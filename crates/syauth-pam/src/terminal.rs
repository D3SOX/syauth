//! Cancellable terminal input for the opt-in sudo password/phone race.

use std::{
    fs::{File, OpenOptions},
    io::{self, Read, Write},
    os::fd::{AsRawFd, FromRawFd, OwnedFd},
    os::unix::net::UnixStream,
    time::{Duration, Instant},
};

use syauth_presenced::{LENGTH_PREFIX_BYTES, MAX_FRAME_LEN, Response, decode_frame};

const PASSWORD_CAPACITY: usize = 512;
const INPUT_TIMEOUT: Duration = Duration::from_secs(300);
const PROMPT: &[u8] = b"Password or approve on your phone: ";

/// Authenticate with a cancellable terminal prompt. PAM retains its own copy
/// of a submitted password; the stack's password module validates that copy.
///
/// # Safety
/// `pamh` must be a live libpam authentication handle on the calling thread.
pub(crate) unsafe fn authenticate(cfg: &crate::config::Config, pamh: *mut pam_sys::PamHandle) -> crate::auth::AuthOutcome {
    use crate::auth::{self, AuthOutcome};
    use syauth_presenced::OUTCOME_REASON_TRANSPORT_ERROR;
    if pamh.is_null() {
        return AuthOutcome::AuthErr {
            reason: "invalid-pam-handle",
            peer_id: None,
        };
    }
    let outcome = auth::authenticate_inner(cfg, |path, peer_id, nonce, timeout| {
        let unavailable = || AuthOutcome::AuthInfoUnavail {
            reason: OUTCOME_REASON_TRANSPORT_ERROR,
            peer_id: Some(peer_id.to_owned()),
        };
        let mut stream = UnixStream::connect(path).map_err(|_| unavailable())?;
        stream
            .set_write_timeout(Some(auth::DAEMON_WRITE_TIMEOUT))
            .map_err(|_| unavailable())?;
        syauth_presenced::write_frame_blocking(
            &mut stream,
            &syauth_presenced::Request::Challenge {
                peer_id: peer_id.to_owned(),
                nonce: nonce.to_vec(),
            },
        )
        .map_err(|_| unavailable())?;
        match select(&mut stream, timeout, cfg.pwfeedback) {
            Ok(Selection::Phone(reply)) => Ok(reply),
            Ok(Selection::Password(secret)) => {
                // SAFETY: the caller owns the live PAM handle. The secret is
                // NUL-terminated and libpam copies it before returning. Its
                // local allocation is wiped immediately on leaving this arm.
                let code = unsafe { pam_sys::raw::pam_set_item(pamh, pam_sys::PamItemType::AUTHTOK as i32, secret.as_ptr().cast()) };
                Err(if code == crate::entry::PAM_SUCCESS {
                    AuthOutcome::PasswordSubmitted
                } else {
                    unavailable()
                })
            }
            Err(error) if error.kind() == io::ErrorKind::Interrupted => Err(AuthOutcome::AuthErr {
                reason: "interrupted",
                peer_id: None,
            }),
            Err(_) => Err(unavailable()),
        }
    });
    if !matches!(outcome, AuthOutcome::PasswordSubmitted) {
        let _ = auth::append_last_log(cfg, &outcome);
    }
    outcome
}

pub(crate) struct Secret([u8; PASSWORD_CAPACITY]);

impl Secret {
    pub(crate) fn as_ptr(&self) -> *const libc::c_char {
        self.0.as_ptr().cast()
    }
}

impl Drop for Secret {
    fn drop(&mut self) {
        // SAFETY: the entire owned array is writable. explicit_bzero cannot
        // be optimized away and no reference to the password escapes Drop.
        unsafe { libc::explicit_bzero(self.0.as_mut_ptr().cast(), self.0.len()) };
    }
}

pub(crate) enum Selection {
    Phone(Response),
    Password(Box<Secret>),
}

struct SignalGuard {
    fd: OwnedFd,
    previous: libc::sigset_t,
}

impl SignalGuard {
    fn new() -> io::Result<Self> {
        // SAFETY: both signal sets are initialized before use; pthread_sigmask
        // affects only this calling thread. signalfd returns a new owned fd.
        unsafe {
            let mut set = std::mem::zeroed();
            let mut previous = std::mem::zeroed();
            libc::sigemptyset(&mut set);
            for signal in [libc::SIGINT, libc::SIGQUIT, libc::SIGHUP, libc::SIGTERM, libc::SIGTSTP] {
                libc::sigaddset(&mut set, signal);
            }
            let error = libc::pthread_sigmask(libc::SIG_BLOCK, &set, &mut previous);
            if error != 0 {
                return Err(io::Error::from_raw_os_error(error));
            }
            let fd = libc::signalfd(-1, &set, libc::SFD_CLOEXEC | libc::SFD_NONBLOCK);
            if fd < 0 {
                let error = io::Error::last_os_error();
                libc::pthread_sigmask(libc::SIG_SETMASK, &previous, std::ptr::null_mut());
                return Err(error);
            }
            Ok(Self {
                fd: OwnedFd::from_raw_fd(fd),
                previous,
            })
        }
    }
}

impl Drop for SignalGuard {
    fn drop(&mut self) {
        // SAFETY: previous was initialized by pthread_sigmask. Signals remain
        // pending in the kernel; restoring the mask delivers them only after
        // Terminal has restored echo and discarded any unfinished password.
        unsafe { libc::pthread_sigmask(libc::SIG_SETMASK, &self.previous, std::ptr::null_mut()) };
    }
}

struct Terminal {
    file: File,
    previous: libc::termios,
    feedback: Option<Feedback>,
}

impl Terminal {
    fn new(file: File, feedback: bool) -> io::Result<Self> {
        // SAFETY: file is owned and live, previous is writable, and tcgetattr
        // initializes it before we read it. A failed call returns immediately.
        let previous = unsafe {
            let mut previous = std::mem::zeroed();
            if libc::tcgetattr(file.as_raw_fd(), &mut previous) != 0 {
                return Err(io::Error::last_os_error());
            }
            previous
        };
        let mut mode = previous;
        mode.c_lflag &= !(libc::ECHO | libc::ECHONL);
        if feedback {
            mode.c_lflag &= !libc::ICANON;
            mode.c_cc[libc::VMIN] = 1;
            mode.c_cc[libc::VTIME] = 0;
        } else {
            mode.c_lflag |= libc::ICANON;
        }
        // SAFETY: mode is initialized and fd remains live. Kernel editing is
        // retained without feedback; masked input uses the bounded editor below.
        if unsafe { libc::tcsetattr(file.as_raw_fd(), libc::TCSANOW, &mode) } != 0 {
            return Err(io::Error::last_os_error());
        }
        let mut terminal = Self {
            file,
            previous,
            feedback: feedback.then(Feedback::new),
        };
        terminal.file.write_all(PROMPT)?;
        Ok(terminal)
    }

    fn password(&mut self) -> io::Result<Option<Box<Secret>>> {
        if let Some(feedback) = &mut self.feedback {
            return feedback.read(&mut self.file, &self.previous);
        }
        let mut secret = Box::new(Secret([0; PASSWORD_CAPACITY]));
        let count = self.file.read(&mut secret.0)?;
        if count == 0 || secret.0[count - 1] != b'\n' || secret.0[..count - 1].contains(&0) {
            return Err(io::Error::new(io::ErrorKind::InvalidInput, "invalid password input"));
        }
        secret.0[count - 1] = 0;
        Ok(Some(secret))
    }
}

struct Feedback {
    secret: Box<Secret>,
    length: usize,
    quoted: bool,
}

impl Feedback {
    fn new() -> Self {
        Self {
            secret: Box::new(Secret([0; PASSWORD_CAPACITY])),
            length: 0,
            quoted: false,
        }
    }

    fn erase(&mut self, file: &mut File) -> io::Result<()> {
        if self.length == 0 {
            return Ok(());
        }
        self.length -= 1;
        while self.length > 0 && self.secret.0[self.length] & 0xc0 == 0x80 {
            self.secret.0[self.length] = 0;
            self.length -= 1;
        }
        self.secret.0[self.length] = 0;
        file.write_all(b"\x08 \x08")
    }

    fn edit(&mut self, file: &mut File, mode: &libc::termios, byte: u8) -> io::Result<bool> {
        if byte == mode.c_cc[libc::VERASE] || byte == b'\x08' {
            self.erase(file)?;
            return Ok(true);
        }
        if byte == mode.c_cc[libc::VKILL] || byte == mode.c_cc[libc::VWERASE] {
            let kill = byte == mode.c_cc[libc::VKILL];
            while self.length > 0 && self.secret.0[self.length - 1].is_ascii_whitespace() {
                self.erase(file)?;
            }
            while self.length > 0 && (kill || !self.secret.0[self.length - 1].is_ascii_whitespace()) {
                self.erase(file)?;
            }
            return Ok(true);
        }
        if byte == mode.c_cc[libc::VLNEXT] {
            self.quoted = true;
            return Ok(true);
        }
        if byte == mode.c_cc[libc::VEOF] {
            return Err(io::Error::new(io::ErrorKind::InvalidInput, "password input ended"));
        }
        Ok(false)
    }

    fn read(&mut self, file: &mut File, mode: &libc::termios) -> io::Result<Option<Box<Secret>>> {
        let mut byte = [0];
        file.read_exact(&mut byte)?;
        let byte = byte[0];
        if !self.quoted {
            if byte == b'\n' {
                self.length = 0;
                return Ok(Some(std::mem::replace(&mut self.secret, Box::new(Secret([0; PASSWORD_CAPACITY])))));
            }
            if self.edit(file, mode, byte)? {
                return Ok(None);
            }
        }
        self.quoted = false;
        if byte == 0 || self.length >= PASSWORD_CAPACITY - 1 {
            return Err(io::Error::new(io::ErrorKind::InvalidInput, "invalid password input"));
        }
        self.secret.0[self.length] = byte;
        self.length += 1;
        if byte & 0xc0 != 0x80 {
            file.write_all(b"*")?;
        }
        Ok(None)
    }
}

impl Drop for Terminal {
    fn drop(&mut self) {
        // SAFETY: the fd and saved terminal attributes remain live throughout
        // Drop. Discard pending password bytes before re-enabling echo, so they
        // cannot become input to the command sudo starts after phone approval.
        unsafe {
            libc::tcflush(self.file.as_raw_fd(), libc::TCIFLUSH);
            libc::tcsetattr(self.file.as_raw_fd(), libc::TCSANOW, &self.previous);
        }
        let _ = self.file.write_all(b"\n");
    }
}

/// Open only this process's controlling terminal, never a PAM-provided path.
pub(crate) fn select(stream: &mut UnixStream, timeout: Duration, feedback: bool) -> io::Result<Selection> {
    let file = OpenOptions::new().read(true).write(true).open("/dev/tty")?;
    // SAFETY: both calls inspect process/tty state without retaining pointers.
    if unsafe { libc::tcgetpgrp(file.as_raw_fd()) != libc::getpgrp() } {
        return Err(io::Error::new(io::ErrorKind::PermissionDenied, "terminal is not in the foreground"));
    }
    let signals = SignalGuard::new()?;
    let mut terminal = Terminal::new(file, feedback)?;
    race(&mut terminal, stream, timeout, signals.fd.as_raw_fd())
}

fn race(terminal: &mut Terminal, stream: &mut UnixStream, timeout: Duration, signal_fd: i32) -> io::Result<Selection> {
    stream.set_nonblocking(true)?;
    let started = Instant::now();
    let mut phone_active = true;
    let mut response = Vec::new();
    loop {
        if started.elapsed() >= INPUT_TIMEOUT {
            return Err(io::Error::new(io::ErrorKind::TimedOut, "password input timed out"));
        }
        phone_active &= started.elapsed() < timeout;
        let mut fds = [
            libc::pollfd {
                fd: terminal.file.as_raw_fd(),
                events: libc::POLLIN,
                revents: 0,
            },
            libc::pollfd {
                fd: if phone_active { stream.as_raw_fd() } else { -1 },
                events: libc::POLLIN,
                revents: 0,
            },
            libc::pollfd {
                fd: signal_fd,
                events: libc::POLLIN,
                revents: 0,
            },
        ];
        // SAFETY: fds is a live initialized array of exactly three pollfd
        // entries; poll only writes their revents fields during this call.
        if unsafe { libc::poll(fds.as_mut_ptr(), fds.len() as libc::nfds_t, 50) } < 0 {
            let error = io::Error::last_os_error();
            if error.kind() == io::ErrorKind::Interrupted {
                continue;
            }
            return Err(error);
        }
        if fds[2].revents != 0 {
            return Err(io::Error::new(io::ErrorKind::Interrupted, "authentication interrupted"));
        }
        if fds[0].revents != 0 {
            if let Some(secret) = terminal.password()? {
                return Ok(Selection::Password(secret));
            }
        }
        if phone_active && fds[1].revents != 0 {
            match read_response(stream, &mut response) {
                Ok(Some(reply)) if approved(&reply) => return Ok(Selection::Phone(reply)),
                Ok(None) => (),
                _ => phone_active = false,
            }
        }
    }
}

fn approved(response: &Response) -> bool {
    matches!(response, Response::Challenge { ok: true, signature: Some(signature), reason }
        if reason == "ok" && signature.len() == syauth_core::SIGNATURE_LEN)
}

fn read_response(stream: &mut UnixStream, bytes: &mut Vec<u8>) -> io::Result<Option<Response>> {
    let mut chunk = [0; 1024];
    match stream.read(&mut chunk) {
        Ok(0) => return Err(io::ErrorKind::UnexpectedEof.into()),
        Ok(count) => bytes.extend_from_slice(&chunk[..count]),
        Err(error) if error.kind() == io::ErrorKind::WouldBlock => return Ok(None),
        Err(error) => return Err(error),
    }
    if bytes.len() < LENGTH_PREFIX_BYTES {
        return Ok(None);
    }
    let length = u32::from_be_bytes(bytes[..LENGTH_PREFIX_BYTES].try_into().map_err(io::Error::other)?) as usize;
    if length > MAX_FRAME_LEN {
        return Err(io::ErrorKind::InvalidData.into());
    }
    if bytes.len() < LENGTH_PREFIX_BYTES + length {
        return Ok(None);
    }
    decode_frame(&bytes[LENGTH_PREFIX_BYTES..]).map(Some).map_err(io::Error::other)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{os::fd::FromRawFd, sync::mpsc, thread};
    use syauth_presenced::write_frame_blocking;

    fn pty() -> (File, File) {
        let (mut master, mut slave) = (-1, -1);
        // SAFETY: openpty initializes the two out-fds; null optional arguments
        // request default attributes. Each resulting fd is adopted exactly once.
        unsafe {
            assert_eq!(
                libc::openpty(&mut master, &mut slave, std::ptr::null_mut(), std::ptr::null(), std::ptr::null()),
                0
            );
            (File::from_raw_fd(master), File::from_raw_fd(slave))
        }
    }

    fn prompt(master: &mut File) {
        let mut bytes = vec![0; PROMPT.len()];
        master.read_exact(&mut bytes).unwrap();
        assert_eq!(bytes, PROMPT);
    }

    #[test]
    fn phone_approval_finishes_without_enter_and_discards_partial_password() {
        let (mut master, slave) = pty();
        let inspect = slave.try_clone().unwrap();
        let (mut client, mut daemon) = UnixStream::pair().unwrap();
        let worker = thread::spawn(move || {
            let mut tty = Terminal::new(slave, false).unwrap();
            assert!(matches!(
                race(&mut tty, &mut client, Duration::from_secs(2), -1).unwrap(),
                Selection::Phone(_)
            ));
        });
        prompt(&mut master);
        master.write_all(b"partial-secret").unwrap();
        write_frame_blocking(
            &mut daemon,
            &Response::Challenge {
                ok: true,
                signature: Some(vec![1; syauth_core::SIGNATURE_LEN]),
                reason: "ok".into(),
            },
        )
        .unwrap();
        worker.join().unwrap();
        // SAFETY: the live slave fd and writable termios/ioctl out-pointers
        // are valid. These calls inspect actual kernel terminal state.
        unsafe {
            let mut attributes = std::mem::zeroed();
            assert_eq!(libc::tcgetattr(inspect.as_raw_fd(), &mut attributes), 0);
            assert_ne!(attributes.c_lflag & libc::ECHO, 0, "echo restored");
            let mut pending = -1;
            assert_eq!(libc::ioctl(inspect.as_raw_fd(), libc::FIONREAD, &mut pending), 0);
            assert_eq!(pending, 0, "partial password cannot leak into the privileged command");
        }
    }

    #[test]
    fn password_can_win_while_phone_has_not_replied() {
        let (mut master, slave) = pty();
        let (mut client, _daemon) = UnixStream::pair().unwrap();
        let (done, result) = mpsc::channel();
        let worker = thread::spawn(move || {
            let mut tty = Terminal::new(slave, false).unwrap();
            let Selection::Password(secret) = race(&mut tty, &mut client, Duration::from_secs(2), -1).unwrap() else {
                panic!("password wins")
            };
            assert_eq!(&secret.0[..14], b"test-password\0");
            done.send(()).unwrap();
        });
        prompt(&mut master);
        master.write_all(b"test-password\n").unwrap();
        result
            .recv_timeout(Duration::from_secs(1))
            .expect("password must not wait for phone timeout");
        worker.join().unwrap();
    }

    #[test]
    fn denial_preserves_password_input() {
        let (mut master, slave) = pty();
        let (mut client, mut daemon) = UnixStream::pair().unwrap();
        let worker = thread::spawn(move || {
            let mut tty = Terminal::new(slave, false).unwrap();
            let Selection::Password(secret) = race(&mut tty, &mut client, Duration::from_secs(2), -1).unwrap() else {
                panic!("password remains available")
            };
            assert_eq!(&secret.0[..5], b"abcd\0");
        });
        prompt(&mut master);
        master.write_all(b"ab").unwrap();
        write_frame_blocking(
            &mut daemon,
            &Response::Challenge {
                ok: false,
                signature: None,
                reason: "denied".into(),
            },
        )
        .unwrap();
        master.write_all(b"cd\n").unwrap();
        worker.join().unwrap();
    }
}
