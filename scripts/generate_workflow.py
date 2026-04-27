#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "release.yml"

WORKFLOW_NAME = "Build and Release"
SCHEDULE_CRON = "0 0 * * *"
DEFAULT_BRANCH = "master"
PYTHON_VERSION = "3.11"

TARGET_ARCHES = ("x86_64", "aarch64", "armv7")
TARGET_LIBCS = ("musl", "gnu")
HOST_BUILD_DEPS = (
    "build-essential",
    "make",
    "file",
    "pkg-config",
    "git",
    "ninja-build",
    "meson",
    "bison",
    "flex",
    "libtalloc-dev",
    "libglib2.0-dev",
    "libpixman-1-dev",
    "zlib1g-dev",
)
HASH_BUILD_PY = "${{ hashFiles('build.py') }}"

STEP_INDENT = "      "
FIELD_INDENT = "        "
BODY_INDENT = "          "
BLOCK_INDENT = "            "


def indent(text: str, prefix: str) -> str:
    return "\n".join(f"{prefix}{line}" if line else line for line in text.splitlines())


def inline_list(items: tuple[str, ...]) -> str:
    return "[" + ", ".join(items) + "]"


def gha(expr: str) -> str:
    return f"${{{{ {expr} }}}}"


def shell_join(items: tuple[str, ...]) -> str:
    return " \\\n            ".join(items)


def yaml_step(name: str | None = None, *, uses: str | None = None, with_lines: tuple[str, ...] = ()) -> str:
    lines: list[str] = []
    if name is None:
        if uses is None:
            raise ValueError("yaml_step requires either name or uses")
        lines.append(f"{STEP_INDENT}- uses: {uses}")
    else:
        lines.append(f"{STEP_INDENT}- name: {name}")
        if uses is not None:
            lines.append(f"{FIELD_INDENT}uses: {uses}")
    if with_lines:
        lines.append(f"{FIELD_INDENT}with:")
        lines.extend(f"{BODY_INDENT}{line}" for line in with_lines)
    return "\n".join(lines)


def yaml_run_step(name: str, script: str, *, shell: str | None = None, env: tuple[str, ...] = (), step_id: str | None = None) -> str:
    lines = [f"{STEP_INDENT}- name: {name}"]
    if step_id is not None:
        lines.append(f"{FIELD_INDENT}id: {step_id}")
    if shell is not None:
        lines.append(f"{FIELD_INDENT}shell: {shell}")
    if env:
        lines.append(f"{FIELD_INDENT}env:")
        lines.extend(f"{BODY_INDENT}{line}" for line in env)
    lines.append(f"{FIELD_INDENT}run: |")
    lines.extend(indent(dedent(script).strip(), BODY_INDENT).splitlines())
    return "\n".join(lines)


def yaml_job(name: str, body_lines: list[str]) -> str:
    return "\n".join([f"{name}:", *body_lines])


def checkout_step() -> str:
    return yaml_step(uses="actions/checkout@v4")


def setup_python_step() -> str:
    return yaml_step(
        "Setup Python",
        uses="actions/setup-python@v5",
        with_lines=(f"python-version: '{PYTHON_VERSION}'",),
    )


def install_host_deps_step() -> str:
    return yaml_run_step(
        "Install host build dependencies",
        f"""
        sudo apt-get update
        sudo apt-get install -y --no-install-recommends \\
          {shell_join(HOST_BUILD_DEPS)}
        """,
    )


def restore_cache_step() -> str:
    return "\n".join(
        [
            f"{STEP_INDENT}- name: Restore cache",
            f"{FIELD_INDENT}uses: actions/cache@v4",
            f"{FIELD_INDENT}with:",
            f"{BODY_INDENT}path: .Cache",
            f"{BODY_INDENT}key: {gha('runner.os')}-proot-cache-{gha('matrix.arch')}-{gha('matrix.libc')}-{HASH_BUILD_PY}",
            f"{BODY_INDENT}restore-keys: |",
            f"{BLOCK_INDENT}{gha('runner.os')}-proot-cache-{gha('matrix.arch')}-{gha('matrix.libc')}-",
        ]
    )


def build_proot_step() -> str:
    return yaml_run_step(
        "Build static proot",
        """
        python3 build.py --arch ${{ matrix.arch }} --${{ matrix.libc }} --parallel 1
        """,
        env=(
            "PROOT_COMMIT: ${{ needs.check-updates.outputs.proot_commit }}",
            "QEMU_COMMIT: ${{ needs.check-updates.outputs.qemu_commit }}",
        ),
    )


def upload_artifact_step() -> str:
    return yaml_step(
        "Upload artifact",
        uses="actions/upload-artifact@v4",
        with_lines=(
            "name: proot-${{ matrix.arch }}-${{ matrix.libc }}",
            "path: dist/proot-${{ matrix.arch }}-${{ matrix.libc }}",
        ),
    )


def download_artifacts_step() -> str:
    return yaml_step(
        "Download artifacts",
        uses="actions/download-artifact@v4",
        with_lines=(
            "path: release-assets",
            "pattern: proot-*",
            "merge-multiple: true",
        ),
    )


def capture_build_date_step() -> str:
    return yaml_run_step(
        "Capture build date",
        """
        echo "build_date=$(date -u +'%Y-%m-%d %H:%M:%S UTC')" >> $GITHUB_OUTPUT
        """,
        shell="bash",
        step_id="meta",
    )


def publish_release_step() -> str:
    return "\n".join(
        [
            f"{STEP_INDENT}- name: Publish release",
            f"{FIELD_INDENT}uses: softprops/action-gh-release@v2",
            f"{FIELD_INDENT}with:",
            f"{BODY_INDENT}tag_name: v{gha('needs.check-updates.outputs.next_version')}",
            f"{BODY_INDENT}name: Release v{gha('needs.check-updates.outputs.next_version')}",
            f"{BODY_INDENT}body: |",
            f"{BLOCK_INDENT}Automated build of static proot binaries.",
            "",
            f"{BLOCK_INDENT}**Components:**",
            f"{BLOCK_INDENT}- proot: {gha('needs.check-updates.outputs.proot_commit')}",
            f"{BLOCK_INDENT}- Build Date: {gha('steps.meta.outputs.build_date')}",
            f"{BODY_INDENT}files: release-assets/*",
        ]
    )


def check_updates_job() -> str:
    return yaml_job(
        "check-updates",
        [
            "  runs-on: ubuntu-latest",
            "  outputs:",
            "    should_build: ${{ steps.check.outputs.should_build }}",
            "    proot_commit: ${{ steps.check.outputs.proot_commit }}",
            "    qemu_commit: ${{ steps.check.outputs.qemu_commit }}",
            "    next_version: ${{ steps.check.outputs.next_version }}",
            "  steps:",
            checkout_step(),
            yaml_run_step(
                "Check for updates",
                """
                set -e
                PROOT_COMMIT=$(git ls-remote https://github.com/proot-me/proot.git HEAD | cut -f1)
                QEMU_COMMIT=$(git ls-remote https://github.com/qemu/qemu.git HEAD | cut -f1)

                echo "Current proot commit: $PROOT_COMMIT"
                echo "Current qemu commit: $QEMU_COMMIT"

                LATEST_RELEASE=$(curl -s https://api.github.com/repos/${{ github.repository }}/releases/latest)
                LATEST_TAG=$(echo "$LATEST_RELEASE" | jq -r '.tag_name // "v0"')
                LATEST_BODY=$(echo "$LATEST_RELEASE" | jq -r '.body // ""')

                VERSION_NUM=$(echo "${LATEST_TAG#v}" | grep -E '^[0-9]+$' || echo "0")
                NEXT_VERSION=$((VERSION_NUM + 1))

                SHOULD_BUILD="true"
                if [[ "${{ github.event_name }}" == "schedule" && "${{ github.event.inputs.force }}" != "true" ]]; then
                  if [[ "$LATEST_BODY" == *"$PROOT_COMMIT"* ]] && [[ "$LATEST_BODY" == *"$QEMU_COMMIT"* ]]; then
                    echo "No updates found in proot or qemu since last release ($LATEST_TAG)."
                    SHOULD_BUILD="false"
                  fi
                fi

                echo "should_build=$SHOULD_BUILD" >> $GITHUB_OUTPUT
                echo "proot_commit=$PROOT_COMMIT" >> $GITHUB_OUTPUT
                echo "qemu_commit=$QEMU_COMMIT" >> $GITHUB_OUTPUT
                echo "next_version=$NEXT_VERSION" >> $GITHUB_OUTPUT
                """,
                shell="bash",
                step_id="check",
            ),
        ],
    )


def build_job() -> str:
    return yaml_job(
        "build",
        [
            "  needs: check-updates",
            "  if: needs.check-updates.outputs.should_build == 'true'",
            "  runs-on: ubuntu-latest",
            "  strategy:",
            "    fail-fast: false",
            "    matrix:",
            f"      arch: {inline_list(TARGET_ARCHES)}",
            f"      libc: {inline_list(TARGET_LIBCS)}",
            "  steps:",
            checkout_step(),
            setup_python_step(),
            install_host_deps_step(),
            restore_cache_step(),
            build_proot_step(),
            upload_artifact_step(),
        ],
    )


def release_job() -> str:
    return yaml_job(
        "release",
        [
            "  needs: [check-updates, build]",
            "  runs-on: ubuntu-latest",
            "  permissions:",
            "    contents: write",
            "  steps:",
            download_artifacts_step(),
            capture_build_date_step(),
            publish_release_step(),
        ],
    )


def render_workflow() -> str:
    return "\n".join(
        [
            f"name: {WORKFLOW_NAME}",
            "",
            "on:",
            "  schedule:",
            f"    - cron: '{SCHEDULE_CRON}'",
            "  push:",
            "    branches:",
            f"      - {DEFAULT_BRANCH}",
            "    paths:",
            "      - 'build.py'",
            "      - '.github/workflows/**'",
            "  workflow_dispatch:",
            "    inputs:",
            "      force:",
            "        description: 'Force build even if no updates found'",
            "        type: boolean",
            "        default: false",
            "",
            "permissions:",
            "  contents: write",
            "",
            "jobs:",
            indent(
                "\n\n".join(
                    [
                        check_updates_job(),
                        build_job(),
                        release_job(),
                    ]
                ),
                "  ",
            ),
            "",
        ]
    )


def write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def main() -> int:
    changed = write_if_changed(WORKFLOW_PATH, render_workflow())
    if changed:
        print(f"Generated {WORKFLOW_PATH.relative_to(ROOT)}")
    else:
        print(f"No changes for {WORKFLOW_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
