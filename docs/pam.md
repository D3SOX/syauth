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

## KDE: use its parallel fingerprint stack

KDE's lock screen can run `kde-fingerprint` authentication alongside its normal
`kde` password stack. Putting the waiting phone module into `kde` caused an unlock
loop and hid the password path on the tested laptop. Keep `kde` unchanged.

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

If recovering from the earlier direct-`kde` configuration, restore its original
local file, or delete `/etc/pam.d/kde` only if it was originally absent so KDE uses
`/usr/lib/pam.d/kde` again. Stopping the phone daemon alone does not repair an
incorrect PAM stack. On the tested laptop KDE Connect provided an independent
way back to the desktop during recovery; prepare your own recovery path first.
