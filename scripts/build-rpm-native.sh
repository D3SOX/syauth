#!/usr/bin/env bash
# Build the committed desktop release for the installed Fedora version.
set -euo pipefail
if [[ ${1:-} == --help ]]; then
  echo 'Usage: build-rpm-native.sh (builds committed HEAD; optional CARGO_TARGET_DIR cache)'
  exit 0
fi
[[ $# == 0 ]] || { echo 'Unknown argument' >&2; exit 2; }
release_repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
release_version=$(git -C "$release_repo" show HEAD:deploy/version.env | sed -n 's/^PACKAGE_VERSION=//p')
release_fedora=$(rpm -E '%fedora')
[[ $release_fedora =~ ^[0-9]+$ ]] || { echo 'A Fedora host is required' >&2; exit 1; }
release_output=${SYAUTH_RPM_OUTPUT_DIR:-$release_repo/target/rpm/f$release_fedora}
release_work=$(mktemp -d)
trap 'rm -rf -- "$release_work"' EXIT
mkdir -p "$release_work/SOURCES" "$release_work/RPMS" "$release_work/SRPMS" "$release_output"
git -C "$release_repo" archive --format=tar --prefix="syauth-$release_version/" HEAD |
  gzip > "$release_work/SOURCES/syauth-$release_version.tar.gz"
git -C "$release_repo" show HEAD:deploy/fedora/syauth.spec > "$release_work/syauth.spec"
rpmbuild -ba "$release_work/syauth.spec" --define "_topdir $release_work"
find "$release_work/RPMS" "$release_work/SRPMS" -name '*.rpm' -type f -exec cp -t "$release_output" {} +
echo "RPMs written to $release_output"
