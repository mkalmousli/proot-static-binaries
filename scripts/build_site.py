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

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / ".site-build"
RELEASES_DIR = OUT_DIR / "releases"
ASSET_PREFIX = "proot-"
ARCHES = ("x86_64", "aarch64", "armv7")
LIBCS = ("musl", "gnu")
INFO_CACHE: dict[str, dict[str, Any]] = {}

CSS = """
:root {
  color-scheme: dark;
  --bg: #0a0b0d;
  --panel: #121418;
  --panel-2: #0f1114;
  --text: #eef1f4;
  --muted: #98a0aa;
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
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: var(--text);
  background: var(--bg);
}

a {
  color: inherit;
  text-decoration: none;
}

.shell {
  width: min(1560px, calc(100% - 0.75rem));
  margin: 0 auto;
  padding: 0.35rem 0 0.75rem;
}

.hero,
.panel,
.detail {
  border: 1px solid var(--line);
  background: var(--panel);
}

.hero,
.panel,
.detail {
  border-radius: 0;
}

.hero {
  padding: 1.4rem;
  margin-bottom: 0.4rem;
}

.hero-top {
  display: grid;
  grid-template-columns: minmax(0, 1.65fr) minmax(310px, 0.95fr);
  gap: 1.1rem;
  align-items: start;
}

.hero.tight {
  margin-top: 0.5rem;
}

.panel,
.detail {
  padding: 1rem 1.05rem;
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
  font-size: clamp(2.6rem, 7vw, 5.2rem);
  line-height: 0.94;
  letter-spacing: -0.04em;
}

.lede {
  margin-top: 0.8rem;
  max-width: 60ch;
  font-size: clamp(1rem, 1.35vw, 1.2rem);
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

.row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.85rem;
}

.pill {
  display: inline-flex;
  align-items: center;
  min-height: 2rem;
  padding: 0.25rem 0.55rem;
  border: 1px solid var(--line);
  background: #101317;
  font-size: 0.9rem;
}

.button {
  display: inline-flex;
  align-items: center;
  min-height: 2.2rem;
  padding: 0.28rem 0.75rem;
  border: 1px solid var(--line);
  background: #171a20;
  font-size: 0.9rem;
  text-decoration: none;
}

.hero-links,
.meta-links {
  display: flex;
  flex-wrap: wrap;
  gap: 0.7rem;
  margin-top: 0.8rem;
  font-size: 0.95rem;
}

.hero-links a,
.meta-links a,
.section-head a,
.version-row {
  text-decoration: underline;
  text-underline-offset: 0.15em;
}

.section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.6rem;
}

.section-head h2 {
  font-size: 0.95rem;
  letter-spacing: 0.02em;
  text-transform: lowercase;
}

.version-list {
  display: grid;
}

.version-row {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(220px, 0.7fr) minmax(160px, 0.6fr) 120px;
  gap: 0.75rem;
  align-items: center;
  padding: 0.68rem 0;
  border-top: 1px solid var(--line);
  font-size: 0.95rem;
}

.version-row:first-child {
  border-top: 0;
}

.version-row strong {
  display: block;
  font-size: 1.02rem;
}

.version-row .current-tag {
  display: inline-flex;
  margin-left: 0.45rem;
  padding: 0.1rem 0.35rem;
  border: 1px solid var(--line);
  background: var(--panel-2);
  color: var(--muted);
  font-size: 0.68rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.version-row .commit,
.version-row .date {
  color: var(--muted);
}

.version-row .actions {
  justify-self: end;
}

.detail {
  display: grid;
  gap: 1rem;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.6rem;
}

.downloads {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.libc-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.75rem;
}

.matrix {
  width: 100%;
  border-collapse: collapse;
  background: var(--panel-2);
  border: 1px solid var(--line);
}

.matrix caption {
  padding: 0.75rem 0.8rem 0.5rem;
  text-align: left;
  font-size: 0.95rem;
  letter-spacing: 0.02em;
  text-transform: lowercase;
}

.matrix th,
.matrix td {
  padding: 0.62rem 0.8rem;
  border-top: 1px solid var(--line);
  text-align: left;
  vertical-align: middle;
}

.matrix th {
  color: var(--muted);
  font-size: 0.72rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.matrix td.size,
.matrix td.download {
  white-space: nowrap;
}

.matrix td.download {
  text-align: right;
}

.matrix .muted-cell {
  color: var(--muted);
}

.note {
  max-width: 68ch;
  line-height: 1.45;
  color: var(--muted);
}

@media (max-width: 900px) {
  .hero-top,
  .detail-grid {
    grid-template-columns: 1fr;
  }

  .libc-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .shell {
    width: min(100% - 0.5rem, 100%);
    padding-top: 0.25rem;
  }

  .hero,
  .panel,
  .detail {
    padding: 0.8rem;
  }

  h1 {
    font-size: clamp(2.3rem, 14vw, 3.4rem);
  }

  .version-row {
    grid-template-columns: 1fr;
    gap: 0.15rem;
  }

  .version-row .actions {
    justify-self: start;
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
    units = ["B", "KiB", "MiB", "GiB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return "unknown"


def slugify(tag: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", tag).strip("-")
    return slug.lower() or "release"


def body_value(release: dict[str, Any], key: str) -> str | None:
    body = str(release.get("body") or "")
    match = re.search(rf"^\s*(?:[-*]\s*)?{re.escape(key)}:\s*(.+)$", body, re.MULTILINE)
    return match.group(1).strip() if match else None


def proot_commit(release: dict[str, Any]) -> str:
    info = release_info(release)
    value = str(info.get("proot_commit") or "").strip()
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
    return body_value(release, "Build Date") or timestamp(str(release.get("published_at") or release.get("created_at") or ""))


def asset_items(release: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        asset
        for asset in release.get("assets", [])
        if isinstance(asset, dict) and str(asset.get("name", "")).startswith(ASSET_PREFIX)
    ]


def asset_label(name: str) -> str:
    return " / ".join(name.removeprefix(ASSET_PREFIX).split("-"))


def asset_links(release: dict[str, Any]) -> str:
    assets = asset_items(release)
    if not assets:
        return '<p class="muted">No assets.</p>'
    return "".join(
        f'<a class="pill" href="{escape(str(asset["browser_download_url"]))}">{escape(asset_label(str(asset["name"])))}</a>'
        for asset in assets
    )


def artifact_rows(release: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    rows: dict[str, dict[str, dict[str, Any]]] = {libc: {} for libc in LIBCS}
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
            rows[libc][arch] = {
                "name": str(item.get("name") or f"proot-{arch}-{libc}"),
                "size": item.get("size"),
                "download_url": str(item.get("download_url") or ""),
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
            "download_url": str(asset.get("browser_download_url") or ""),
        }
    return rows


def download_table(release: dict[str, Any], libc: str) -> str:
    rows = artifact_rows(release).get(libc, {})
    body = []
    for arch in ARCHES:
        item = rows.get(arch)
        if item:
            body.append(
                "<tr>"
                f"<td>{escape(arch)}</td>"
                f'<td class="size">{escape(human_size(item.get("size")))}</td>'
                f'<td class="download"><a class="button" href="{escape(item["download_url"])}">download</a></td>'
                "</tr>"
            )
        else:
            body.append(
                "<tr>"
                f"<td>{escape(arch)}</td>"
                '<td class="size muted-cell">missing</td>'
                '<td class="download muted-cell">-</td>'
                "</tr>"
            )
    return f"""
      <table class="matrix">
        <caption>{escape(libc)}</caption>
        <thead>
          <tr>
            <th>arch</th>
            <th>size</th>
            <th>download</th>
          </tr>
        </thead>
        <tbody>
          {''.join(body)}
        </tbody>
      </table>
    """


def page_shell(title: str, body: str, stylesheet_href: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <link rel="stylesheet" href="{stylesheet_href}">
</head>
<body>
{body}
</body>
</html>
"""


def detail_page(release: dict[str, Any], repo_url: str) -> str:
    tag_name = str(release.get("tag_name") or "release")
    tag = escape(tag_name)
    commit = escape(proot_commit(release))
    date = escape(build_date(release))
    release_url = f"{repo_url}/releases/tag/{tag_name}"
    body = f"""
  <main class="shell">
    <section class="hero tight">
      <p class="eyebrow">version</p>
      <h1>{tag}</h1>
      <p class="lede">Direct downloads, build metadata, and a release snapshot for this version.</p>
      <div class="hero-links">
        <a class="button" href="{escape(release_url)}">open on github</a>
        <a href="../index.html">home</a>
        <a href="{repo_url}/releases">all releases</a>
      </div>
      <div class="detail-grid">
        <div class="meta-box"><span>tag</span><strong>{tag}</strong></div>
        <div class="meta-box"><span>proot commit</span><strong>{commit}</strong></div>
        <div class="meta-box"><span>build date</span><strong>{date}</strong></div>
        <div class="meta-box"><span>github</span><strong>release page</strong></div>
      </div>
    </section>
    <section class="detail">
      <div class="section-head">
        <h2>downloads</h2>
      </div>
      <div class="libc-grid">
        {download_table(release, "musl")}
        {download_table(release, "gnu")}
      </div>
    </section>
  </main>
"""
    return page_shell(tag, body, "../style.css")


def version_row_html(item: dict[str, Any], repo_url: str, current: bool = False) -> str:
    tag_name = str(item.get("tag_name") or "release")
    tag = escape(tag_name)
    commit = escape(proot_commit(item))
    date = escape(iso_date(str(item.get("published_at") or item.get("created_at") or "")))
    history_link = f"releases/{slugify(tag_name)}.html"
    github_link = f"{repo_url}/releases/tag/{tag_name}"
    badge = '<span class="current-tag">current</span>' if current else ""
    current_class = " current" if current else ""
    return (
        f'<div class="version-row{current_class}">'
        f"<span><strong><a href=\"{escape(history_link)}\">{tag}</a>{badge}</strong></span>"
        f'<span class="commit">{commit}</span>'
        f'<span class="date">{date}</span>'
        f'<span class="actions"><a class="button" href="{escape(github_link)}">github</a></span>'
        "</div>"
    )


def index_page(releases_list: list[dict[str, Any]], repo_url: str) -> str:
    latest = releases_list[0] if releases_list else None

    if latest:
        latest_tag_name = str(latest.get("tag_name") or "release")
        latest_tag = escape(latest_tag_name)
        latest_commit = escape(proot_commit(latest))
        latest_date = escape(build_date(latest))
        latest_assets = asset_links(latest)
        latest_detail = f'releases/{slugify(latest_tag_name)}.html'
        latest_github = f"{repo_url}/releases/tag/{latest_tag_name}"
    else:
        latest_tag = "release"
        latest_commit = "unknown"
        latest_date = "unknown"
        latest_assets = '<p class="muted">No releases yet.</p>'
        latest_detail = f"{repo_url}/releases"
        latest_github = f"{repo_url}/releases"

    release_rows = "\n".join(
        version_row_html(item, repo_url, current=index == 0)
        for index, item in enumerate(releases_list)
    ) if releases_list else '<p class="muted">No versions yet.</p>'

    body = f"""
  <main class="shell">
    <section class="hero">
      <div class="hero-top">
        <div>
          <p class="eyebrow">proot static binaries</p>
          <h1>{latest_tag}</h1>
          <p class="lede">This project builds static proot binaries from upstream proot commits and publishes them as GitHub Releases. Each release page shows the exact commit, build date, file sizes, and direct downloads.</p>
          <div class="hero-links">
            <a href="{latest_detail}">latest details</a>
            <a class="button" href="{escape(latest_github)}">open release on github</a>
          </div>
          <div class="row">
            {latest_assets}
          </div>
        </div>
        <div class="meta-stack">
          <div class="meta-box"><span>proot commit</span><strong>{latest_commit}</strong></div>
          <div class="meta-box"><span>build date</span><strong>{latest_date}</strong></div>
          <div class="meta-box"><span>about</span><strong>static proot release build</strong></div>
        </div>
      </div>
    </section>
    <section class="panel">
      <div class="section-head">
        <h2>version history</h2>
        <a href="{repo_url}/releases">github releases</a>
      </div>
      <div class="version-list">
        {release_rows}
      </div>
    </section>
  </main>
"""
    return page_shell("proot", body, "./style.css")


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
    changed |= write_if_changed(OUT_DIR / "index.html", index_page(release_list, repo_url))

    for release in release_list:
        tag = str(release.get("tag_name") or "release")
        changed |= write_if_changed(RELEASES_DIR / f"{slugify(tag)}.html", detail_page(release, repo_url))

    print(f"{'Generated' if changed else 'No changes for'} {OUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
