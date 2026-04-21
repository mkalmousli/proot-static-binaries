#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ALPINE_VERSION = "3.20.5"
PROOT_REF = os.environ.get("PROOT_REF", "master")


@dataclass(frozen=True)
class Target:
    name: str
    alpine_arch: str
    qemu_name: str


TARGETS = {
    "x86_64": Target("x86_64", "x86_64", "qemu-x86_64-static"),
    "aarch64": Target("aarch64", "aarch64", "qemu-aarch64-static"),
    "armv7": Target("armv7", "armv7", "qemu-arm-static"),
}

PROOT_URLS = {
    "x86_64": "https://github.com/termux/proot-static-build/releases/download/v5.4.0/proot-x86_64",
    "aarch64": "https://github.com/termux/proot-static-build/releases/download/v5.4.0/proot-aarch64",
    "armv7": "https://github.com/termux/proot-static-build/releases/download/v5.4.0/proot-arm",
}

QEMU_URLS = {
    "x86_64": "https://github.com/multiarch/qemu-user-static/releases/download/v7.2.0-1/qemu-x86_64-static",
    "aarch64": "https://github.com/multiarch/qemu-user-static/releases/download/v7.2.0-1/qemu-aarch64-static",
    "armv7": "https://github.com/multiarch/qemu-user-static/releases/download/v7.2.0-1/qemu-arm-static",
}


class CacheLayout:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.download_part = root / "Downloads" / "Part"
        self.download_full = root / "Downloads" / "Full"
        self.temps = root / "Temps"
        self.sources = root / "Sources"
        self.tooling = root / "Tooling"
        self.rootfs = root / "Rootfs"
        self.state = root / "State"

    def ensure(self) -> None:
        for d in [
            self.root,
            self.download_part,
            self.download_full,
            self.temps,
            self.sources,
            self.tooling,
            self.rootfs,
            self.state,
        ]:
            d.mkdir(parents=True, exist_ok=True)


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=True)


def detect_host_arch() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    if machine in ("aarch64", "arm64"):
        return "aarch64"
    if machine.startswith("armv7") or machine.startswith("arm"):
        return "armv7"
    raise RuntimeError(f"Unsupported host architecture: {machine}")


def resumable_download(url: str, full_dir: Path, part_dir: Path, force: bool = False) -> Path:
    key = sha256_of(url)
    meta_path = full_dir / f"{key}.json"

    guessed_name = url.rstrip("/").split("/")[-1] or f"asset-{key[:12]}"
    final_path = full_dir / guessed_name
    part_path = part_dir / f"{guessed_name}.part"

    if final_path.exists() and not force:
        print(f"Using cached download: {final_path}")
        return final_path

    downloaded = part_path.stat().st_size if part_path.exists() else 0
    headers = {}
    if downloaded > 0:
        headers["Range"] = f"bytes={downloaded}-"

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        status = getattr(resp, "status", 200)
        if status == 206:
            mode = "ab"
        elif status == 200:
            mode = "wb"
            downloaded = 0
        else:
            raise RuntimeError(f"Unexpected HTTP status {status} for {url}")

        with open(part_path, mode) as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)

    part_path.replace(final_path)
    meta_path.write_text(json.dumps({"url": url, "file": final_path.name}, indent=2), encoding="utf-8")
    return final_path


def prepare_proot(cache: CacheLayout, force: bool) -> Path:
    host = detect_host_arch()
    url = PROOT_URLS[host]
    proot = resumable_download(url, cache.download_full, cache.download_part, force=force)
    target = cache.tooling / "proot"
    if force or not target.exists():
        shutil.copy2(proot, target)
        target.chmod(0o755)
    return target


def prepare_qemu(cache: CacheLayout, target: Target, force: bool) -> Path:
    url = QEMU_URLS[target.name]
    qemu = resumable_download(url, cache.download_full, cache.download_part, force=force)
    out = cache.tooling / target.qemu_name
    if force or not out.exists():
        shutil.copy2(qemu, out)
        out.chmod(0o755)
    return out


def prepare_source(cache: CacheLayout, force: bool) -> Path:
    src_dir = cache.sources / f"proot-{PROOT_REF}"
    if src_dir.exists() and not force:
        print(f"Using cached source: {src_dir}")
        return src_dir

    archive_url = f"https://github.com/proot-me/proot/archive/refs/heads/{PROOT_REF}.tar.gz"
    archive = resumable_download(archive_url, cache.download_full, cache.download_part, force=force)

    tmp_dir = Path(tempfile.mkdtemp(prefix="src-", dir=cache.temps))
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(tmp_dir)

    extracted = next(tmp_dir.iterdir())
    if src_dir.exists():
        shutil.rmtree(src_dir)
    shutil.move(str(extracted), src_dir)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return src_dir


def prepare_rootfs(cache: CacheLayout, target: Target, force: bool) -> Path:
    rootfs_dir = cache.rootfs / target.name
    marker = rootfs_dir / "etc" / "os-release"
    if marker.exists() and not force:
        print(f"Using cached rootfs: {rootfs_dir}")
        return rootfs_dir

    if rootfs_dir.exists():
        shutil.rmtree(rootfs_dir)
    rootfs_dir.mkdir(parents=True, exist_ok=True)

    url = (
        f"https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/{target.alpine_arch}/"
        f"alpine-minirootfs-{ALPINE_VERSION}-{target.alpine_arch}.tar.gz"
    )
    archive = resumable_download(url, cache.download_full, cache.download_part, force=force)
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(rootfs_dir)
    return rootfs_dir


def proot_base_cmd(proot: Path, rootfs: Path, work: Path, qemu: Path | None) -> list[str]:
    cmd = [
        str(proot),
        "-0",
        "-r",
        str(rootfs),
        "-b",
        "/dev",
        "-b",
        "/proc",
        "-b",
        "/sys",
        "-b",
        "/etc/resolv.conf",
        "-b",
        f"{work}:/work",
        "-w",
        "/work",
    ]
    if qemu is not None:
        cmd += ["-q", str(qemu)]
    return cmd


def run_in_rootfs(proot: Path, rootfs: Path, work: Path, qemu: Path | None, inner: list[str]) -> None:
    run(proot_base_cmd(proot, rootfs, work, qemu) + inner)


def build_target(project_root: Path, cache: CacheLayout, target: Target, force: bool) -> None:
    dist_dir = project_root / "dist"
    dist_dir.mkdir(exist_ok=True)
    output_bin = dist_dir / f"proot-{target.name}"

    if output_bin.exists() and not force:
        print(f"Skipping {target.name}; output already exists: {output_bin}")
        return

    proot_bin = prepare_proot(cache, force=force)
    qemu_bin = None
    if target.name != detect_host_arch():
        qemu_bin = prepare_qemu(cache, target, force=force)

    rootfs = prepare_rootfs(cache, target, force=force)
    source = prepare_source(cache, force=force)

    work_target = cache.temps / f"work-{target.name}"
    if work_target.exists():
        shutil.rmtree(work_target)
    shutil.copytree(source, work_target)

    repos = "https://dl-cdn.alpinelinux.org/alpine/v3.20/main\\nhttps://dl-cdn.alpinelinux.org/alpine/v3.20/community\\n"
    run_in_rootfs(proot_bin, rootfs, work_target, qemu_bin, [
        "sh",
        "-lc",
        f"printf '{repos}' > /etc/apk/repositories",
    ])
    run_in_rootfs(proot_bin, rootfs, work_target, qemu_bin, ["apk", "update"])
    run_in_rootfs(proot_bin, rootfs, work_target, qemu_bin, [
        "apk",
        "add",
        "--no-cache",
        "build-base",
        "linux-headers",
        "make",
        "file",
        "talloc-dev",
    ])

    run_in_rootfs(proot_bin, rootfs, work_target, qemu_bin, [
        "sh",
        "-lc",
        "cd /work/src && make clean >/dev/null 2>&1 || true; make CFLAGS='-O2 -static' LDFLAGS='-static' proot",
    ])

    built = work_target / "src" / "proot"
    if not built.exists():
        raise RuntimeError(f"Build did not produce expected binary for {target.name}: {built}")

    shutil.copy2(built, output_bin)
    output_bin.chmod(0o755)
    print(f"Built: {output_bin}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build static proot binaries with proot+alpine+qemu")
    parser.add_argument("--arch", choices=sorted(TARGETS.keys()), help="single target arch")
    parser.add_argument("--all", action="store_true", help="build all target architectures")
    parser.add_argument("--force", action="store_true", help="force refresh downloads/build artifacts")
    parser.add_argument("--cache-dir", default=".Cache", help="cache directory root")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.all and not args.arch:
        print("Choose --arch <name> or --all", file=sys.stderr)
        return 2

    root = Path(__file__).resolve().parent.parent
    os.chdir(root)

    cache = CacheLayout((root / args.cache_dir).resolve())
    cache.ensure()

    targets = list(TARGETS.values()) if args.all else [TARGETS[args.arch]]
    for target in targets:
        print(f"=== Building {target.name} ===")
        build_target(root, cache, target, force=args.force)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
