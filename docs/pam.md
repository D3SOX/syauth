# sudo and KDE screen unlock on Arch

Complete [desktop installation and pairing](getting-started.md) first. The examples
below assume login name `LOCAL_USER` and UID `1000`; substitute both with your
actual `id -un` and `id -u`. The daemon runs as that user, so PAM must explicitly
connect to `/run/user/1000/syauth/auth.sock`, including when sudo authenticates as
root. A user guard ensures other accounts keep their original authentication.

## Back up before editing

Preserve existing local overrides and record which files were absent. For example,
run this helper with `sudo bash /path/to/helper.sh` from your KDE session:

```sh
#!/usr/bin/env bash
set -eu
backup=/var/lib/syauth-pam-backup
if [ -e "$backup" ]; then
  echo 'Backup already exists; do not overwrite the originals.' >&2
  exit 1
fi
install -d -m700 "$backup"
for service in sudo kde kde-fingerprint; do
  if [ -e "/etc/pam.d/$service" ]; then
    cp -a "/etc/pam.d/$service" "$backup/$service"
  else
    touch "$backup/$service.was-absent"
  fi
done
```

Use a separate scratch directory for proposed files and inspect their complete
contents before installing them. Do not edit `system-auth`, `system-local-login`,
SDDM, login, or the vendor files under `/usr/lib/pam.d` for this setup.

## Test the module privately first

If `pamtester` is available, create a temporary service named `syauth-test` with
only this line, install it into `/etc/pam.d/syauth-test`, and run
`pamtester syauth-test LOCAL_USER authenticate` as the desktop user:

```pam
auth required pam_syauth.so socket=/run/user/1000/syauth/auth.sock
```

The Pixel fingerprint prompt opens automatically; scanning should succeed.
Remove the temporary service afterward. On the tested laptop, an equivalent
isolated test used Python/ctypes with
`pam_start_confdir` and a temporary configuration directory, avoiding any change
to the active PAM services. Phone unavailable/denied must fail this private test;
in the real stacks below, `sufficient` allows the original authentication to run.

## sudo: insert before the existing auth stack

Copy your existing `/etc/pam.d/sudo` into the scratch directory. Immediately before
its first auth line, insert these lines, leaving all original lines intact:

```pam
auth [success=1 default=ignore] pam_succeed_if.so user != LOCAL_USER quiet
auth sufficient pam_syauth.so socket=/run/user/1000/syauth/auth.sock
```

For the selected user, syauth is tried first; other users skip it. The original
`auth include system-auth` remains afterward for password and existing factors.
Install the reviewed file with:

```sh
sudo install -m644 /path/to/scratch/sudo /etc/pam.d/sudo
```

Test `sudo -k; sudo true` and approve the Pixel biometric prompt. Then repeat with
the phone unavailable or select Disallow on the approval screen. Verify that
the original password path still works before proceeding.

## KDE: request the phone with an empty submission

Use `on_empty_password` to wait for a submission in KDE's password field.
Enter a password for normal password authentication, or leave the field empty
and press Enter to request the phone. Opening the lock screen sends no phone
request. An empty submission still requires a verified phone response.

Build and install the updated PAM module before adding the option. Older
modules ignore unknown options and would request the phone immediately.

```sh
cargo build --release -p syauth-pam
sudo install -m644 target/release/libpam_syauth.so /usr/lib/security/pam_syauth.so.new
sudo mv -T /usr/lib/security/pam_syauth.so.new /usr/lib/security/pam_syauth.so
cargo test -p syauth-pam --test pam_submission
```

The tests load the real module through libpam in a private configuration
directory. They cover waiting for input, password reuse, incorrect passwords,
empty input, cancellation, and missing conversation responses.

Back up both KDE service files. If you already enabled the automatic setup
below, remove its three-line phone block from `kde-fingerprint`, including
the `pam_succeed_if` guard and `pam_echo` message. Preserve the remaining local
fingerprint stack. Leaving that block installed would still request the phone
automatically.

On Arch with the default `kde` service, use this `/etc/pam.d/kde` file after
substituting your username and UID. If you have a custom service, preserve its
mandatory checks and password modules instead of replacing it with this example.

```pam
#%PAM-1.0
auth required pam_shells.so
auth requisite pam_nologin.so
auth requisite pam_faillock.so preauth
auth [success=1 default=ignore] pam_succeed_if.so user != LOCAL_USER quiet
auth sufficient pam_syauth.so on_empty_password socket=/run/user/1000/syauth/auth.sock
auth include system-auth

account include system-local-login
password include system-local-login
session include system-local-login
```

The guard keeps other users on their normal password stack. The checks before
syauth reject prohibited shells, disabled logins, and locked accounts. Account
checks still run after phone authentication.

To show the instruction above the password field on Plasma 6.7.91, enable its
existing prompt setting as your desktop user. No KDE rebuild or QML edit is needed.

```sh
kwriteconfig6 --file kscreenlockerrc --group UI --key ShowPromptInRegularAuthenticator --type bool true
sudo install -m644 /path/to/scratch/kde /etc/pam.d/kde
```

Test the proposed service privately before installing it, then check:

1. Lock with Meta+L and show the password field. The phone should stay quiet.
2. Leave the field empty and press Enter. Approve with the Pixel fingerprint.
3. Lock again and enter the laptop password. No phone prompt should appear.
4. Submit an empty field, then decline or let the phone request expire. Enter
   the laptop password when the password prompt returns.

This mode uses a single PAM transaction. After an empty submission, password
retry follows phone denial or the eight-second phone deadline. It does not offer
simultaneous password unlock while the phone request waits. Keep sudo's module
line without `on_empty_password` to retain its automatic phone prompt.

On Plasma/kscreenlocker 6.7.91, the installed KDE worker passed private tests
for password authentication and password retry after an empty submission. A
private test through that worker also requested and accepted a fingerprint
approval from the Pixel 8 Pro. Test the real lock screen before relying on it.

## KDE: request the phone automatically

KDE's lock screen can run `kde-fingerprint` authentication alongside its normal
`kde` password stack. Putting the phone module into `kde` without a password
conversation caused an unlock loop on the tested laptop. For this automatic
mode, keep `kde` unchanged and use the parallel stack.

Copy your existing `/etc/pam.d/kde-fingerprint` if present, otherwise copy
`/usr/lib/pam.d/kde-fingerprint` to the scratch directory. Preserve the distro's
mandatory account/authentication checks. Insert this block after the existing
`pam_faillock.so preauth` check and before `pam_fprintd.so`:

```pam
auth [success=2 default=ignore] pam_succeed_if.so user != LOCAL_USER quiet
auth optional pam_echo.so Approve this unlock on your phone.
auth sufficient pam_syauth.so socket=/run/user/1000/syauth/auth.sock
```

The exact resulting file on the tested Arch installation was:

```pam
auth required pam_shells.so
auth requisite pam_nologin.so
auth requisite pam_faillock.so preauth
auth [success=2 default=ignore] pam_succeed_if.so user != LOCAL_USER quiet
auth optional pam_echo.so Approve this unlock on your phone.
auth sufficient pam_syauth.so socket=/run/user/1000/syauth/auth.sock
-auth required pam_fprintd.so
auth optional pam_permit.so
auth required pam_env.so
account include system-local-login
password required pam_deny.so
session include system-local-login
```

Keep `pam_echo`: its informational message lets KDE recognize that the parallel
authenticator has prompted. Without it, this KDE version can discard a successful
result during its no-password unlock state transition. The guard skips both the
message and syauth for other users. The existing local fingerprint stack stays
afterward; a phone denial never becomes success through `pam_permit` when the
required fingerprint module fails.

```sh
sudo install -m644 /path/to/scratch/kde-fingerprint /etc/pam.d/kde-fingerprint
```

Test these paths separately:

1. Meta+L, activate unlock with Enter if needed, then scan the phone fingerprint
   when its prompt opens automatically.
   KDE should unlock and its password field should remain available while waiting.
2. Meta+L again; enter the laptop password without approving on the phone. KDE
   should unlock and the pending phone dialog should close automatically.
3. With the phone unavailable, verify that the normal KDE password still unlocks.

The tests were completed on Plasma/kscreenlocker 6.7.91. Older KDE builds may have
different parallel authenticator behavior; check the vendor stack and test the
password path. Existing distro files can change on upgrades, so compare local
`kde-fingerprint` overrides with new vendor versions.

## Module options and results

| Option | Behavior |
| --- | --- |
| `socket=PATH` | Select the daemon socket. The default is `$XDG_RUNTIME_DIR/syauth/auth.sock`, or `/run/user/$UID/syauth/auth.sock` if unset. |
| `on_empty_password` | Wait for a submission. Request the phone only for an empty response; cache typed passwords for the next module. Off by default. |

The module logs through syslog with facility `LOG_AUTHPRIV` and tag `pam_syauth`.
It never logs submitted passwords.

| Result | Meaning |
| --- | --- |
| `PAM_SUCCESS` | The daemon verified the phone response. |
| `PAM_IGNORE` | A nonempty password was submitted in `on_empty_password` mode. The next password module should reuse `PAM_AUTHTOK`, such as with `try_first_pass`. |
| `PAM_AUTH_ERR` | The phone declined, verification failed, the submission conversation failed, or Rust caught a panic. |
| `PAM_AUTHINFO_UNAVAIL` | The daemon or peer was unavailable, busy, or timed out. |

With `sufficient`, failure or unavailability continues to the remaining
authentication stack. In empty-submission mode, syauth clears the empty token
before contacting the daemon so the password module can ask for a password.

## Roll back

Run this helper with `sudo bash /path/to/rollback.sh`. It restores original
local files and removes only overrides that were absent before setup:

```sh
#!/usr/bin/env bash
set -eu
backup=/var/lib/syauth-pam-backup
for service in sudo kde kde-fingerprint; do
  if [ -f "$backup/$service.was-absent" ]; then
    rm -f "/etc/pam.d/$service"
  elif [ -f "$backup/$service" ]; then
    cp -a "$backup/$service" "/etc/pam.d/$service"
  else
    echo "Missing backup for $service; refusing to guess." >&2
    exit 1
  fi
done
```

If you enabled the prompt instruction, restore the previous value of
`UI/ShowPromptInRegularAuthenticator` in `kscreenlockerrc`. If it was absent,
remove just that setting with:

```sh
kwriteconfig6 --file kscreenlockerrc --group UI --key ShowPromptInRegularAuthenticator --delete
```

If recovering from the earlier automatic direct-`kde` configuration, restore its original
local file, or delete `/etc/pam.d/kde` only if it was originally absent so KDE uses
`/usr/lib/pam.d/kde` again. Stopping the phone daemon alone does not repair an
incorrect PAM stack. On the tested laptop KDE Connect provided an independent
way back to the desktop during recovery; prepare your own recovery path first.
