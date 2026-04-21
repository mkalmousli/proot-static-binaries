# proot-static-binaries

Builds static `proot` binaries for multiple Linux architectures and publishes them as GitHub release assets.

## How it works

The build pipeline is Python-driven and runs on standard GitHub Ubuntu runners (no Docker job containers).

For each target architecture, the builder:

- Clones `proot` source and builds host `proot` locally
- Clones `qemu` source and builds `qemu-user` emulators locally
- Downloads architecture-specific Alpine minirootfs
- Boots target Alpine under the source-built host `proot` (with source-built `qemu-*` for foreign arch)
- Installs build dependencies via `apk`
- Builds `proot` statically in that environment
- Publishes `dist/proot-<arch>` as release artifacts

## Smart/resumable cache layout

Everything is stored under `.Cache/`:

- `.Cache/Downloads/Part` - resumable partial downloads
- `.Cache/Downloads/Full` - completed downloads
- `.Cache/Temps` - temporary working directories
- `.Cache/Sources` - cached source trees
- `.Cache/Tooling` - cached source-built runtime tools (`proot`, `qemu-*`)
- `.Cache/Rootfs` - extracted Alpine rootfs per architecture
- `.Cache/State` - future metadata/state files

The script reuses existing artifacts automatically and skips work when outputs already exist.

## Build locally

Single arch:

```bash
python3 scripts/build_static.py --arch x86_64
```

All arches:

```bash
python3 scripts/build_static.py --all
```

Force refresh:

```bash
python3 scripts/build_static.py --all --force
```

## Release usage

Push a tag like:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Release assets are named:

- `proot-x86_64`
- `proot-aarch64`
- `proot-armv7`
