#!/bin/sh
set -eu
# Preserve existing state, ownership, permissions, and PAM configuration.
if [ ! -e /var/lib/syauth ]; then
    install -d -m 0700 /var/lib/syauth
fi
# Enablement and a user-manager reload are explicit per-user setup steps.
