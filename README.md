# proot-static-binaries

Build static `proot` binaries for `x86_64`, `aarch64`, and `armv7`.

## Build

Run one target:

```bash
python3 build.py --arch x86_64
```

Run all targets:

```bash
python3 build.py --all
```

The script uses the host CPU count automatically for build jobs and runs all requested targets concurrently by default. It resolves upstream `HEAD` to explicit commit archives instead of downloading branch names, and you can override that with `PROOT_COMMIT` or `QEMU_COMMIT`. It is Ubuntu-aware and installs missing host dependencies automatically.

## Cache layout

- `.Cache/Downloads/Part` - resumable partial downloads
- `.Cache/Downloads/Full` - completed downloads
- `.Cache/Temps` - temporary work dirs
- `.Cache/Sources` - source trees
- `.Cache/Tooling` - built host tooling (`proot`, `qemu-*`)
- `.Cache/Rootfs` - extracted Alpine rootfs per target arch

## Release

Push a tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Release assets:

- `proot-x86_64`
- `proot-aarch64`
- `proot-armv7`
