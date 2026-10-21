#!/usr/bin/env bash
# Set the package version inside a built .deb, and keep its file name.
#
#   scripts/set-deb-version.sh <file.deb> <debian-version>
#
# Tauri writes the app version into the .deb as it is. For a beta that is
# YYYY.M.N-beta.B, which dpkg sorts AFTER the final YYYY.M.N, so apt would
# treat the stable release as a downgrade. scripts/build-linux-desktop.sh
# calls this with the dpkg form from `scripts/calver.py debian-version`
# (YYYY.M.N~beta.B, which dpkg sorts before YYYY.M.N). The file name keeps
# the public version, because the in-app updater looks for
# Dictate_<version>_amd64.deb.
set -euo pipefail

deb="${1:?usage: set-deb-version.sh <file.deb> <debian-version>}"
version="${2:?usage: set-deb-version.sh <file.deb> <debian-version>}"

if ! [[ "$version" =~ ^[0-9][A-Za-z0-9.+~-]*$ ]]; then
  echo "✗ not a Debian version: $version" >&2
  exit 1
fi
current="$(dpkg-deb --field "$deb" Version)"
if [ "$current" = "$version" ]; then
  echo "▶ $deb already has version $version"
  exit 0
fi

work="$(mktemp -d "$(dirname "$deb")/.deb-version.XXXXXX")"
trap 'rm -rf "$work"' EXIT
dpkg-deb --raw-extract "$deb" "$work/root"
sed -i "s/^Version: .*/Version: ${version}/" "$work/root/DEBIAN/control"
# Tauri's packages are owned by root; keep them so. gzip, as Tauri writes
# them, keeps the repack quick for a package that carries a speech model.
dpkg-deb --root-owner-group -Zgzip --build "$work/root" "$work/out.deb" >/dev/null
mv -f "$work/out.deb" "$deb"
echo "▶ $deb: package version $current -> $(dpkg-deb --field "$deb" Version)"
