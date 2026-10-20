# Arch package update checks

Use this optional checker on an Arch Linux KDE system whose phone and password
authentication have already been configured and tested. It observes configuration
drift after pacman updates. Its watched module path is
`/usr/lib/security/pam_syauth.so`, and all six watched packages must be installed:
`kscreenlocker`, `plasma-desktop`, `pam`, `pambase`, `glibc`, and `sudo`.

The hook also runs when a package changes tracked PAM configuration files, the
custom module, or its GCC/audit/cap-ng libraries. It runs once after a matching
transaction completes. This integration comes from
[D3SOX commit 4e84a76a](https://github.com/D3SOX/syauth/commit/4e84a76abdee049c32f771a4f658d169862e1ac1).

## Install after testing authentication

First test sudo, phone approval using your configured lockscreen trigger,
password authentication, and password fallback after a phone timeout. Then
enable the checker that the syauth package ships:

```sh
sh /usr/lib/syauth/install.sh update-check
```

The installer preserves the PAM setup and uses or adds:

- `/usr/lib/syauth/check-pam-update`, from the syauth package, using the Python standard library.
- `/etc/pacman.d/hooks/95-syauth-check.hook`, the pacman hook.
- `/var/lib/syauth-update-check/baseline.json`, hashes and package versions from the tested setup.

Installation refuses an existing hook or baseline directory, and enables the
hook only after baseline recording and the initial check succeed. Failure
removes the newly created hook and baseline.

## Review findings and accept a baseline

Run checks as your desktop user:

```sh
/usr/lib/syauth/check-pam-update
```

The checker reports changed or missing local PAM files, changed packaged
defaults, relevant `.pacnew` files, package version changes, and unresolved module
libraries or symbols. It invokes `ldd -r` only when the module hash matches the
recorded baseline. The module must be owned by root, contain an ELF header, and
have no group or world write permission.

Checks leave the files and baseline unchanged. A successful check means tracked
files and package versions match and module dependencies resolve; authentication
still needs to be tested after relevant updates. The checker does not modify PAM
rules or invoke phone approval.

Review findings, compare packaged defaults with local overrides, resolve relevant
`.pacnew` files, and test your configured authentication paths. Only then record
the accepted state:

```sh
sudo /usr/lib/syauth/check-pam-update --record-baseline
```

Recording refuses missing watched packages, unresolved `.pacnew` files, or a
module with loader problems. A failed recording leaves the previous baseline
intact. The hook never records a baseline, so findings persist until explicitly
accepted. `--baseline PATH` selects a different baseline file for manual checks.

Exit codes are `0` for a passing check, `1` when review is needed, and `2` when the
check cannot complete. Hook findings occur after the package transaction and do
not roll it back.

## Remove the optional integration

This command removes the hook while preserving phone authentication:

```sh
sudo rm /etc/pacman.d/hooks/95-syauth-check.hook
```

Keep the baseline for reference, or remove it explicitly:

```sh
sudo rm /var/lib/syauth-update-check/baseline.json
sudo rmdir /var/lib/syauth-update-check
```

Run private fixture and command-line tests without an Arch installation:

```sh
python3 -m unittest discover -s tests -p test_pam_update_check.py -v
```
