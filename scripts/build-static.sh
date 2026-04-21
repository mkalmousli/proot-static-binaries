#!/usr/bin/env bash
set -euo pipefail

ARCH="${1:-x86_64}"
PROOT_REF="${PROOT_REF:-master}"
WORKDIR="$(pwd)"
OUTDIR="$WORKDIR/dist"
SRCDIR="$WORKDIR/out/proot"

mkdir -p "$OUTDIR" "$WORKDIR/out"
rm -rf "$SRCDIR"

git clone --depth 1 --branch "$PROOT_REF" https://github.com/proot-me/proot.git "$SRCDIR"

case "$ARCH" in
  x86_64)
    export TARGET_TRIPLE="x86_64-linux-musl"
    export CC="x86_64-linux-musl-gcc"
    ;;
  aarch64)
    export TARGET_TRIPLE="aarch64-linux-musl"
    export CC="aarch64-linux-musl-gcc"
    ;;
  armv7)
    export TARGET_TRIPLE="armv7-linux-musleabihf"
    export CC="arm-linux-musleabihf-gcc"
    ;;
  *)
    echo "unsupported arch: $ARCH" >&2
    exit 1
    ;;
esac

cd "$SRCDIR/src"

# Static build. Fallback to regular make if strict static flags fail.
if ! make clean >/dev/null 2>&1; then
  true
fi

if ! make CC="$CC" CFLAGS="-O2 -static" LDFLAGS="-static" proot; then
  make CC="$CC" proot
fi

install -m 0755 proot "$OUTDIR/proot-$ARCH"
file "$OUTDIR/proot-$ARCH" || true
