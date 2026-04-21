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
import threading
import urllib.request
from datetime import datetime
from queue import Empty, Queue
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from posixpath import normpath

ALPINE_VERSION = "3.20.5"
UBUNTU_VERSION = "24.04.4"
PROOT_COMMIT = os.environ.get("PROOT_COMMIT", os.environ.get("PROOT_REF"))
QEMU_COMMIT = os.environ.get("QEMU_COMMIT", os.environ.get("QEMU_REF"))
SOURCE_COMMITS: dict[str, str] = {}


@dataclass(frozen=True)
class Target:
    name: str
    alpine_arch: str
    ubuntu_arch: str
    qemu_name: str


TARGETS = {
    "x86_64": Target("x86_64", "x86_64", "amd64", "qemu-x86_64"),
    "aarch64": Target("aarch64", "aarch64", "arm64", "qemu-aarch64"),
    "armv7": Target("armv7", "armv7", "armhf", "qemu-arm"),
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

    def ensure(self) -> None:
        for d in [
            self.root,
            self.download_part,
            self.download_full,
            self.temps,
            self.sources,
            self.tooling,
            self.rootfs,
        ]:
            d.mkdir(parents=True, exist_ok=True)


USE_COLOR = sys.stdout.isatty() or os.environ.get("FORCE_COLOR") == "1"
CPU_COUNT = os.cpu_count() or 2
CTX_SEGMENT_CODES = ["1;36", "1;34", "1;35", "1;33", "1;32", "1;31"]
CTX_ALIAS = {
    "host": "host",
    "deps": "deps",
    "download": "download",
    "source": "source",
    "target": "target",
    "rootfs": "rootfs",
    "build": "build",
    "proot": "proot",
    "qemu": "qemu",
    "configure": "configure",
    "make": "make",
    "install": "install",
    "x86_64": "x86_64",
    "aarch64": "aarch64",
    "armv7": "armv7",
}


def color(text: str, code: str) -> str:
    if not USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def ctx_step(label: str, current: int, total: int) -> str:
    return f"{label}@{current}/{total}"


def compact_ctx_part(part: str) -> str:
    alias = CTX_ALIAS.get(part)
    if alias:
        return alias
    if "/" in part:
        chunks = [chunk for chunk in part.split("/") if chunk]
        return "/".join(compact_ctx_part(chunk) for chunk in chunks)
    return part if len(part) <= 12 else part[:12]


def format_ctx(ctx: str) -> str:
    parts = [part for part in ctx.split(":") if part]
    if not parts:
        parts = ["host"]

    def render_part(part: str, color_code: str) -> tuple[str, str]:
        label, progress = (part.split("@", 1) + [None])[:2] if "@" in part else (part, None)
        label = compact_ctx_part(label)
        show_progress = progress is not None and not progress.endswith("/1")
        plain = label if not show_progress else f"{label} {progress}"
        if not USE_COLOR:
            return plain, plain
        colored_label = color(label, color_code)
        if not show_progress:
            return plain, colored_label
        return plain, f"{colored_label} {color(progress, '1;37')}"

    rendered = [render_part(part, CTX_SEGMENT_CODES[index % len(CTX_SEGMENT_CODES)]) for index, part in enumerate(parts)]
    if not USE_COLOR:
        return " ".join(plain for plain, _ in rendered)
    return " ".join(colored for _, colored in rendered)


def emit_line(ctx: str, prefix: str, line: str) -> None:
    colors = {
        "STEP": "1;34",
        "RUN": "1;36",
        "DL": "1;33",
        "CACHE": "0;32",
        "WARN": "1;31",
        "OUT": "0;90",
        "ERR": "1;31",
    }
    base = "0;90"
    stamp = color(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), base)
    ctx_label = format_ctx(ctx)
    prefix_label = color(prefix.lower(), colors.get(prefix, base))
    if prefix == "OUT":
        message = color(line, base)
    elif prefix == "ERR":
        message = color(line, colors["ERR"])
    else:
        message = line
    print(f"{stamp} {ctx_label} {prefix_label} {message}", flush=True)


def log(prefix: str, message: str, ctx: str = "host") -> None:
    lines = message.splitlines() or [""]
    for line in lines:
        emit_line(ctx, prefix, line)


def shell_quote(text: str) -> str:
    return "'" + text.replace("'", "'\"'\"'") + "'"


def command_log_text(cmd: list[str]) -> str:
    return " ".join(part.replace("\n", "\\n") for part in cmd)


def write_stamp(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload + "\n", encoding="utf-8")


def stamp_matches(path: Path, payload: str) -> bool:
    if not path.exists():
        return False
    try:
        return path.read_text(encoding="utf-8").strip() == payload
    except OSError:
        return False


def ensure_rootfs_layout(rootfs_dir: Path) -> bool:
    changed = False
    busybox = rootfs_dir / "bin" / "busybox"
    shell = rootfs_dir / "bin" / "sh"
    if not shell.exists() and busybox.exists():
        shell.parent.mkdir(parents=True, exist_ok=True)
        if shell.is_symlink() or shell.exists():
            shell.unlink()
        os.symlink("busybox", shell)
        changed = True
    return changed


def rootfs_ready(rootfs_dir: Path, libc: str) -> bool:
    if libc == "musl":
        return (rootfs_dir / "etc" / "os-release").exists() and (rootfs_dir / "bin" / "sh").exists() and (rootfs_dir / "sbin" / "apk").exists()
    else:
        return (rootfs_dir / "etc" / "os-release").exists() and (rootfs_dir / "bin" / "sh").exists() and (rootfs_dir / "usr" / "bin" / "apt").exists()


def run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None, ctx: str = "host") -> None:
    wd = f" (cwd={cwd})" if cwd else ""
    log("RUN", f"{command_log_text(cmd)}{wd}", ctx=ctx)
    process = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None and process.stderr is not None

    queue: Queue[tuple[str, str] | tuple[str, None]] = Queue()

    def pump(stream_name: str, pipe: object) -> None:
        assert pipe is not None
        for raw_line in pipe:
            queue.put((stream_name, raw_line.rstrip("\n")))
        queue.put((stream_name, None))

    threads = [
        threading.Thread(target=pump, args=("OUT", process.stdout), daemon=True),
        threading.Thread(target=pump, args=("ERR", process.stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()

    closed_streams = 0
    while closed_streams < 2:
        try:
            stream_name, payload = queue.get(timeout=0.1)
        except Empty:
            if process.poll() is not None and not any(thread.is_alive() for thread in threads):
                break
            continue
        if payload is None:
            closed_streams += 1
            continue
        log(stream_name, payload, ctx=ctx)

    for thread in threads:
        thread.join()
    rc = process.wait()
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd)


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def is_ubuntu_like() -> bool:
    os_release = Path("/etc/os-release")
    if not os_release.exists():
        return False
    text = os_release.read_text(encoding="utf-8", errors="ignore").lower()
    return "ubuntu" in text or "debian" in text


def resolve_repo_commit(repo: str, override: str | None) -> str:
    if override:
        return override
    cached = SOURCE_COMMITS.get(repo)
    if cached:
        return cached

    output = subprocess.check_output(["git", "ls-remote", f"https://github.com/{repo}.git", "HEAD"], text=True)
    commit = output.split()[0].strip()
    if not is_commitish(commit):
        raise RuntimeError(f"Failed to resolve HEAD commit for {repo}: {output!r}")
    SOURCE_COMMITS[repo] = commit
    log("STEP", f"Resolved {repo} HEAD to {commit}", ctx=f"source:{repo}")
    return commit


def patch_proot_gnumakefile(source_root: Path, build_version: str) -> None:
    makefile = source_root / "src" / "GNUmakefile"
    text = makefile.read_text(encoding="utf-8")
    old = "GIT_VERSION := $(shell git describe --tags `git rev-list --tags --max-count=1`)\n\nGIT_COMMIT := $(shell git rev-list --all --max-count=1 | cut -c 1-8)\n\nVERSION = $(GIT_VERSION)-$(GIT_COMMIT)\n"
    new = f"GIT_VERSION :=\n\nGIT_COMMIT := {build_version}\n\nVERSION ?= {build_version}\n"
    if old in text:
        text = text.replace(old, new, 1)
    else:
        text = text.replace("VERSION = $(GIT_VERSION)-$(GIT_COMMIT)\n", f"VERSION ?= {build_version}\n", 1)
    if "CFLAGS   += $(EXTRA_CFLAGS)\n" not in text:
        text = text.replace("CFLAGS   += $(shell pkg-config --cflags talloc)\n", "CFLAGS   += $(shell pkg-config --cflags talloc)\nCFLAGS   += $(EXTRA_CFLAGS)\n", 1)
    if "LDFLAGS  += $(EXTRA_LDFLAGS)\n" not in text:
        text = text.replace("LDFLAGS  += $(shell pkg-config --libs talloc)\n", "LDFLAGS  += $(shell pkg-config --libs talloc)\nLDFLAGS  += $(EXTRA_LDFLAGS)\n", 1)
    tmp = makefile.with_suffix(makefile.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(makefile)


def ensure_host_packages() -> None:
    required_commands = ["make", "gcc", "pkg-config", "meson", "ninja", "bison", "flex"]
    missing = [c for c in required_commands if not command_exists(c)]
    if not missing:
        log("CACHE", "Host build dependencies already available")
        return

    if not is_ubuntu_like():
        raise RuntimeError(f"Missing required tools: {missing}. Automatic install currently supports Ubuntu/Debian only.")

    apt_packages = [
        "build-essential",
        "make",
        "file",
        "pkg-config",
        "git",
        "ninja-build",
        "meson",
        "bison",
        "flex",
        "libglib2.0-dev",
        "libpixman-1-dev",
        "zlib1g-dev",
        "python3-venv",
    ]

    prefix = [] if os.geteuid() == 0 else ["sudo"]
    log("STEP", f"Installing missing host dependencies: {', '.join(missing)}")
    run(prefix + ["apt-get", "update"], ctx="deps")
    run(prefix + ["apt-get", "install", "-y", "--no-install-recommends", *apt_packages], ctx="deps")


def detect_host_arch() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    if machine in ("aarch64", "arm64"):
        return "aarch64"
    if machine.startswith("armv7") or machine.startswith("arm"):
        return "armv7"
    raise RuntimeError(f"Unsupported host architecture: {machine}")


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_within_directory(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def normalize_tar_member_name(name: str) -> str:
    normalized = normpath(name).lstrip("/")
    if normalized in ("", "."):
        return ""
    return normalized


def safe_link_target(base_dir: Path, link_name: str, root: Path) -> None:
    root_resolved = root.resolve()
    if os.path.isabs(link_name):
        resolved = (root_resolved / link_name.lstrip("/")).resolve()
    else:
        resolved = (base_dir.resolve() / link_name).resolve()
    if not is_within_directory(root_resolved, resolved):
        raise RuntimeError(f"Unsafe archive link target: {link_name}")


def safe_extract_tar(archive: Path, destination: Path, strip_top_level: bool = False) -> None:
    with tarfile.open(archive, "r:*") as tf:
        members = tf.getmembers()
        top_levels = set()
        for member in members:
            normalized = normalize_tar_member_name(member.name)
            if normalized:
                top_levels.add(Path(normalized).parts[0])
        strip_prefix = ""
        if strip_top_level:
            if len(top_levels) != 1:
                raise RuntimeError(f"Expected exactly one top-level entry in {archive.name}, found {sorted(top_levels)}")
            strip_prefix = f"{next(iter(top_levels))}/"

        prepared: list[tuple[tarfile.TarInfo, Path]] = []
        for member in members:
            name = normalize_tar_member_name(member.name)
            if not name:
                continue
            if strip_prefix:
                if name == strip_prefix[:-1]:
                    continue
                if not name.startswith(strip_prefix):
                    raise RuntimeError(f"Archive entry outside expected root {strip_prefix}: {member.name}")
                name = name[len(strip_prefix):]
                if not name:
                    continue

            target = destination / name
            if not is_within_directory(destination, target):
                raise RuntimeError(f"Unsafe archive entry: {member.name}")
            prepared.append((member, target))

        for member, target in prepared:
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)

        for member, target in prepared:
            if member.isdir() or member.issym() or member.islnk():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            extracted = tf.extractfile(member)
            if extracted is None:
                continue
            with extracted, open(target, "wb") as out:
                shutil.copyfileobj(extracted, out)
            if member.mode:
                os.chmod(target, member.mode)

        for member, target in prepared:
            if not (member.issym() or member.islnk()):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            if member.issym():
                safe_link_target(target.parent, member.linkname, destination)
                os.symlink(member.linkname, target)
                continue

            linked_name = normalize_tar_member_name(member.linkname)
            if strip_prefix and linked_name.startswith(strip_prefix):
                linked_name = linked_name[len(strip_prefix):]
            if not linked_name:
                raise RuntimeError(f"Invalid hard link target in archive: {member.name}")
            linked_target = destination / linked_name
            if not is_within_directory(destination, linked_target):
                raise RuntimeError(f"Unsafe hard link target in archive: {member.linkname}")
            if not linked_target.exists():
                raise RuntimeError(f"Hard link target missing during extraction: {member.linkname}")
            os.link(linked_target, target)


def resumable_download(url: str, full_dir: Path, part_dir: Path, force: bool = False) -> Path:
    guessed_name = url.rstrip("/").split("/")[-1] or f"asset-{sha256_of(url)[:12]}"
    final_path = full_dir / guessed_name
    part_path = part_dir / f"{guessed_name}.part"

    if final_path.exists() and not force:
        log("CACHE", f"Using cached download: {final_path.name}", ctx="download")
        return final_path

    downloaded = part_path.stat().st_size if part_path.exists() else 0
    headers = {}
    if downloaded > 0:
        headers["Range"] = f"bytes={downloaded}-"

    req = urllib.request.Request(url, headers=headers)
    log("DL", f"Downloading: {url}", ctx="download")
    with urllib.request.urlopen(req) as resp:
        status = getattr(resp, "status", 200)
        if status == 206:
            mode = "ab"
        elif status == 200:
            mode = "wb"
        else:
            raise RuntimeError(f"Unexpected HTTP status {status} for {url}")

        with open(part_path, mode) as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)

    part_path.replace(final_path)
    log("DL", f"Saved: {final_path}", ctx="download")
    return final_path


def is_commitish(ref: str) -> bool:
    return len(ref) in (7, 40) and all(ch in "0123456789abcdef" for ch in ref.lower())


def source_ready(repo: str, src_dir: Path) -> bool:
    checks = {
        "proot-me/proot": [src_dir / "src" / "GNUmakefile", src_dir / "src" / "loader" / "loader.c"],
        "qemu/qemu": [src_dir / "configure"],
    }
    required = checks.get(repo)
    if not required:
        return src_dir.exists()
    for required_path in required:
        if not required_path.exists():
            return False
        if required_path.is_file() and required_path.stat().st_size == 0:
            return False
    return True


def source_archive_url(repo: str, ref: str) -> str:
    if is_commitish(ref):
        return f"https://github.com/{repo}/archive/{ref}.tar.gz"
    kind = 'tags' if ref.startswith('v') else 'heads'
    return f"https://github.com/{repo}/archive/refs/{kind}/{ref}.tar.gz"


def prepare_source_archive(cache: CacheLayout, repo: str, ref: str, force: bool) -> Path:
    src_dir = cache.sources / repo / f"{repo.split('/')[-1]}-{ref}"
    src_ctx = f"source:{repo}"
    if src_dir.exists() and not force:
        if source_ready(repo, src_dir):
            log("CACHE", f"Using cached source: {repo}@{ref}", ctx=src_ctx)
            return src_dir
        log("WARN", f"Refreshing invalid cached source: {repo}@{ref}", ctx=src_ctx)
        shutil.rmtree(src_dir)

    url = source_archive_url(repo, ref)
    archive = resumable_download(url, cache.download_full, cache.download_part, force=force)

    src_dir.parent.mkdir(parents=True, exist_ok=True)
    if src_dir.exists():
        shutil.rmtree(src_dir)
    src_dir.mkdir(parents=True, exist_ok=True)
    try:
        run(["tar", "-xf", str(archive), "-C", str(src_dir), "--strip-components=1", "--overwrite"], ctx=src_ctx)
    except Exception:
        shutil.rmtree(src_dir, ignore_errors=True)
        raise
    return src_dir


def prepare_proot(cache: CacheLayout, force: bool) -> Path:
    out_bin = cache.tooling / "proot"
    out_stamp = cache.tooling / ".proot.stamp"
    build_ctx = f"{ctx_step('tooling', 1, 2)}:{ctx_step('proot', 1, 1)}"
    proot_commit = resolve_repo_commit("proot-me/proot", PROOT_COMMIT)
    if out_bin.exists() and not force:
        if not out_stamp.exists():
            write_stamp(out_stamp, proot_commit)
        log("CACHE", f"Using cached built proot from {proot_commit[:8]}", ctx=build_ctx)
        return out_bin

    source = prepare_source_archive(cache, "proot-me/proot", proot_commit, force)
    build_version = proot_commit[:8]
    patch_proot_gnumakefile(source, build_version)
    log("STEP", "Building host proot from source", ctx=build_ctx)
    run(["make", "-C", str(source / "src"), "clean"], ctx=build_ctx)
    run(["make", "-C", str(source / "src"), "-j", str(CPU_COUNT), f"VERSION={build_version}", "CFLAGS+=-Wno-error", "proot"], ctx=build_ctx)

    built = source / "src" / "proot"
    if not built.exists():
        raise RuntimeError(f"Failed to build host proot from source: {built}")

    out_bin.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built, out_bin)
    out_bin.chmod(0o755)
    write_stamp(out_stamp, proot_commit)
    return out_bin


def prepare_qemu(cache: CacheLayout, force: bool) -> Path:
    qemu_ctx = f"{ctx_step('tooling', 2, 2)}:{ctx_step('qemu', 1, 3)}"
    qemu_commit = resolve_repo_commit("qemu/qemu", QEMU_COMMIT)
    source = prepare_source_archive(cache, "qemu/qemu", qemu_commit, force)
    build_dir = cache.tooling / f"qemu-build-{qemu_commit}"
    install_dir = cache.tooling / f"qemu-install-{qemu_commit}"

    required_bins = [install_dir / "bin" / t.qemu_name for t in TARGETS.values()]
    if (not force) and all(p.exists() for p in required_bins):
        log("CACHE", f"Using cached built qemu-user from {install_dir.name}", ctx=qemu_ctx)
        return install_dir

    configure_ctx = f"{ctx_step('tooling', 2, 2)}:{ctx_step('qemu', 1, 3)}:{ctx_step('configure', 1, 3)}"
    make_ctx = f"{ctx_step('tooling', 2, 2)}:{ctx_step('qemu', 2, 3)}:{ctx_step('make', 2, 3)}"
    install_ctx = f"{ctx_step('tooling', 2, 2)}:{ctx_step('qemu', 3, 3)}:{ctx_step('install', 3, 3)}"
    configure_cmd = [
        str(source / "configure"),
        "--target-list=x86_64-linux-user,aarch64-linux-user,arm-linux-user",
        "--disable-system",
        "--enable-linux-user",
        "--disable-tools",
        "--disable-docs",
        "--disable-werror",
        f"--prefix={install_dir}",
    ]
    configure_sig = sha256_of("\n".join(configure_cmd + [str(source), str(install_dir)]))
    build_sig = sha256_of(f"make\n{CPU_COUNT}\n{qemu_commit}\n{source}")
    install_sig = sha256_of(f"install\n{install_dir}\n{qemu_commit}")
    configure_stamp = build_dir / ".configure.stamp"
    make_stamp = build_dir / ".make.stamp"
    install_stamp = install_dir / ".install.stamp"

    configured = build_dir.exists() and (build_dir / 'build.ninja').exists()
    if force and build_dir.exists():
        shutil.rmtree(build_dir)
        configured = False
    if force and install_dir.exists():
        shutil.rmtree(install_dir)

    if configured and not force:
        if stamp_matches(configure_stamp, configure_sig):
            log("CACHE", f"Reusing configured qemu build dir {build_dir.name}", ctx=configure_ctx)
        else:
            configured = False
    if not configured:
        if build_dir.exists():
            shutil.rmtree(build_dir)
        build_dir.mkdir(parents=True, exist_ok=True)
        log("STEP", "Building host qemu-user from source", ctx=qemu_ctx)
        run(configure_cmd, cwd=build_dir, ctx=configure_ctx)
        write_stamp(configure_stamp, configure_sig)

    if stamp_matches(make_stamp, build_sig):
        log("CACHE", "Skipping qemu make; build stamp is current", ctx=make_ctx)
    else:
        run(["make", "-C", str(build_dir), "-j", str(CPU_COUNT)], ctx=make_ctx)
        write_stamp(make_stamp, build_sig)

    if all(p.exists() for p in required_bins) and stamp_matches(install_stamp, install_sig):
        log("CACHE", "Skipping qemu install; install stamp is current", ctx=install_ctx)
    else:
        run(["make", "-C", str(build_dir), "install"], ctx=install_ctx)
        write_stamp(install_stamp, install_sig)

    for required in required_bins:
        if not required.exists():
            raise RuntimeError(f"Missing built qemu binary: {required}")

    return install_dir


def prepare_rootfs(cache: CacheLayout, target: Target, libc: str, force: bool, ctx: str | None = None) -> Path:
    rootfs_dir = cache.rootfs / f"{target.name}-{libc}"
    rootfs_ctx = ctx or f"rootfs:{target.name}:{libc}"
    rootfs_sig = sha256_of(f"{target.name}\n{libc}\n{target.alpine_arch}\n{target.ubuntu_arch}\n{ALPINE_VERSION}")
    rootfs_stamp = rootfs_dir / ".rootfs.stamp"

    if rootfs_dir.exists() and not force:
        if libc == "musl" and ensure_rootfs_layout(rootfs_dir):
            log("WARN", f"Repaired cached rootfs shell layout: {target.name}", ctx=rootfs_ctx)
        if rootfs_ready(rootfs_dir, libc) and stamp_matches(rootfs_stamp, rootfs_sig):
            log("CACHE", f"Using cached rootfs: {target.name}-{libc}", ctx=rootfs_ctx)
            return rootfs_dir
        log("WARN", f"Refreshing invalid cached rootfs: {target.name}-{libc}", ctx=rootfs_ctx)
        shutil.rmtree(rootfs_dir)

    if rootfs_dir.exists():
        shutil.rmtree(rootfs_dir)
    rootfs_dir.mkdir(parents=True, exist_ok=True)

    if libc == "musl":
        url = (
            f"https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/{target.alpine_arch}/"
            f"alpine-minirootfs-{ALPINE_VERSION}-{target.alpine_arch}.tar.gz"
        )
    else:
        url = (
            f"http://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/"
            f"ubuntu-base-{UBUNTU_VERSION}-base-{target.ubuntu_arch}.tar.gz"
        )

    archive = resumable_download(url, cache.download_full, cache.download_part, force=force)
    run(["tar", "-xf", str(archive), "-C", str(rootfs_dir), "--overwrite"], ctx=rootfs_ctx)
    if libc == "musl":
        ensure_rootfs_layout(rootfs_dir)
    if not rootfs_ready(rootfs_dir, libc):
        raise RuntimeError(f"Extracted rootfs is incomplete for {target.name}-{libc}: {rootfs_dir}")
    write_stamp(rootfs_stamp, rootfs_sig)
    return rootfs_dir


def proot_base_cmd(
    proot: Path,
    rootfs: Path,
    work: Path,
    qemu: Path | None,
    extra_binds: list[tuple[Path, str]] | None = None,
) -> list[str]:
    cmd = [
        str(proot), "-0", "-r", str(rootfs),
        "-b", "/dev", "-b", "/proc", "-b", "/sys", "-b", "/etc/resolv.conf",
        "-b", f"{work}:/work", "-w", "/work",
    ]
    for host_path, guest_path in extra_binds or []:
        cmd += ["-b", f"{host_path}:{guest_path}"]
    if qemu is not None:
        cmd += ["-q", str(qemu)]
    return cmd


def run_in_rootfs(
    proot: Path,
    rootfs: Path,
    work: Path,
    qemu: Path | None,
    inner: list[str],
    ctx: str | None = None,
    extra_binds: list[tuple[Path, str]] | None = None,
) -> None:
    env = os.environ.copy()
    env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    run(proot_base_cmd(proot, rootfs, work, qemu, extra_binds=extra_binds) + inner, env=env, ctx=ctx or f"rootfs:{rootfs.name}")


def build_target(
    project_root: Path,
    cache: CacheLayout,
    target: Target,
    libc: str,
    force: bool,
    proot_bin: Path,
    qemu_install: Path,
    target_index: int,
    target_total: int,
    dist_dir: Path,
) -> None:
    output_bin = dist_dir / f"proot-{target.name}-{libc}"
    target_ctx = f"{ctx_step('target', target_index, target_total)}:{target.name}:{libc}"

    host_arch = detect_host_arch()
    qemu_bin = None if target.name == host_arch else (qemu_install / "bin" / target.qemu_name)

    log("STEP", f"Preparing target environment: {target.name} ({libc})", ctx=target_ctx)
    rootfs = prepare_rootfs(cache, target, libc, force, ctx=f"{target_ctx}:{ctx_step('rootfs', 1, 3)}")
    proot_commit = resolve_repo_commit("proot-me/proot", PROOT_COMMIT)
    source = prepare_source_archive(cache, "proot-me/proot", proot_commit, force)
    build_version = proot_commit[:8]
    patch_proot_gnumakefile(source, build_version)

    work_target = cache.temps / f"work-{target.name}-{libc}"
    if work_target.exists():
        shutil.rmtree(work_target)
    work_target.mkdir(parents=True, exist_ok=True)

    pkg_ctx = f"{target_ctx}:{ctx_step('packages', 2, 3)}"
    if libc == "musl":
        repos = "https://dl-cdn.alpinelinux.org/alpine/v3.20/main\nhttps://dl-cdn.alpinelinux.org/alpine/v3.20/community\n"
        pkg_list = ["build-base", "linux-headers", "make", "file", "git", "talloc-dev", "talloc-static", "bsd-compat-headers"]
        pkg_sig = sha256_of("\n".join([ALPINE_VERSION, target.name, repos, *pkg_list]))
        pkg_stamp = rootfs / ".packages.stamp"
        if stamp_matches(pkg_stamp, pkg_sig):
            log("CACHE", f"Using cached packages: {target.name}", ctx=pkg_ctx)
        else:
            run_in_rootfs(proot_bin, rootfs, work_target, qemu_bin, ["/bin/sh", "-lc", f"printf %s {shell_quote(repos)} > /etc/apk/repositories"], ctx=pkg_ctx)
            run_in_rootfs(proot_bin, rootfs, work_target, qemu_bin, ["/sbin/apk", "update"], ctx=pkg_ctx)
            run_in_rootfs(proot_bin, rootfs, work_target, qemu_bin, ["/sbin/apk", "add", "--no-cache", *pkg_list], ctx=pkg_ctx)
            write_stamp(pkg_stamp, pkg_sig)
    else:
        pkg_list = ["build-essential", "libtalloc-dev", "make", "file", "git"]
        pkg_sig = sha256_of("\n".join([target.name, "ubuntu-24.04", *pkg_list]))
        pkg_stamp = rootfs / ".packages.stamp"
        if stamp_matches(pkg_stamp, pkg_sig):
            log("CACHE", f"Using cached packages: {target.name}", ctx=pkg_ctx)
        else:
            run_in_rootfs(proot_bin, rootfs, work_target, qemu_bin, ["/usr/bin/apt-get", "update"], ctx=pkg_ctx)
            run_in_rootfs(proot_bin, rootfs, work_target, qemu_bin, ["/usr/bin/apt-get", "install", "-y", "--no-install-recommends", *pkg_list], ctx=pkg_ctx)
            write_stamp(pkg_stamp, pkg_sig)

    build_ctx = f"{target_ctx}:{ctx_step('build', 3, 3)}"
    build_sig = sha256_of("\n".join([
        target.name,
        libc,
        build_version,
        str(source),
        "EXTRA_CFLAGS=-O2 -static -Wno-error",
        "EXTRA_LDFLAGS=-static",
    ]))
    build_stamp = output_bin.with_suffix(output_bin.suffix + ".stamp")
    if output_bin.exists() and stamp_matches(build_stamp, build_sig) and not force:
        log("CACHE", f"Using cached target binary: {output_bin.name}", ctx=build_ctx)
        return
    build_root = f"/tmp/proot-build-{target.name}-{libc}"
    run_in_rootfs(proot_bin, rootfs, work_target, qemu_bin, [
        "/bin/sh",
        "-lc",
        f"set -e; build_root={build_root}; rm -rf \"$build_root\"; mkdir -p \"$build_root\"; cp -a /src-host/. \"$build_root/\"; cd \"$build_root/src\"; make clean >/dev/null 2>&1 || true; : > .check_process_vm.res; : > .check_seccomp_filter.res; make -j {CPU_COUNT} VERSION={build_version} EXTRA_CFLAGS='-O2 -static -Wno-error' EXTRA_LDFLAGS='-static' proot; cp proot /work/proot",
    ], ctx=build_ctx, extra_binds=[(source, "/src-host")])

    built = work_target / "proot"
    if not built.exists():
        raise RuntimeError(f"Build did not produce expected binary for {target.name}: {built}")
    shutil.copy2(built, output_bin)
    output_bin.chmod(0o755)
    write_stamp(build_stamp, build_sig)
    log("STEP", f"Built target binary: {output_bin}", ctx=target_ctx)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build static proot binaries")
    parser.add_argument("--arch", choices=sorted(TARGETS.keys()), help="single target arch")
    parser.add_argument("--all", action="store_true", help="build all target architectures")
    parser.add_argument("--force", action="store_true", help="force refresh downloads/build artifacts")
    parser.add_argument("--cache-dir", default=".Cache", help="cache directory root")
    parser.add_argument("-o", "--output", help="custom output directory (default: dist/)")
    parser.add_argument("--skip-host-packages", action="store_true", help="skip Ubuntu auto package install")
    parser.add_argument("-j", "--jobs", type=int, help="number of parallel jobs per build (default: CPU count)")
    parser.add_argument("-p", "--parallel", type=int, default=1, help="number of architectures to build in parallel (default: 1)")
    libc_group = parser.add_mutually_exclusive_group()
    libc_group.add_argument("--gnu", action="store_const", dest="libc", const="gnu", help="use GNU toolchain (glibc)")
    libc_group.add_argument("--musl", action="store_const", dest="libc", const="musl", help="use musl toolchain (default)")
    parser.set_defaults(libc="musl")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.all and not args.arch:
        print("Choose --arch <name> or --all", file=sys.stderr)
        return 2

    root = Path(__file__).resolve().parent
    os.chdir(root)

    if not args.skip_host_packages:
        ensure_host_packages()

    cache = CacheLayout((root / args.cache_dir).resolve())
    cache.ensure()
    global CPU_COUNT
    CPU_COUNT = args.jobs or max(1, os.cpu_count() or 2)

    dist_dir = Path(args.output).resolve() if args.output else root / "dist"
    dist_dir.mkdir(exist_ok=True, parents=True)

    targets = list(TARGETS.values()) if args.all else [TARGETS[args.arch]]
    log("STEP", f"Preparing shared host tooling with {CPU_COUNT} jobs", ctx=ctx_step('host', 1, 2))
    
    parallel = max(1, args.parallel)
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        fut_proot = pool.submit(prepare_proot, cache, args.force)
        fut_qemu = pool.submit(prepare_qemu, cache, args.force)
        proot_bin = fut_proot.result()
        qemu_install = fut_qemu.result()

    log("STEP", f"Starting target builds (parallel-targets={parallel}, jobs={CPU_COUNT})", ctx=ctx_step('host', 2, 2))
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = [
            pool.submit(build_target, root, cache, target, args.libc, args.force, proot_bin, qemu_install, index + 1, len(targets), dist_dir)
            for index, target in enumerate(targets)
        ]
        for fut in futures:
            fut.result()
    log("STEP", "All requested targets completed", ctx=ctx_step('host', 2, 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
