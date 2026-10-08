#!/usr/bin/env bash
set -euo pipefail

if [[ $(id -u) != 0 ]]; then
    echo 'Run this installer with sudo or pkexec.' >&2
    exit 1
fi
repo=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
checker=/usr/local/libexec/syauth-update-check
hook=/etc/pacman.d/hooks/95-syauth-check.hook
baseline=/var/lib/syauth-update-check/baseline.json

for destination in "$checker" "$hook" /var/lib/syauth-update-check; do
    if [[ -e $destination || -L $destination ]]; then
        echo "Already exists: $destination. Review the existing installation before replacing it." >&2
        exit 1
    fi
done

rollback() {
    rm -f -- "$checker" "$hook" "$baseline"
    rmdir -- /var/lib/syauth-update-check 2>/dev/null || true
}
trap rollback EXIT
install -Dm755 "$repo/scripts/check-pam-update.py" "$checker"
"$checker" --record-baseline
"$checker"
# Enable the hook only after the initial baseline passes its checks.
install -Dm644 "$repo/deploy/arch/95-syauth-check.hook" "$hook"
trap - EXIT
echo 'Installed syauth update checker and pacman hook. PAM configuration was preserved.'
