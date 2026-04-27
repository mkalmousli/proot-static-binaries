#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / ".site-build"
ASSET_PREFIX = "proot-"
ARCHES = ("x86_64", "aarch64", "armv7")
LIBCS = ("musl", "gnu")
INFO_CACHE: dict[str, dict[str, Any]] = {}

CSS = """
:root {
  color-scheme: dark;
  --bg: #0a0b0d;
  --panel: #121418;
  --panel-2: #0e1114;
  --text: #eef1f4;
  --muted: #99a1aa;
  --line: #2a313a;
}

* {
  box-sizing: border-box;
}

html,
body {
  margin: 0;
  min-height: 100%;
}

body {
  color: var(--text);
  background: var(--bg);
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

a {
  color: inherit;
  text-decoration: none;
}

.shell {
  width: min(1500px, calc(100% - 0.75rem));
  margin: 0 auto;
  padding: 0.35rem 0 0.75rem;
}

.intro,
.release {
  border: 1px solid var(--line);
  background: var(--panel);
  border-radius: 0;
}

.intro {
  padding: 1rem;
  margin-bottom: 0.4rem;
}

.release {
  padding: 0.95rem 1rem;
  margin-top: 0.4rem;
}

.intro-top {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr);
  gap: 1rem;
  align-items: start;
}

.eyebrow,
.meta,
.muted,
.lede {
  color: var(--muted);
}

.eyebrow {
  margin: 0 0 0.45rem;
  font-size: 0.72rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h1,
h2,
h3,
p {
  margin: 0;
}

h1 {
  font-size: clamp(2.5rem, 6vw, 5rem);
  line-height: 0.94;
  letter-spacing: -0.04em;
}

.lede {
  margin-top: 0.8rem;
  max-width: 68ch;
  font-size: clamp(1rem, 1.2vw, 1.15rem);
  line-height: 1.45;
}

.meta-stack {
  display: grid;
  gap: 0.45rem;
}

.meta-box {
  padding: 0.7rem 0.8rem;
  border: 1px solid var(--line);
  background: var(--panel-2);
}

.meta-box span {
  display: block;
  margin-bottom: 0.15rem;
  color: var(--muted);
  font-size: 0.72rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.meta-box strong {
  font-size: 0.98rem;
  font-weight: 600;
  word-break: break-word;
}

.hero-links,
.meta-links {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
  margin-top: 0.8rem;
}

.hero-links {
  margin-top: 0.7rem;
}

.pill,
.button {
  display: inline-flex;
  align-items: center;
  min-height: 2.15rem;
  padding: 0.26rem 0.7rem;
  border: 1px solid var(--line);
  background: #101317;
  font-size: 0.9rem;
  line-height: 1;
}

.hero-link {
  text-decoration: underline;
  text-underline-offset: 0.15em;
}

.versions {
  display: grid;
  gap: 0.55rem;
}

.release-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.6rem;
}

.release-head h2 {
  font-size: 0.95rem;
  letter-spacing: 0.02em;
  text-transform: lowercase;
}

.release-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem;
}

.current-tag {
  display: inline-flex;
  padding: 0.1rem 0.35rem;
  border: 1px solid var(--line);
  background: var(--panel-2);
  color: var(--muted);
  font-size: 0.68rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.release-meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.6rem;
  margin: 0.7rem 0 0.65rem;
}

.release-meta .meta-box {
  min-width: 0;
}

.tables {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.75rem;
}

.download-note {
  margin: 0 0 0.7rem;
  color: var(--muted);
  line-height: 1.45;
}

.snippet {
  border: 1px solid var(--line);
  background: var(--panel-2);
  padding: 0.75rem;
}

.snippet pre {
  margin: 0;
  overflow-x: auto;
  font-size: 0.82rem;
  line-height: 1.45;
  white-space: pre;
}

.snippet code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
}

.snippet .eyebrow {
  margin-bottom: 0.4rem;
}

.snippet .note {
  margin-top: 0.5rem;
  color: var(--muted);
  font-size: 0.85rem;
}

table {
  width: 100%;
  border-collapse: collapse;
  border: 1px solid var(--line);
  background: var(--panel-2);
}

caption {
  padding: 0.75rem 0.8rem 0.5rem;
  text-align: left;
  font-size: 0.95rem;
  text-transform: lowercase;
}

th,
td {
  padding: 0.62rem 0.8rem;
  border-top: 1px solid var(--line);
  text-align: left;
  vertical-align: middle;
}

th {
  color: var(--muted);
  font-size: 0.72rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

td.size,
td.download {
  white-space: nowrap;
}

td.download {
  text-align: right;
}

.muted-cell {
  color: var(--muted);
}

@media (max-width: 960px) {
  .intro-top,
  .release-meta,
  .tables {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .shell {
    width: min(100% - 0.5rem, 100%);
    padding-top: 0.25rem;
  }

  .intro,
  .release {
    padding: 0.8rem;
  }

  h1 {
    font-size: clamp(2.2rem, 14vw, 3.5rem);
  }
}
""".strip()


def repo_slug() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if repo:
        return repo

    try:
        output = subprocess.check_output(["git", "remote", "get-url", "origin"], text=True).strip()
    except Exception as exc:  # pragma: no cover - local fallback
        raise RuntimeError("Unable to determine repository slug") from exc

    if output.endswith(".git"):
        output = output[:-4]
    if output.startswith("git@github.com:"):
        return output.removeprefix("git@github.com:")
    if output.startswith("https://github.com/"):
        return output.removeprefix("https://github.com/")
    raise RuntimeError(f"Unsupported origin URL: {output}")


def fetch_json(url: str, accept: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": "proot-static-binaries-site",
        },
    )
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(request) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:  # pragma: no cover - network/runtime only
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub request failed for {url}: {exc.code} {exc.reason}\n{body}") from exc


def github_api(path: str) -> Any:
    return fetch_json(f"https://api.github.com{path}", "application/vnd.github+json")


def github_json_url(url: str) -> Any:
    return fetch_json(url, "application/json")


def releases() -> list[dict[str, Any]]:
    data = github_api(f"/repos/{repo_slug()}/releases?per_page=100")
    if not isinstance(data, list):
        raise RuntimeError("Unexpected GitHub releases payload")
    return [item for item in data if not item.get("draft")]


def release_info_asset(release: dict[str, Any]) -> dict[str, Any] | None:
    for asset in release.get("assets", []):
        if isinstance(asset, dict) and str(asset.get("name")) == "info.json":
            return asset
    return None


def release_info(release: dict[str, Any]) -> dict[str, Any]:
    asset = release_info_asset(release)
    if not asset:
        return {}
    cache_key = str(asset.get("browser_download_url") or asset.get("id") or "")
    if not cache_key:
        return {}
    if cache_key in INFO_CACHE:
        return INFO_CACHE[cache_key]
    try:
        payload = github_json_url(str(asset["browser_download_url"]))
    except Exception:
        INFO_CACHE[cache_key] = {}
        return {}
    info = payload if isinstance(payload, dict) else {}
    INFO_CACHE[cache_key] = info
    return info


def iso_date(value: str | None) -> str:
    if not value:
        return "unknown"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def timestamp(value: str | None) -> str:
    if not value:
        return "unknown"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def human_size(size: Any) -> str:
    try:
        value = float(size)
    except (TypeError, ValueError):
        return "unknown"
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return "unknown"


def install_command(repo: str) -> str:
    return f'curl -fsSL "https://raw.githubusercontent.com/{repo}/master/install.sh" | sh'


def body_value(release: dict[str, Any], key: str) -> str | None:
    body = str(release.get("body") or "")
    match = re.search(rf"^\s*(?:[-*]\s*)?{re.escape(key)}:\s*(.+)$", body, re.MULTILINE)
    return match.group(1).strip() if match else None


def proot_commit(release: dict[str, Any]) -> str:
    info = release_info(release)
    value = str(info.get("proot_commit") or "").strip()
    if value:
        return value
    value = body_value(release, "proot commit")
    if value:
        return value
    value = body_value(release, "proot")
    if value:
        return value
    target = str(release.get("target_commitish") or "")
    return target if re.fullmatch(r"[0-9a-fA-F]{7,40}", target) else "unknown"


def build_date(release: dict[str, Any]) -> str:
    info = release_info(release)
    value = str(info.get("build_date") or "").strip()
    if value:
        return value
    value = body_value(release, "Build Date")
    if value:
        return value
    return timestamp(str(release.get("published_at") or release.get("created_at") or ""))


def asset_items(release: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        asset
        for asset in release.get("assets", [])
        if isinstance(asset, dict) and str(asset.get("name", "")).startswith(ASSET_PREFIX)
    ]


def asset_map(release: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(asset.get("name") or ""): asset
        for asset in asset_items(release)
        if str(asset.get("name") or "")
    }


def artifact_rows(release: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    rows: dict[str, dict[str, dict[str, Any]]] = {libc: {} for libc in LIBCS}
    assets_by_name = asset_map(release)
    info = release_info(release)
    artifacts = info.get("artifacts")
    if isinstance(artifacts, list):
        for item in artifacts:
            if not isinstance(item, dict):
                continue
            arch = str(item.get("arch") or "")
            libc = str(item.get("libc") or "")
            if arch not in ARCHES or libc not in LIBCS:
                continue
            name = str(item.get("name") or f"proot-{arch}-{libc}")
            asset = assets_by_name.get(name, {})
            rows[libc][arch] = {
                "name": name,
                "size": item.get("size"),
                "sha256": item.get("sha256"),
                "download_url": str(item.get("download_url") or asset.get("browser_download_url") or ""),
            }
        if any(rows[libc] for libc in LIBCS):
            return rows

    for asset in asset_items(release):
        name = str(asset.get("name") or "")
        match = re.fullmatch(r"proot-(x86_64|aarch64|armv7)-(musl|gnu)", name)
        if not match:
            continue
        arch, libc = match.groups()
        rows[libc][arch] = {
            "name": name,
            "size": asset.get("size"),
            "sha256": None,
            "download_url": str(asset.get("browser_download_url") or ""),
        }
    return rows


def download_table(release: dict[str, Any], libc: str) -> str:
    rows = artifact_rows(release).get(libc, {})
    rendered = []
    for arch in ARCHES:
        item = rows.get(arch)
        if item:
            rendered.append(
                "<tr>"
                f"<td>{escape(arch)}</td>"
                f'<td class="size">{escape(human_size(item.get("size")))}</td>'
                f'<td class="download"><a class="button" href="{escape(item["download_url"])}">download</a></td>'
                "</tr>"
            )
        else:
            rendered.append(
                "<tr>"
                f"<td>{escape(arch)}</td>"
                '<td class="size muted-cell">missing</td>'
                '<td class="download muted-cell">-</td>'
                "</tr>"
            )

    return f"""
      <table>
        <caption>{escape(libc)}</caption>
        <thead>
          <tr>
            <th>arch</th>
            <th>size</th>
            <th>download</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rendered)}
        </tbody>
      </table>
    """


def page_shell(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <link rel="stylesheet" href="./style.css">
</head>
<body>
{body}
</body>
</html>
"""


def release_section(release: dict[str, Any], repo_url: str, current: bool = False) -> str:
    tag_name = str(release.get("tag_name") or "release")
    tag = escape(tag_name)
    commit_value = proot_commit(release)
    commit = escape(commit_value)
    date = escape(build_date(release))
    commit_link = (
        f'<a href="https://github.com/proot-me/proot/commit/{escape(commit_value)}">{commit}</a>'
        if re.fullmatch(r"[0-9a-fA-F]{7,40}", commit_value)
        else commit
    )
    release_url = f"{repo_url}/releases/tag/{tag_name}"
    badge = '<span class="current-tag">current</span>' if current else ""

    return f"""
    <section class="release" id="{escape(tag_name)}">
      <div class="release-head">
        <div class="release-title">
          <h2>{tag}{badge}</h2>
        </div>
        <a class="button" href="{escape(release_url)}">open on github</a>
      </div>
      <div class="release-meta">
        <div class="meta-box"><span>proot commit</span><strong>{commit_link}</strong></div>
        <div class="meta-box"><span>build date</span><strong>{date}</strong></div>
        <div class="meta-box"><span>tag</span><strong>{tag}</strong></div>
      </div>
      <p class="download-note">musl builds are linked against musl libc and stay smaller. gnu builds use glibc and are usually a better fit for glibc-based systems.</p>
      <div class="tables">
        {download_table(release, "musl")}
        {download_table(release, "gnu")}
      </div>
    </section>
    """


def index_page(releases_list: list[dict[str, Any]], repo_url: str, repo_slug_value: str) -> str:
    versions = "\n".join(
        release_section(release, repo_url, current=index == 0)
        for index, release in enumerate(releases_list)
    ) if releases_list else '<p class="muted">No releases published yet.</p>'

    body = f"""
  <main class="shell">
    <section class="intro">
      <div class="intro-top">
        <div>
          <p class="eyebrow">proot static binaries</p>
          <h1>proot static binaries</h1>
          <p class="lede">This project builds static proot binaries from upstream proot commits and publishes them as GitHub Releases.</p>
          <div class="hero-links">
            <a class="button" href="{escape(repo_url)}">github repo</a>
            <a class="button" href="https://raw.githubusercontent.com/{escape(repo_slug_value)}/master/install.sh">install.sh</a>
          </div>
        </div>
        <div class="snippet">
          <p class="eyebrow">install</p>
          <pre><code>{escape(install_command(repo_slug_value))}</code></pre>
          <div class="note">Hosted installer that picks the right binary for your arch and libc.</div>
        </div>
      </div>
    </section>
    <section class="versions" id="versions">
      <div class="release-head">
        <h2>versions</h2>
        <span class="muted">latest first</span>
      </div>
      {versions}
    </section>
  </main>
"""
    return page_shell("proot", body)


def write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def main() -> int:
    repo = repo_slug()
    repo_url = f"https://github.com/{repo}"
    release_list = releases()

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)

    changed = False
    changed |= write_if_changed(OUT_DIR / "style.css", CSS + "\n")
    changed |= write_if_changed(OUT_DIR / ".nojekyll", "")
    changed |= write_if_changed(OUT_DIR / "index.html", index_page(release_list, repo_url, repo))

    print(f"{'Generated' if changed else 'No changes for'} {OUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
