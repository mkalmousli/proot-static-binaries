# proot-static-binaries

Builds static `proot` binaries for multiple Linux architectures and publishes them as GitHub release assets.

## What this repo does

- Builds `proot` from upstream source (`proot-me/proot`)
- Produces statically linked binaries for:
  - `x86_64`
  - `aarch64`
  - `armv7`
- Uploads build outputs as workflow artifacts
- Publishes binaries to GitHub Releases when a tag is pushed

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

## Local build

The repo is designed for CI builds in containers. Local manual build is possible with:

```bash
scripts/build-static.sh x86_64
```
