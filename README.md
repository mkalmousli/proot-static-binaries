# proot-static-binaries

Build static `proot` binaries for `x86_64`, `aarch64`, and `armv7`.

## What It Does

- `build.py` builds static `proot` binaries for the supported architectures and libc variants.
- `build_site.py` reads GitHub Releases and generates the static site in `.site-build/`.
- `.github/workflows/release.yml` publishes new release assets and `info.json`.
- `.github/workflows/site.yml` rebuilds the site after a release is published, or when run manually.

## How To Run

Run one target:

```bash
python3 build.py --arch x86_64
```

Run all targets:

```bash
python3 build.py --all
```

The script uses the host CPU count automatically for build jobs and runs all requested targets concurrently by default. It now builds from `proot` release tags, and you can override that with `PROOT_TAG` or `QEMU_COMMIT`. It is Ubuntu-aware and installs missing host dependencies automatically.

Build the site locally:

```bash
python3 build_site.py
```

That reads the GitHub Releases for this repository and writes a single-page site to `.site-build/` with the latest summary and the full version list.

## Cache layout

- `.Cache/Downloads/Part` - resumable partial downloads
- `.Cache/Downloads/Full` - completed downloads
- `.Cache/Temps` - temporary work dirs
- `.Cache/Sources` - source trees
- `.Cache/Tooling` - built host tooling (`proot`, `qemu-*`)
- `.Cache/Rootfs` - extracted Alpine rootfs per target arch

## Release

Push a tag or publish a release:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Release assets:

- `proot-x86_64`
- `proot-aarch64`
- `proot-armv7`

The release workflow also uploads `info.json` with the build metadata and artifact sizes. New `proot` releases are built from the oldest missing upstream tag first, then move forward tag by tag.
