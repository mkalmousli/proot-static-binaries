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
SITE_DIR = ROOT / "site"
RELEASES_DIR = SITE_DIR / "releases"
INDEX_PATH = SITE_DIR / "index.html"
ASSET_PREFIX = "proot-"


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


def time_value(value: str | None) -> str:
    if not value:
        return "unknown"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def slugify(tag: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", tag).strip("-")
    return slug or "release"


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
    return body_value(release, "Build Date") or time_value(str(release.get("published_at") or release.get("created_at") or ""))


def asset_items(release: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        asset
        for asset in release.get("assets", [])
        if isinstance(asset, dict) and str(asset.get("name", "")).startswith(ASSET_PREFIX)
    ]


def asset_label(name: str) -> str:
    tail = name.removeprefix(ASSET_PREFIX)
    return " / ".join(tail.split("-"))


def asset_links(release: dict[str, Any]) -> str:
    assets = asset_items(release)
    if not assets:
        return '<p class="muted">No assets.</p>'
    return "".join(
        f'<a class="pill" href="{escape(str(asset["browser_download_url"]))}">{escape(asset_label(str(asset["name"])))}</a>'
        for asset in assets
    )


def detail_page(release: dict[str, Any], repo_url: str) -> str:
    tag = escape(str(release.get("tag_name") or "release"))
    commit = escape(proot_commit(release))
    date = escape(build_date(release))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{tag} - proot</title>
  <link rel="stylesheet" href="../style.css">
</head>
<body>
  <main class="page">
    <header class="hero tight">
      <p class="eyebrow">release</p>
      <h1>{tag}</h1>
      <p class="meta">proot {commit}</p>
      <p class="meta">{date}</p>
      <div class="row">
        {asset_links(release)}
      </div>
      <p class="meta"><a href="../index.html">back</a> <a href="{repo_url}/releases">github</a></p>
    </header>
  </main>
</body>
</html>
"""


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
        latest_assets = '<p class="muted">No releases.</p>'
        latest_detail = f"{repo_url}/releases"

    if older:
        older_rows = "\n".join(
            f'<a class="version-row" href="releases/{slugify(str(item.get("tag_name") or "release"))}.html">'
            f'<span>{escape(str(item.get("tag_name") or "release"))}</span>'
            f'<span>{escape(proot_commit(item))}</span>'
            f'<span>{escape(iso_date(str(item.get("published_at") or item.get("created_at") or "")))}</span>'
            f"</a>"
            for item in older
        )
    else:
        older_rows = '<p class="muted">No older versions.</p>'

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>proot</title>
  <link rel="stylesheet" href="./style.css">
</head>
<body>
  <main class="page">
    <header class="hero">
      <p class="eyebrow">proot static binaries</p>
      <h1>{latest_tag}</h1>
      <p class="meta">{latest_commit}</p>
      <p class="meta">{latest_date}</p>
      <div class="row">
        {latest_assets}
      </div>
      <p class="meta"><a href="{latest_detail}">details</a></p>
    </header>
    <section class="panel">
      <div class="section-head">
        <h2>older versions</h2>
        <a href="{repo_url}/releases">all releases</a>
      </div>
      <div class="version-list">
        {older_rows}
      </div>
    </section>
  </main>
</body>
</html>
"""


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
    changed = write_if_changed(INDEX_PATH, index_page(release_list, repo_url))

    for release in release_list:
        tag = str(release.get("tag_name") or "release")
        page = RELEASES_DIR / f"{slugify(tag)}.html"
        changed |= write_if_changed(page, detail_page(release, repo_url))

    print(f"{'Generated' if changed else 'No changes for'} site")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
