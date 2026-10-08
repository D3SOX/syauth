//! Load the real cdylib in libpam using a private configuration directory.
//! These tests never modify /etc/pam.d or need a phone or root privileges.

use std::{
    collections::VecDeque,
    ffi::{CString, c_char, c_int, c_void},
    panic::{AssertUnwindSafe, catch_unwind},
    path::PathBuf,
    process::Command,
    ptr,
    sync::{OnceLock, mpsc},
    thread,
    time::Duration,
};

use pam_sys::{PamConversation, PamHandle, PamMessage, PamResponse, raw};
use tempfile::TempDir;

#[link(name = "pam")]
unsafe extern "C" {
    fn pam_start_confdir(
        service: *const c_char,
        user: *const c_char,
        conversation: *const PamConversation,
        confdir: *const c_char,
        handle: *mut *mut PamHandle,
    ) -> c_int;
}

enum Reply {
    Text(CString),
    Cancel,
    Missing,
    Wait(mpsc::Sender<()>, mpsc::Receiver<CString>),
}

struct Conversation {
    replies: VecDeque<Reply>,
    prompts: usize,
}

extern "C" fn converse(count: c_int, messages: *mut *mut PamMessage, responses: *mut *mut PamResponse, data: *mut c_void) -> c_int {
    catch_unwind(AssertUnwindSafe(|| {
        if count != 1 || messages.is_null() || responses.is_null() || data.is_null() {
            return 19;
        }
        // SAFETY: libpam passes one live message, a writable response pointer,
        // and the exclusively borrowed Conversation supplied to pam_start_confdir.
        let (state, style) = unsafe { (&mut *data.cast::<Conversation>(), (**messages).msg_style) };
        let reply = if style == 1 || style == 2 {
            state.prompts += 1;
            match state.replies.pop_front() {
                Some(Reply::Text(text)) => Some(text),
                Some(Reply::Missing) => None,
                Some(Reply::Wait(ready, response)) => {
                    if ready.send(()).is_err() {
                        return 19;
                    }
                    match response.recv_timeout(Duration::from_secs(5)) {
                        Ok(text) => Some(text),
                        Err(_) => return 19,
                    }
                }
                Some(Reply::Cancel) | None => return 19,
            }
        } else {
            None
        };
        // SAFETY: libc allocation matches libpam's free contract. The response
        // remains owned by this callback until its out-pointer is assigned.
        unsafe {
            let allocated = libc::calloc(1, size_of::<PamResponse>()).cast::<PamResponse>();
            if allocated.is_null() {
                return 5;
            }
            if let Some(text) = reply {
                (*allocated).resp = libc::strdup(text.as_ptr());
                if (*allocated).resp.is_null() {
                    libc::free(allocated.cast());
                    return 5;
                }
            }
            *responses = allocated;
        }
        0
    }))
    .unwrap_or(19)
}

fn fixture() -> PathBuf {
    static BUILT: OnceLock<TempDir> = OnceLock::new();
    BUILT
        .get_or_init(|| {
            let dir = tempfile::tempdir().unwrap();
            let output = Command::new("cc")
                .args(["-shared", "-fPIC", "-o"])
                .arg(dir.path().join("pam_submission.so"))
                .arg(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/pam_submission.c"))
                .args(["-lpam", "-ldl"])
                .output()
                .expect("compile private PAM fixture");
            assert!(output.status.success(), "{}", String::from_utf8_lossy(&output.stderr));
            dir
        })
        .path()
        .join("pam_submission.so")
}

fn authenticate(expected: Option<i32>, options: &str, fallback: &str, replies: Vec<Reply>) -> (i32, usize) {
    let dir = tempfile::tempdir().unwrap();
    let module = std::env::current_exe().unwrap().parent().unwrap().join("libpam_syauth.so");
    assert!(module.is_file(), "cargo must build the PAM cdylib at {}", module.display());
    let fixture = fixture();
    let first = if let Some(expected) = expected {
        format!("auth required {} module={} {expected}", fixture.display(), module.display())
    } else {
        format!("auth sufficient {}", module.display())
    };
    let config = format!("{first} socket={}/absent.sock {options}\n{fallback}", dir.path().display());
    std::fs::write(dir.path().join("syauth-submission-test"), config).unwrap();
    let mut state = Conversation {
        replies: replies.into(),
        prompts: 0,
    };
    let conversation = PamConversation {
        conv: Some(converse),
        data_ptr: ptr::from_mut(&mut state).cast(),
    };
    let confdir = CString::new(dir.path().as_os_str().as_encoded_bytes()).unwrap();
    let mut handle = ptr::null_mut();
    // SAFETY: all C strings and the conversation state outlive this transaction.
    // libpam owns handle; we end it exactly once after authentication.
    let result = unsafe {
        let started = pam_start_confdir(
            c"syauth-submission-test".as_ptr(),
            c"syauth-test-user".as_ptr(),
            &conversation,
            confdir.as_ptr(),
            &mut handle,
        );
        assert_eq!(started, 0);
        let result = raw::pam_authenticate(handle, 0);
        raw::pam_end(handle, result);
        result
    };
    (result, state.prompts)
}

fn text(value: &str) -> Reply {
    Reply::Text(CString::new(value).unwrap())
}

#[test]
fn typed_password_is_ignored_and_cached_for_the_password_module() {
    let password = format!("auth required {} test-password\n", fixture().display());
    assert_eq!(
        authenticate(Some(25), "on_empty_password", &password, vec![text("test-password")]),
        (0, 1)
    );
}

#[test]
fn wrong_password_still_fails_password_authentication() {
    let password = format!("auth required {} test-password\n", fixture().display());
    assert_eq!(
        authenticate(Some(25), "on_empty_password", &password, vec![text("wrong-password")]),
        (7, 1)
    );
}

#[test]
fn empty_submission_selects_phone_and_clears_the_selector_before_password_retry() {
    let password = format!("auth required {} test-password require-cleared\n", fixture().display());
    assert_eq!(
        authenticate(Some(9), "on_empty_password", &password, vec![text(""), text("test-password")]),
        (0, 2)
    );
}

#[test]
fn cancelled_conversation_does_not_request_the_phone() {
    assert_eq!(authenticate(Some(7), "on_empty_password", "", vec![Reply::Cancel]), (0, 1));
}

#[test]
fn missing_response_is_not_an_empty_submission() {
    assert_eq!(authenticate(Some(7), "on_empty_password", "", vec![Reply::Missing]), (0, 1));
}

#[test]
fn default_mode_does_not_ask_for_a_password() {
    assert_eq!(authenticate(Some(9), "", "", vec![]), (0, 0));
}

#[test]
fn authentication_waits_for_an_actual_submission() {
    let (ready_tx, ready_rx) = mpsc::channel();
    let (reply_tx, reply_rx) = mpsc::channel();
    let (done_tx, done_rx) = mpsc::channel();
    let worker = thread::spawn(move || {
        let result = authenticate(Some(25), "on_empty_password", "", vec![Reply::Wait(ready_tx, reply_rx)]);
        done_tx.send(result).unwrap();
    });
    ready_rx
        .recv_timeout(Duration::from_secs(5))
        .expect("PAM waits at the password prompt");
    assert!(
        done_rx.recv_timeout(Duration::from_millis(100)).is_err(),
        "authentication must still wait"
    );
    reply_tx.send(CString::new("test-password").unwrap()).unwrap();
    assert_eq!(done_rx.recv_timeout(Duration::from_secs(5)).unwrap(), (0, 1));
    worker.join().unwrap();
}

#[test]
fn sufficient_stack_reuses_typed_password_without_granting_wrong_passwords() {
    let password = format!("auth required {} test-password\n", fixture().display());
    assert_eq!(
        authenticate(None, "on_empty_password", &password, vec![text("test-password")]),
        (0, 1)
    );
    assert_eq!(
        authenticate(None, "on_empty_password", &password, vec![text("wrong-password")]),
        (7, 1)
    );
}

#[test]
fn sufficient_stack_prompts_for_password_after_phone_unavailability() {
    let password = format!("auth required {} test-password require-cleared\n", fixture().display());
    assert_eq!(
        authenticate(None, "on_empty_password", &password, vec![text(""), text("test-password")]),
        (0, 2)
    );
}
