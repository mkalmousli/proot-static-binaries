#!/bin/sh
set -eu

repo="${REPO:-mkalmousli/proot-static-binaries}"
out="${1:-proot}"

arch="$(uname -m)"
case "$arch" in
  x86_64|amd64) arch="x86_64" ;;
  aarch64|arm64) arch="aarch64" ;;
  armv7l|armv7*) arch="armv7" ;;
  *)
    echo "unsupported architecture: $arch" >&2
    exit 1
    ;;
esac

libc="musl"
if command -v ldd >/dev/null 2>&1 && ldd --version 2>&1 | head -n1 | grep -qiE 'glibc|gnu'; then
  libc="gnu"
fi

tag="$(
  curl -fsSL "https://api.github.com/repos/$repo/releases/latest" |
    sed -n 's/.*"tag_name":[[:space:]]*"\([^"]*\)".*/\1/p' |
    head -n1
)"

if [ -z "$tag" ]; then
  echo "unable to resolve latest release tag" >&2
  exit 1
fi

asset="proot-${arch}-${libc}"
url="https://github.com/$repo/releases/download/$tag/$asset"
tmp="${out}.tmp.$$"

trap 'rm -f "$tmp"' INT HUP TERM EXIT

curl -fsSL "$url" -o "$tmp"
chmod 755 "$tmp"
mv "$tmp" "$out"

trap - INT HUP TERM EXIT
echo "installed $out"
