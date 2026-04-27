#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
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
  width: min(1260px, calc(100% - 1rem));
  margin: 0 auto;
  padding: 0.5rem 0 1rem;
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
  padding: 1.25rem;
  margin-bottom: 0.5rem;
}

.hero-top {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(280px, 0.95fr);
  gap: 1rem;
  align-items: start;
}

.hero.tight {
  margin-top: 0.5rem;
}

.panel,
.detail {
  padding: 0.95rem 1rem;
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
  grid-template-columns: 1.1fr 0.9fr 0.9fr;
  gap: 0.75rem;
  align-items: center;
  padding: 0.55rem 0;
  border-top: 1px solid var(--line);
  font-size: 0.95rem;
}

.version-row:first-child {
  border-top: 0;
}

.version-row span:last-child {
  justify-self: end;
}

.detail {
  display: grid;
  gap: 1rem;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.6rem;
}

.downloads {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
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
}

@media (max-width: 720px) {
  .shell {
    width: min(100% - 0.5rem, 100%);
    padding-top: 0.25rem;
  }

  .hero,
  .panel,
  .detail {
    padding: 0.85rem;
  }

  h1 {
    font-size: clamp(2.3rem, 14vw, 3.4rem);
  }

  .version-row {
    grid-template-columns: 1fr;
    gap: 0.15rem;
  }

  .version-row span:last-child {
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


def github_api(path: str) -> Any:
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Accept": "application/vnd.github+json",
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
        raise RuntimeError(f"GitHub API request failed for {path}: {exc.code} {exc.reason}\n{body}") from exc


def releases() -> list[dict[str, Any]]:
    data = github_api(f"/repos/{repo_slug()}/releases?per_page=100")
    if not isinstance(data, list):
        raise RuntimeError("Unexpected GitHub releases payload")
    return [item for item in data if not item.get("draft")]


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


def slugify(tag: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", tag).strip("-")
    return slug.lower() or "release"


def body_value(release: dict[str, Any], key: str) -> str | None:
    body = str(release.get("body") or "")
    match = re.search(rf"^{re.escape(key)}:\s*(.+)$", body, re.MULTILINE)
    return match.group(1).strip() if match else None


def proot_commit(release: dict[str, Any]) -> str:
    value = body_value(release, "proot")
    if value:
        return value
    target = str(release.get("target_commitish") or "")
    return target if re.fullmatch(r"[0-9a-fA-F]{7,40}", target) else "unknown"


def build_date(release: dict[str, Any]) -> str:
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
    tag = escape(str(release.get("tag_name") or "release"))
    commit = escape(proot_commit(release))
    date = escape(build_date(release))
    body = f"""
  <main class="shell">
    <section class="hero tight">
      <p class="eyebrow">version</p>
      <h1>{tag}</h1>
      <p class="lede">Direct downloads and a compact build summary for this version.</p>
      <div class="detail-grid">
        <div class="meta-box"><span>proot commit</span><strong>{commit}</strong></div>
        <div class="meta-box"><span>build date</span><strong>{date}</strong></div>
        <div class="meta-box"><span>tag</span><strong>{tag}</strong></div>
      </div>
      <div class="meta-links">
        <a href="../index.html">home</a>
        <a href="{repo_url}/releases">github releases</a>
      </div>
    </section>
    <section class="detail">
      <div class="section-head">
        <h2>downloads</h2>
      </div>
      <div class="downloads">
        {asset_links(release)}
      </div>
    </section>
  </main>
"""
    return page_shell(tag, body, "../style.css")


def index_page(releases_list: list[dict[str, Any]], repo_url: str) -> str:
    latest = releases_list[0] if releases_list else None
    older = releases_list[1:] if len(releases_list) > 1 else []

    if latest:
        latest_tag = escape(str(latest.get("tag_name") or "release"))
        latest_commit = escape(proot_commit(latest))
        latest_date = escape(build_date(latest))
        latest_assets = asset_links(latest)
        latest_detail = f'releases/{slugify(str(latest.get("tag_name") or "release"))}.html'
    else:
        latest_tag = "release"
        latest_commit = "unknown"
        latest_date = "unknown"
        latest_assets = '<p class="muted">No releases yet.</p>'
        latest_detail = f"{repo_url}/releases"

    older_rows = (
        "\n".join(
            f'<a class="version-row" href="releases/{slugify(str(item.get("tag_name") or "release"))}.html">'
            f'<span>{escape(str(item.get("tag_name") or "release"))}</span>'
            f'<span>{escape(proot_commit(item))}</span>'
            f'<span>{escape(iso_date(str(item.get("published_at") or item.get("created_at") or "")))}</span>'
            f"</a>"
            for item in older
        )
        if older
        else '<p class="muted">No older versions.</p>'
    )

    body = f"""
  <main class="shell">
    <section class="hero">
      <div class="hero-top">
        <div>
          <p class="eyebrow">proot static binaries</p>
          <h1>{latest_tag}</h1>
          <p class="lede">This site reads GitHub Releases and turns each build into direct downloads. Open a version page for the exact commit and build date.</p>
          <div class="hero-links">
            <a href="{latest_detail}">latest details</a>
            <a href="{repo_url}/releases">all releases</a>
          </div>
          <div class="row">
            {latest_assets}
          </div>
        </div>
        <div class="meta-stack">
          <div class="meta-box"><span>proot commit</span><strong>{latest_commit}</strong></div>
          <div class="meta-box"><span>build date</span><strong>{latest_date}</strong></div>
        </div>
      </div>
    </section>
    <section class="panel">
      <div class="section-head">
        <h2>older versions</h2>
        <a href="{repo_url}/releases">github</a>
      </div>
      <div class="version-list">
        {older_rows}
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
