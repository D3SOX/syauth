#!/bin/sh
# Install syauth from a verified release package or a local source build, and
# optionally set up Arch Linux/KDE authentication and the Android companion.
# Journeys: specs/journeys/JOURNEY-release-publication.md,
#           specs/journeys/JOURNEY-S-013-pam-install-helper.md
set -eu

REPO_SLUG=D3SOX/syauth
DOCS=https://d3sox.me/syauth
# Tests redirect every system path below a private directory.
ROOT=${SYAUTH_ROOT:-}
LIBDIR=$ROOT/usr/lib/syauth
SHAREDIR=$ROOT/usr/share/syauth
SYSTEM_STATE=$ROOT/var/lib/syauth-installer
APP=com.sy.syauth.android
tab=$(printf '\t')

fail() { printf 'syauth installer: %s\n' "$*" >&2; exit 1; }
run() { printf '+ %s\n' "$*"; "$@"; }
need() {
    for need_tool in "$@"; do
        command -v "$need_tool" >/dev/null 2>&1 || fail "Required command missing: $need_tool"
    done
}
usage() {
    cat <<'EOF'
Usage: install.sh [install] [--version X.Y.Z | --source [DIR]] [--desktop]
                  [--phone-address MAC] [--android SERIAL] [--dry-run]
       install.sh rollback | pair | update-check

install       Install the latest verified release package (default), or with
              --source build a native package from a checkout and install it.
  --desktop   Also configure sudo and KDE screen unlock, live lockscreen status,
              and the user daemon (Arch Linux with Plasma 6.8 or newer).
  --android   Also install the Android app on this ADB device for user 0: the
              signed release APK, or with --source a debug build.
rollback      Restore the files changed by --desktop.
pair          Pair a phone while the daemon is paused.
update-check  Check PAM, packages, and module dependencies after pacman updates.

Supports Debian/Ubuntu, Fedora, openSUSE, and Arch Linux on x86_64/aarch64.
EOF
}

# ---------------------------------------------------------------- files ----

# Refuse a symlink anywhere along a path we write, restore, or read PAM from.
no_symlinks() {
    ns_path=$1
    while [ -n "$ns_path" ] && [ "$ns_path" != / ] && [ "$ns_path" != . ]; do
        [ ! -L "$ns_path" ] || fail "Refusing a symlink in installation path: $ns_path"
        ns_path=$(dirname -- "$ns_path")
    done
}

# Replace a file only after its new contents are complete.
atomic_install() {
    no_symlinks "$2"
    mkdir -p -- "$(dirname -- "$2")"
    ai_temporary=$(mktemp "$(dirname -- "$2")/.syauth-XXXXXXXX")
    if cat -- "$1" > "$ai_temporary" && chmod "$3" "$ai_temporary" && mv -f -- "$ai_temporary" "$2"; then
        return 0
    fi
    rm -f -- "$ai_temporary"
    fail "Cannot write $2"
}

# Swap a directory in place; the old copy stays until the new one is present.
replace_directory() {
    no_symlinks "$2"
    rd_parent=$(dirname -- "$2")
    mkdir -p -- "$rd_parent"
    rd_temporary=$(mktemp -d "$rd_parent/.syauth-restore-XXXXXXXX")
    cp -a -- "$1" "$rd_temporary/package"
    if [ -e "$2" ]; then mv -- "$2" "$rd_temporary/previous"; fi
    if ! mv -- "$rd_temporary/package" "$2"; then
        if [ -e "$rd_temporary/previous" ]; then mv -- "$rd_temporary/previous" "$2"; fi
        rm -rf -- "$rd_temporary"
        fail "Cannot restore $2"
    fi
    rm -rf -- "$rd_temporary"
}

fingerprint() {
    if [ ! -e "$1" ] && [ ! -L "$1" ]; then
        echo absent
        return
    fi
    (
        cd -- "$(dirname -- "$1")"
        find "$(basename -- "$1")" | LC_ALL=C sort | while IFS= read -r entry; do
            printf '%s %s\n' "$entry" "$(stat -c %a -- "$entry")"
            if [ -L "$entry" ]; then readlink -- "$entry"; elif [ -f "$entry" ]; then sha256sum < "$entry"; fi
        done
    ) | sha256sum | cut -d' ' -f1
}

with_lock() {
    no_symlinks "$1"
    mkdir -p -- "$(dirname -- "$1")"
    exec 9>"$1"
    flock -n 9 || fail 'Another syauth installation is running'
}

# --------------------------------------------------------------- backups ----
# A backup directory keeps the originals from the first installation
# (originals), a fingerprint of every installed path (installed), and a
# pending marker while an installation runs, so an interrupted run can be
# rolled back.

backup_remember() {
    no_symlinks "$2"
    mkdir -p -- "$1"
    chmod 700 -- "$1"
    if [ -f "$1/originals" ] && cut -f6- -- "$1/originals" | grep -Fxq -- "$2"; then
        return 0
    fi
    # A new path may also create parent directories; remember the highest one
    # as absent so a restore removes it too.
    if [ ! -e "$2" ] && [ ! -L "$2" ]; then
        br_top=$2
        while [ ! -e "$(dirname -- "$br_top")" ]; do br_top=$(dirname -- "$br_top"); done
        if [ "$br_top" != "$2" ]; then backup_remember "$1" "$br_top"; fi
    fi
    br_slot=0
    if [ -f "$1/originals" ]; then br_slot=$(wc -l < "$1/originals"); fi
    br_meta="-$tab-$tab-"
    if [ -d "$2" ]; then
        cp -a -- "$2" "$1/$br_slot"
        br_kind="dir"
    elif [ -e "$2" ]; then
        cp -p -- "$2" "$1/$br_slot"
        br_kind="file"
    else
        br_kind="absent"
    fi
    if [ "$br_kind" != absent ]; then br_meta=$(stat -c "%a$tab%u$tab%g" -- "$2"); fi
    printf '%s\t%s\t%s\t%s\n' "$br_slot" "$br_kind" "$br_meta" "$2" >> "$1/originals"
}

backup_check() {
    if [ -f "$1/pending" ]; then
        [ "${2:-}" = rollback ] && return 0
        fail "An interrupted installation needs recovery: run 'install.sh rollback'"
    fi
    [ -f "$1/installed" ] || return 0
    while IFS=$tab read -r bc_hash bc_path; do
        [ "$(fingerprint "$bc_path")" = "$bc_hash" ] ||
            fail "Changed since installation: $bc_path. Review backups in $1 before rollback."
    done < "$1/installed"
}

backup_restore() {
    [ "${2:-}" = nocheck ] || backup_check "$1" rollback
    if [ -f "$1/originals" ]; then
        while IFS=$tab read -r rs_slot rs_kind rs_mode rs_uid rs_gid rs_path; do
            no_symlinks "$rs_path"
            case "$rs_kind" in
                absent) rm -rf -- "$rs_path";;
                file) atomic_install "$1/$rs_slot" "$rs_path" "$rs_mode";;
                dir) replace_directory "$1/$rs_slot" "$rs_path";;
            esac
            if [ "$rs_kind" != absent ] && [ "$(id -u)" = 0 ]; then chown "$rs_uid:$rs_gid" -- "$rs_path"; fi
        done < "$1/originals"
    fi
    if [ -f "$1/pending" ]; then
        rs_attempt=$(cat -- "$1/pending")
        case "$(basename -- "$rs_attempt")" in
            .syauth-attempt-*) [ "$(dirname -- "$rs_attempt")" != "$(dirname -- "$1")" ] || rm -rf -- "$rs_attempt";;
        esac
    fi
    rm -rf -- "$1"
}

# backup_apply STATE ACTION PATH...: run ACTION, which writes PATHs. A failed
# ACTION restores the previous installation; success records fingerprints.
backup_apply() {
    ba_state=$1
    ba_action=$2
    shift 2
    backup_check "$ba_state"
    mkdir -p -- "$(dirname -- "$ba_state")"
    ba_attempt=$(mktemp -d "$(dirname -- "$ba_state")/.syauth-attempt-XXXXXXXX")
    for ba_path in "$@"; do
        backup_remember "$ba_attempt/backup" "$ba_path"
        backup_remember "$ba_state" "$ba_path"
    done
    printf '%s\n' "$ba_attempt" > "$ba_state/pending"
    set +e
    ( set -e; "$ba_action" )
    ba_status=$?
    set -e
    if [ "$ba_status" -ne 0 ]; then
        backup_restore "$ba_attempt/backup" nocheck
        rm -f -- "$ba_state/pending"
        rm -rf -- "$ba_attempt"
        exit "$ba_status"
    fi
    : > "$ba_state/installed.new"
    if [ -f "$ba_state/installed" ]; then
        while IFS=$tab read -r ba_hash ba_known; do
            ba_keep=true
            for ba_path in "$@"; do
                if [ "$ba_path" = "$ba_known" ]; then ba_keep=false; fi
            done
            if [ "$ba_keep" = true ]; then printf '%s\t%s\n' "$ba_hash" "$ba_known" >> "$ba_state/installed.new"; fi
        done < "$ba_state/installed"
    fi
    for ba_path in "$@"; do
        printf '%s\t%s\n' "$(fingerprint "$ba_path")" "$ba_path" >> "$ba_state/installed.new"
    done
    mv -f -- "$ba_state/installed.new" "$ba_state/installed"
    rm -f -- "$ba_state/pending"
    rm -rf -- "$ba_attempt"
}

# ------------------------------------------------------------------ PAM ----

pam_source() {
    for ps_directory in etc/pam.d usr/lib/pam.d; do
        no_symlinks "$ROOT/$ps_directory/$1"
        if [ -f "$ROOT/$ps_directory/$1" ]; then
            printf '%s\n' "$ROOT/$ps_directory/$1"
            return 0
        fi
    done
    fail "Missing PAM service: $1"
}

# pam_config USER UID SERVICE < STACK: drop a previous syauth block, then
# insert the guarded block before the single system-auth include.
pam_config() {
    awk -v user="$1" -v uid="$2" -v service="$3" '
    function norm(text) { gsub(/[ \t]+/, " ", text); sub(/^ /, "", text); sub(/ $/, "", text); return text }
    BEGIN {
        guard = "auth [success=1 default=ignore] pam_succeed_if.so user != " user " quiet"
        socket = "socket=/run/user/" uid "/syauth/auth.sock"
        allowed["terminal_prompt"]; allowed["pwfeedback"]; allowed["on_empty_password"]; allowed[socket]
    }
    $0 ~ /pam_syauth\.so/ && $0 !~ /^[ \t]*#/ {
        custom = $1 != "auth" || $2 != "sufficient" || $3 != "pam_syauth.so"
        for (i = 4; i <= NF; i++) if (!($i in allowed)) custom = 1
        if (custom) { error = "Review the existing custom syauth configuration in " service; exit 1 }
        if (count == 0 || norm(kept[count]) != guard) { error = "Missing matching user guard in " service "; review the existing setup"; exit 1 }
        count--
        next
    }
    { kept[++count] = $0 }
    END {
        if (error != "") { print error > "/dev/stderr"; exit 1 }
        for (i = 1; i <= count; i++) if (split(kept[i], f) == 3 && f[1] == "auth" && f[2] == "include" && f[3] == "system-auth") includes++
        if (includes != 1) { print "Expected one \"auth include system-auth\" in " service "; custom stacks need manual review" > "/dev/stderr"; exit 1 }
        options = service == "sudo" ? "terminal_prompt pwfeedback" : "on_empty_password"
        for (i = 1; i <= count; i++) {
            if (split(kept[i], f) == 3 && f[1] == "auth" && f[2] == "include" && f[3] == "system-auth") {
                print guard
                print "auth sufficient pam_syauth.so " options " " socket
            }
            print kept[i]
        }
    }'
}

# kde_stack STACK PASSWORD_STACK: expand the Arch login auth includes locally
# (global services stay untouched), keep the faillock preauth check, and
# require KDE's mandatory checks before system-auth.
kde_stack() {
    for ks_name in system-local-login system-login; do
        for ks_directory in etc/pam.d usr/lib/pam.d; do no_symlinks "$ROOT/$ks_directory/$ks_name"; done
    done
    awk -v root="$ROOT" -v password="$2" '
    function source(name, probe) {
        if ((getline probe < (root "/etc/pam.d/" name)) >= 0) { close(root "/etc/pam.d/" name); return root "/etc/pam.d/" name }
        if ((getline probe < (root "/usr/lib/pam.d/" name)) >= 0) { close(root "/usr/lib/pam.d/" name); return root "/usr/lib/pam.d/" name }
        error = "Missing PAM service: " name
        return ""
    }
    function emit(file, seen, auth_only, line, f, n, kind, path) {
        while (error == "" && (getline line < file) > 0) {
            n = split(line, f)
            kind = f[1]
            sub(/^-/, "", kind)
            if (n == 3 && f[1] == "auth" && f[2] == "include" && (f[3] == "system-local-login" || f[3] == "system-login")) {
                if (index(seen, " " f[3] " ")) { error = "Cyclic KDE PAM includes"; break }
                path = source(f[3])
                if (path != "") emit(path, seen f[3] " ", 1)
                expanded = 1
            } else if (!auth_only || kind == "auth") {
                rows[++count] = line
            }
        }
        close(file)
    }
    function has(row, word, f, n, i) { n = split(row, f); for (i = 1; i <= n; i++) if (f[i] == word) return 1; return 0 }
    function include_row(row, f) { return split(row, f) == 3 && f[1] == "auth" && f[2] == "include" && f[3] == "system-auth" }
    BEGIN {
        emit(ARGV[1], " ", 0)
        if (error == "" && expanded) {
            for (i = 1; i <= count; i++) if (has(rows[i], "pam_faillock.so") && has(rows[i], "preauth")) preauth_present = 1
            if (!preauth_present) {
                while ((getline line < password) > 0) {
                    n = split(line, f)
                    if (preauth == "" && n >= 4 && f[1] == "auth" && (f[2] == "required" || f[2] == "requisite") && f[3] == "pam_faillock.so" && has(line, "preauth")) {
                        preauth = "auth requisite"
                        for (j = 3; j <= n; j++) preauth = preauth " " f[j]
                    }
                }
                if (preauth == "") error = "Cannot preserve KDE'"'"'s mandatory faillock preauth check"
                for (i = 1; i <= count && !at; i++) if (include_row(rows[i])) at = i
                if (error == "" && !at) error = "Unsupported KDE auth include chain"
                if (error == "") { for (i = count; i >= at; i--) rows[i + 1] = rows[i]; rows[at] = preauth; count++ }
            }
        }
        if (error == "") {
            limit = 0
            for (i = 1; i <= count && !limit; i++) if (include_row(rows[i])) limit = i
            for (i = 1; i < limit; i++) {
                split(rows[i], f)
                if (f[1] == "auth" && f[2] == "required" && f[3] == "pam_shells.so") shells = 1
                if (f[1] == "auth" && f[2] == "requisite" && f[3] == "pam_nologin.so") nologin = 1
                if (f[1] == "auth" && f[2] == "requisite" && f[3] == "pam_faillock.so" && has(rows[i], "preauth")) faillock = 1
            }
            if (!(shells && nologin && faillock)) error = "KDE'"'"'s mandatory shell, nologin, and faillock checks must precede system-auth; review this custom stack"
        }
        if (error != "") { print error > "/dev/stderr"; exit 1 }
        for (i = 1; i <= count; i++) print rows[i]
    }' "$1"
}

# pam_plan USER UID DIRECTORY: write the generated sudo and kde stacks.
pam_plan() {
    pp_password=$(pam_source system-auth)
    awk '$1 == "auth" { pam = 0; reuse = 0; for (i = 1; i <= NF; i++) { if ($i == "pam_unix.so") pam = 1; if ($i == "try_first_pass" || $i == "use_first_pass") reuse = 1 } if (pam && reuse) ok = 1 }
         END { exit !ok }' "$pp_password" ||
        fail 'The password stack must reuse PAM_AUTHTOK with pam_unix.so try_first_pass or use_first_pass'
    for pp_directory in etc/pam.d usr/lib/pam.d; do
        if [ -f "$ROOT/$pp_directory/kde-fingerprint" ] && grep -Eq '^[[:space:]]*auth[[:space:]].*pam_syauth\.so' "$ROOT/$pp_directory/kde-fingerprint"; then
            fail 'Remove the old automatic phone block from kde-fingerprint using docs/pam.md first'
        fi
    done
    pp_sudo=$(pam_source sudo)
    pp_kde=$(pam_source kde)
    pam_config "$1" "$2" sudo < "$pp_sudo" > "$3/sudo" || exit 1
    kde_stack "$pp_kde" "$pp_password" > "$3/kde.expanded" || exit 1
    pam_config "$1" "$2" kde < "$3/kde.expanded" > "$3/kde" || exit 1
    rm -f -- "$3/kde.expanded"
}

# --------------------------------------------------------- system phase ----
# Runs through sudo as the owner of /etc/pam.d.

system_install_files() {
    for si_service in sudo kde; do atomic_install "$si_plan/$si_service" "$ROOT/etc/pam.d/$si_service" 644; done
}

system_phase() {
    sp_action=$1
    sp_user=${2:-}
    [ "$(id -u)" = "$(stat -c %u -- "$ROOT/etc/pam.d")" ] || fail 'The system phase must run as root'
    with_lock "$SYSTEM_STATE.lock"
    if [ "$sp_action" = update-check ]; then
        system_update_check
        return
    fi
    sp_entry=$(getent passwd "$sp_user") || fail "Unknown user: $sp_user"
    sp_uid=$(printf '%s\n' "$sp_entry" | cut -d: -f3)
    sp_gid=$(printf '%s\n' "$sp_entry" | cut -d: -f4)
    printf '%s\n' "$sp_user" | grep -Eq '^[a-z_][a-z0-9_-]*\$?$' && [ "$sp_uid" != 0 ] ||
        fail 'Select an ordinary local user with a PAM-compatible login name'
    no_symlinks "$SYSTEM_STATE"
    if [ -e "$SYSTEM_STATE" ]; then
        [ "$(stat -c %u -- "$SYSTEM_STATE")" = "$(id -u)" ] && [ $(( 0$(stat -c %a -- "$SYSTEM_STATE") & 077 )) -eq 0 ] ||
            fail "Backup directory must be root-owned and private: $SYSTEM_STATE"
        if [ -f "$SYSTEM_STATE/user" ] && [ "$(cat -- "$SYSTEM_STATE/user")" != "$sp_uid" ]; then
            fail 'This installer manages one desktop user; restore the previous setup first'
        fi
    fi
    if [ "$sp_action" = rollback ]; then
        if [ -f "$SYSTEM_STATE/originals" ]; then
            cut -f6- -- "$SYSTEM_STATE/originals" | while IFS= read -r sp_path; do
                case "$sp_path" in
                    "$ROOT/etc/pam.d/sudo"|"$ROOT/etc/pam.d/kde") ;;
                    *) fail 'Unexpected paths in system backup';;
                esac
            done
            backup_restore "$SYSTEM_STATE"
        fi
        return
    fi
    si_plan=$(mktemp -d "${TMPDIR:-/tmp}/syauth-pam.XXXXXXXX")
    trap 'rm -rf -- "$si_plan"' EXIT
    pam_plan "$sp_user" "$sp_uid" "$si_plan"
    for sp_directory in var/lib/syauth var/lib/syauth/keys var/log/syauth; do
        no_symlinks "$ROOT/$sp_directory"
        if [ -e "$ROOT/$sp_directory" ]; then
            [ "$(stat -c %u -- "$ROOT/$sp_directory")" = "$sp_uid" ] && [ $(( 0$(stat -c %a -- "$ROOT/$sp_directory") & 077 )) -eq 0 ] ||
                fail "Expected a private directory owned by $sp_user: $ROOT/$sp_directory"
        else
            mkdir -p -- "$ROOT/$sp_directory"
            chmod 700 -- "$ROOT/$sp_directory"
            chown "$sp_uid:$sp_gid" -- "$ROOT/$sp_directory"
        fi
    done
    backup_apply "$SYSTEM_STATE" system_install_files "$ROOT/etc/pam.d/sudo" "$ROOT/etc/pam.d/kde"
    printf '%s\n' "$sp_uid" > "$SYSTEM_STATE/user"
}

# Enable the pacman hook only after the initial baseline passes its checks.
system_update_check() {
    uc_checker=$LIBDIR/check-pam-update
    uc_hook=$ROOT/etc/pacman.d/hooks/95-syauth-check.hook
    uc_state=$ROOT/var/lib/syauth-update-check
    [ -x "$uc_checker" ] || fail "Missing $uc_checker; install the syauth package first"
    for uc_path in "$uc_hook" "$uc_state"; do
        if [ -e "$uc_path" ] || [ -L "$uc_path" ]; then
            fail "Already exists: $uc_path. Review the existing installation before replacing it."
        fi
    done
    trap 'rm -f -- "$uc_hook"; rm -rf -- "$uc_state"' EXIT
    "$uc_checker" --record-baseline
    "$uc_checker"
    atomic_install "$SHAREDIR/pacman/95-syauth-check.hook" "$uc_hook" 644
    trap - EXIT
    echo 'Installed the syauth update checker and pacman hook. PAM configuration was preserved.'
}

# ---------------------------------------------------------- desktop user ----

user_paths() {
    [ "$(id -u)" != 0 ] || fail 'Run as your desktop user; the installer uses sudo only for system files'
    user=$(id -un)
    uid=$(id -u)
    config=${XDG_CONFIG_HOME:-$HOME/.config}
    data=${XDG_DATA_HOME:-$HOME/.local/share}
    state=${XDG_STATE_HOME:-$HOME/.local/state}/syauth
    for up_path in "$HOME" "$config" "$data" "$state"; do
        case "$up_path" in /*) ;; *) fail 'HOME and the XDG configuration, data, and state paths must be absolute';; esac
    done
    dropins=$config/systemd/user/syauth-presenced.service.d
    cli=$ROOT/usr/bin/syauth
}

# Locate this installer for the root phase: the running file, or the copy the
# package ships when the installer was piped into sh.
installer_path() {
    if [ -f "$0" ] && grep -q 'syauth installer' "$0" 2>/dev/null; then
        printf '%s/%s\n' "$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)" "$(basename -- "$0")"
    elif [ -f "$LIBDIR/install.sh" ]; then
        printf '%s\n' "$LIBDIR/install.sh"
    else
        fail 'Cannot locate install.sh for the system phase; install the syauth package first'
    fi
}

elevate() {
    el_self=$(installer_path)
    if [ -n "$ROOT" ]; then
        run sudo env "SYAUTH_ROOT=$ROOT" sh "$el_self" __system "$@"
    else
        run sudo sh "$el_self" __system "$@"
    fi
}

plasma_shell() {
    ps_name=$(kreadconfig6 --file "$config/plasmashellrc" --group Shell --key ShellPackage)
    ps_name=${ps_name:-org.kde.plasma.desktop}
    [ "$(basename -- "$ps_name")" = "$ps_name" ] || fail 'The active Plasma shell must be a package name'
    shell=$data/plasma/shells/$ps_name
    shell_source=$ROOT/usr/share/plasma/shells/$ps_name/contents/lockscreen
}

desktop_preflight() {
    grep -Eq '^ID="?arch"?$' "$os_release" || fail 'Desktop setup supports Arch Linux with KDE Plasma; other systems need the manual guide'
    need sudo systemctl kreadconfig6 kwriteconfig6 bluetoothctl pacman python3 diff flock getent
    user_paths
    pacman -Q plasma-desktop kscreenlocker | awk '{ n = split($2, v, ":"); split(v[n], p, "."); if (p[1] < 6 || (p[1] == 6 && p[2] < 8)) old = 1 } END { exit old }' ||
        fail 'Live lockscreen status requires Plasma and kscreenlocker 6.8 or newer'
    bluetoothctl show | grep -q 'Powered: yes' || fail 'Enable a Bluetooth adapter in KDE before installing'
    systemctl --user show --property=Version --value >/dev/null || fail 'The systemd user manager is not available'
    if [ -e "$config/systemd/user/syauth-presenced.service" ] || [ -e "$dropins/binary.conf" ]; then
        fail "A user unit or binary.conf in $config/systemd/user overrides the packaged service; move it away first"
    fi
    dp_plan=$work/plan
    mkdir -p -- "$dp_plan"
    pam_plan "$user" "$uid" "$dp_plan"
    plasma_shell
    if [ -f "$state/kde-status/install.json" ]; then
        dp_target=$(sed -n 's/.*"target": *"\([^"]*\)".*/\1/p' "$state/kde-status/install.json")
        [ "$dp_target" = "$shell" ] || fail 'The existing live-status installation uses another shell; restore it first'
        if grep -q '"had_original": *true' "$state/kde-status/install.json"; then
            dp_package=$state/kde-status/package
        else
            dp_package=$(sed -n 's/.*"source": *"\([^"]*\)".*/\1/p' "$state/kde-status/install.json")
        fi
    elif [ -d "$shell" ]; then
        dp_package=$shell
    else
        dp_package=$(dirname -- "$(dirname -- "$shell_source")")
    fi
    [ "$(grep -c '^    component FailableLabel' "$dp_package/contents/lockscreen/MainBlock.qml" 2>/dev/null)" = 1 ] &&
        [ "$(grep -cF 'if (lockScreenUi.showPrompt) {' "$dp_package/contents/lockscreen/LockScreenUi.qml" 2>/dev/null)" = 1 ] ||
        fail 'Live status requires the supported Plasma 6.8 shell layout'
    printf 'Desktop user: %s (UID %s)\nPlasma override: %s\n' "$user" "$uid" "$shell"
}

desktop_dry_run() {
    for dd_service in sudo kde; do
        diff -u --label "/etc/pam.d/$dd_service" --label "/etc/pam.d/$dd_service" "$(pam_source "$dd_service")" "$dp_plan/$dd_service" || true
    done
    echo 'Dry run: back up existing files, configure sudo/KDE PAM and live Plasma status via sudo, enable the user daemon.'
}

desktop_configure() {
    run "$LIBDIR/install-kde-status" --shell-dir "$shell" --source "$shell_source" \
        --state-dir "$state/kde-status" --cli "$cli" --component "$SHAREDIR/kde/PhoneStatus.qml"
    run kwriteconfig6 --file "$config/kscreenlockerrc" --group UI \
        --key ShowPromptInRegularAuthenticator --type bool true
    dc_file=$(mktemp "${TMPDIR:-/tmp}/syauth-unit.XXXXXXXX")
    printf '[Service]\nRuntimeDirectory=syauth\nRuntimeDirectoryMode=0700\nReadWritePaths=%%t/syauth\n' > "$dc_file"
    atomic_install "$dc_file" "$dropins/runtime.conf" 644
    if [ -n "$phone_address" ]; then
        printf '[Service]\nEnvironment=SYAUTH_RECONNECT_DEVICE=%s\n' "$phone_address" > "$dc_file"
        atomic_install "$dc_file" "$dropins/phone.conf" 644
    fi
    rm -f -- "$dc_file"
    elevate install "$user"
}

desktop_install() {
    [ -x "$cli" ] || fail "Missing $cli; the syauth package is not installed"
    [ -x "$LIBDIR/install-kde-status" ] || fail "Missing $LIBDIR/install-kde-status; reinstall the syauth package"
    with_lock "$state/.installer.lock"
    if [ ! -f "$state/installer/service" ]; then
        di_active=false
        di_enabled=false
        if systemctl --user is-active --quiet syauth-presenced; then di_active=true; fi
        if systemctl --user is-enabled --quiet syauth-presenced; then di_enabled=true; fi
    fi
    set -- "$dropins/runtime.conf" "$shell" "$state/kde-status" "$config/kscreenlockerrc"
    if [ -n "$phone_address" ]; then set -- "$@" "$dropins/phone.conf"; fi
    backup_apply "$state/installer" desktop_configure "$@"
    if [ ! -f "$state/installer/service" ]; then
        printf 'active=%s\nenabled=%s\n' "$di_active" "$di_enabled" > "$state/installer/service"
    fi
    run systemctl --user daemon-reload
    run systemctl --user enable --now syauth-presenced
    run systemctl --user restart syauth-presenced
    echo "Installed. Open a new lockscreen to see live phone status. Test sudo with 'sudo -k' followed by 'sudo -i'."
    echo 'Pair a new phone with: install.sh pair'
    echo 'After testing phone and password authentication, enable the pacman checker with: install.sh update-check'
}

rollback() {
    user_paths
    need sudo systemctl flock
    with_lock "$state/.installer.lock"
    backup_check "$state/installer" rollback
    elevate rollback "$user"
    if [ ! -f "$state/installer/originals" ]; then
        echo 'No desktop-user backup to restore.'
        return
    fi
    rb_active=false
    rb_enabled=false
    if [ -f "$state/installer/service" ]; then
        rb_active=$(sed -n 's/^active=//p' "$state/installer/service")
        rb_enabled=$(sed -n 's/^enabled=//p' "$state/installer/service")
    fi
    run systemctl --user stop syauth-presenced
    if [ "$rb_enabled" != true ]; then run systemctl --user disable syauth-presenced; fi
    backup_restore "$state/installer"
    run systemctl --user daemon-reload
    if [ "$rb_enabled" = true ]; then run systemctl --user enable syauth-presenced; fi
    if [ "$rb_active" = true ]; then run systemctl --user start syauth-presenced; fi
    echo 'Restored the pre-installer setup. Pairing data and the Android app were preserved.'
}

pair() {
    user_paths
    [ -x "$cli" ] || fail 'Install syauth before pairing'
    pa_active=false
    if systemctl --user is-active --quiet syauth-presenced; then pa_active=true; fi
    run systemctl --user stop syauth-presenced
    echo 'Open Pair with computer on your phone. Compare and confirm both Bluetooth and app codes on both devices.'
    set +e
    run "$cli" pair --timeout-secs 300
    pa_status=$?
    set -e
    if [ "$pa_active" = true ]; then run systemctl --user start syauth-presenced; fi
    return "$pa_status"
}

update_check() {
    grep -Eq '^ID="?arch"?$' "$os_release" || fail 'The update checker supports Arch Linux pacman hooks'
    need sudo
    elevate update-check
}

# -------------------------------------------------------------- android ----

adb_value() { adb -s "$android" shell "$@" | tr -d '\r'; }

android_preflight() {
    need adb
    [ "$(adb_value am get-current-user)" = 0 ] || fail "Android installation requires the selected device's current user to be 0"
    [ "$(adb_value getprop ro.build.version.sdk)" -ge 33 ] 2>/dev/null ||
        fail 'Production pairing requires Android 13/API 33 or newer with Keystore Ed25519 support'
}

android_build() {
    need cargo cargo-ndk rustup java make
    ab_sdk=${ANDROID_HOME:-$HOME/Android/Sdk}
    [ -d "$ab_sdk" ] || fail 'Set ANDROID_HOME to an installed Android SDK, including platform 34'
    ab_ndk=${NDK_HOME:-$(find "$ab_sdk/ndk" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort -V | tail -n 1)}
    [ -n "$ab_ndk" ] && [ -d "$ab_ndk" ] || fail 'Install an Android NDK and set NDK_HOME'
    run rustup target add aarch64-linux-android armv7-linux-androideabi x86_64-linux-android i686-linux-android
    (cd "$checkout" && run env "ANDROID_HOME=$ab_sdk" "NDK_HOME=$ab_ndk" scripts/build_aar.sh)
    (cd "$checkout/syauth-android" && run env "ANDROID_HOME=$ab_sdk" ./gradlew --no-parallel \
        -Pkotlin.compiler.execution.strategy=in-process :app:assembleDebug :app:testDebugUnitTest)
    apk=$checkout/syauth-android/app/build/outputs/apk/debug/app-debug.apk
}

android_install() {
    [ "$(adb_value am get-current-user)" = 0 ] || fail 'Android user changed during the build; switch back to user 0 before installing'
    printf '+ adb -s %s install --user 0 -r %s\n' "$android" "$apk"
    ai_output=$(adb -s "$android" install --user 0 -r "$apk" 2>&1) || true
    printf '%s\n' "$ai_output"
    if ! printf '%s\n' "$ai_output" | tr -d '\r' | grep -qx Success; then
        case "$ai_output" in
            *INSTALL_FAILED_UPDATE_INCOMPATIBLE*) fail 'The installed app has a different signing key. Uninstall it first; this removes its pairing.';;
        esac
        fail 'Android did not confirm installation'
    fi
    run adb -s "$android" shell am start --user 0 -n "$APP/.MainActivity"
}

# -------------------------------------------------------------- release ----

fetch() { curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --connect-timeout 15 --max-time 180 --retry 3 --output "$2" "$1"; }

resolve_release() {
    api=https://api.github.com/repos/$REPO_SLUG/releases
    if [ -n "$version" ]; then endpoint=$api/tags/v$version; else endpoint=$api/latest; fi
    fetch "$endpoint" "$work/release.json"
    tag=$(sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\(v[0-9][0-9.]*\)".*/\1/p' "$work/release.json")
    printf '%s\n' "$tag" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$' || fail 'Release API returned an invalid or missing tag'
    [ -z "$version" ] || [ "$tag" = "v$version" ] || fail 'Release tag does not match requested version'
    version=${tag#v}
}

# Download one release asset and check it against the SHA-256 digest that
# GitHub's release API reports for exactly that asset name.
download_verified() {
    fetch "https://github.com/$REPO_SLUG/releases/download/$tag/$1" "$work/$1"
    # shellcheck disable=SC2020 # each JSON delimiter becomes a line break
    tr -d '\r\n' < "$work/release.json" | tr ',{}[]' '\n\n\n\n\n' | awk -v name="$1" '
        $0 ~ /^[[:space:]]*"name"[[:space:]]*:/ { value = $0; sub(/^[^:]*:[[:space:]]*"/, "", value); sub(/"[[:space:]]*$/, "", value); if (value == name) current = 1 }
        current && $0 ~ /^[[:space:]]*"digest"[[:space:]]*:/ { value = $0; sub(/^[^:]*:[[:space:]]*"sha256:/, "", value); sub(/"[[:space:]]*$/, "", value); if (length(value) != 64 || value ~ /[^0-9a-f]/) exit 1; print value "  " name; count++; current = 0 }
        $0 ~ /^[[:space:]]*"browser_download_url"[[:space:]]*:/ { current = 0 }
        END { if (count != 1) exit 1 }' > "$work/selected.sha256" || fail 'Missing, duplicated, or malformed package checksum'
    (cd "$work" && sha256sum --check selected.sha256) || fail 'Checksum verification failed; refusing installation'
}

asset_name() {
    case "$format" in
        deb) printf 'syauth_%s_%s.deb\n' "$1" "$deb_arch";;
        rpm) printf 'syauth-%s-4.%s.rpm\n' "$1" "$arch";;
        arch) printf 'syauth-%s-1-%s.pkg.tar.zst\n' "$1" "$arch";;
    esac
}

source_checkout() {
    if [ -z "$checkout" ]; then
        if [ -f "$0" ] && [ -f "$(dirname -- "$0")/../Cargo.toml" ]; then
            checkout=$(dirname -- "$0")/..
        else
            fail '--source needs a syauth checkout: --source DIR'
        fi
    fi
    checkout=$(CDPATH='' cd -- "$checkout" && pwd)
    [ -f "$checkout/Cargo.toml" ] && [ -x "$checkout/scripts/build-linux-packages.sh" ] || fail "Not a syauth checkout: $checkout"
    version=$(awk '/^\[workspace\.package\]/ { inside = 1; next } /^\[/ { inside = 0 } inside && $1 == "version" { gsub(/"/, "", $3); print $3; exit }' "$checkout/Cargo.toml")
    printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || fail 'Cannot read the workspace version'
}

build_package() {
    need cargo cc pkg-config python3
    (cd "$checkout" && run cargo build --locked --release -p syauth-cli -p syauth-pam -p syauth-presenced)
    (cd "$checkout" && run scripts/build-linux-packages.sh --version "$version" --arch "$arch" \
        --binaries target/release --output "$work/packages")
    package=$work/packages/$(asset_name "$version")
    [ -f "$package" ] || fail "The package build did not produce $package"
}

# Package installation may elevate; network downloads and builds never do.
run_root() {
    if [ "$(id -u)" = 0 ]; then "$@"; else
        command -v sudo >/dev/null 2>&1 || fail 'sudo is required; alternatively run the downloaded script as root'
        sudo "$@"
    fi
}

install_package() {
    case "$manager" in
        apt-get) run_root apt-get update -q; run_root apt-get install -y ${reinstall:+--reinstall} "$1";;
        dnf) if [ -n "$reinstall" ] && rpm -q syauth >/dev/null 2>&1; then run_root dnf reinstall -y "$1"; else run_root dnf install -y "$1"; fi;;
        zypper) run_root zypper --non-interactive install --allow-unsigned-rpm ${reinstall:+--force} "$1";;
        pacman) run_root pacman -U --noconfirm "$1";;
    esac
}

platform() {
    need curl sha256sum mktemp uname getconf awk sed grep
    arch=$(uname -m)
    case "$arch" in
        x86_64) deb_arch=amd64;;
        aarch64|arm64) arch=aarch64; deb_arch=arm64;;
        *) fail "Unsupported architecture: $arch";;
    esac
    libc=$(getconf GNU_LIBC_VERSION 2>/dev/null) || fail 'A glibc-based Linux distribution is required'
    printf '%s\n' "$libc" | awk '$1 == "glibc" {split($2,v,"."); if(v[1]>2 || (v[1]==2 && v[2]>=36)) ok=1} END {exit !ok}' || fail 'glibc 2.36 or newer is required'
    distro=$(sed -n 's/^ID=//p' "$os_release" | tr -d '"' | tr -d "'")
    case "$distro" in
        debian|ubuntu|linuxmint|pop|elementary|zorin) manager=apt-get; format=deb;;
        fedora) manager=dnf; format=rpm;;
        opensuse-tumbleweed|opensuse-leap|opensuse) manager=zypper; format=rpm;;
        arch|endeavouros|manjaro) manager=pacman; format=arch;;
        *) fail "Unsupported distribution: $distro. See $DOCS/how-to/install/";;
    esac
    command -v "$manager" >/dev/null 2>&1 || fail "Native package manager missing: $manager"
}

install_main() {
    platform
    if [ "$from_source" = true ]; then source_checkout; fi
    work=$(mktemp -d "${TMPDIR:-/tmp}/syauth-install.XXXXXXXX")
    trap 'rm -rf -- "$work"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    if [ "$desktop" = true ]; then desktop_preflight; fi
    if [ -n "$android" ]; then android_preflight; fi
    if [ "$from_source" = true ]; then
        if [ "$dry_run" = true ]; then
            printf 'Dry run: build syauth %s from %s into a %s package and install it with %s.\n' "$version" "$checkout" "$format" "$manager"
        else
            build_package
            # A local build may repeat the installed version; replace it anyway.
            reinstall=--reinstall
            install_package "$package"
        fi
    else
        resolve_release
        asset=$(asset_name "$version")
        printf 'Downloading syauth %s for %s/%s\n' "$version" "$distro" "$arch"
        download_verified "$asset"
        if [ "$dry_run" = true ]; then
            printf 'Verified %s; would install with %s. No changes made.\n' "$asset" "$manager"
        else
            install_package "$work/$asset"
        fi
    fi
    if [ -n "$android" ]; then
        if [ "$dry_run" = true ]; then
            printf 'Dry run: install the %s Android app on %s for user 0.\n' "$([ "$from_source" = true ] && echo debug || echo signed release)" "$android"
        else
            if [ "$from_source" = true ]; then
                android_build
            else
                apk_name=syauth-$version-android.apk
                download_verified "$apk_name"
                apk=$work/$apk_name
            fi
            android_install
        fi
    fi
    if [ "$desktop" = true ]; then
        if [ "$dry_run" = true ]; then desktop_dry_run; else desktop_install; fi
    elif [ "$dry_run" = false ]; then
        echo "Installed. PAM configuration is unchanged. Follow $DOCS/tutorials/first-unlock/ to pair your phone and enable the user service, or rerun with --desktop on Arch Linux with KDE Plasma."
    fi
}

# ------------------------------------------------------------------ main ----

os_release=${SYAUTH_OS_RELEASE:-$ROOT/etc/os-release}
command=install
case "${1:-}" in
    install|rollback|pair|update-check) command=$1; shift;;
    __system) shift; system_phase "$@"; exit 0;;
esac
version=
version_supplied=false
dry_run=false
from_source=false
checkout=
desktop=false
phone_address=
android=
reinstall=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --version) [ "$#" -ge 2 ] || fail '--version needs X.Y.Z'; version=${2#v}; version_supplied=true; shift 2;;
        --source)
            from_source=true
            if [ "$#" -ge 2 ] && [ "${2#-}" = "$2" ]; then checkout=$2; shift; fi
            shift;;
        --desktop) desktop=true; shift;;
        --phone-address) [ "$#" -ge 2 ] || fail '--phone-address needs a MAC address'; phone_address=$2; shift 2;;
        --android) [ "$#" -ge 2 ] || fail '--android needs an ADB serial'; android=$2; shift 2;;
        --dry-run) dry_run=true; shift;;
        --help|-h) usage; exit 0;;
        *) fail "Unknown argument: $1";;
    esac
done
if [ "$command" != install ] && { [ "$version_supplied" = true ] || [ "$from_source" = true ] || [ "$desktop" = true ] || [ -n "$phone_address$android" ] || [ "$dry_run" = true ]; }; then
    fail "Options apply only to install"
fi
if [ "$version_supplied" = true ]; then
    printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || fail 'Version must be X.Y.Z'
    [ "$from_source" = false ] || fail '--version selects a release; --source builds the checkout version'
fi
if [ -n "$phone_address" ]; then
    printf '%s\n' "$phone_address" | grep -Eq '^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$' || fail "--phone-address must be the phone's bonded Bluetooth MAC address"
    [ "$desktop" = true ] || fail '--phone-address configures the --desktop daemon'
    phone_address=$(printf '%s\n' "$phone_address" | tr 'a-f' 'A-F')
fi
if [ -n "$android" ]; then
    printf '%s\n' "$android" | grep -Eq '^[A-Za-z0-9._:-]+$' || fail '--android needs an ADB serial'
fi
[ -r "$os_release" ] || fail 'Cannot read /etc/os-release'
case "$command" in
    install) install_main;;
    rollback) rollback;;
    pair) pair;;
    update-check) update_check;;
esac
