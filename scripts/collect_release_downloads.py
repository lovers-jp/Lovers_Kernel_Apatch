#!/usr/bin/env python3
"""Lovers_Kernel_Apatch: daily GitHub Release download statistics.

Only Python standard library is used. Designed for GitHub Actions and compatible
with the original stats/history/YYYY-MM-DD.csv format already in the repository.
"""

import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "lovers-jp/Lovers_Kernel_Apatch")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
DATE = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")
STATS = Path("stats")
HISTORY = STATS / "history"
COLUMNS = ["date_jst", "tag", "asset_id", "asset_name", "downloads"]
CATEGORY_LABELS = {
    "kernel": "Kernel (boot.img / boot.zip)",
    "susfs": "APatch / SuSFS ZIP",
    "tuner": "Lovers Kernel Tuner APK",
    "other": "その他の添付ファイル",
}


def category(filename):
    """Categorize by filename, independent of Release tag/version."""
    name = filename.casefold()
    if name.endswith(".zip") and ("susfs" in name or "apatch" in name):
        return "susfs"
    if (re.fullmatch(r"(init_)?boot(?:[-_.].*)?\.(?:zip|img)", name)
            or (name.endswith((".zip", ".img")) and "kernel" in name and "tuner" not in name)):
        return "kernel"
    if name.endswith(".apk") and "tuner" in name:
        return "tuner"
    return "other"


def releases_from_github():
    if REPOSITORY != "lovers-jp/Lovers_Kernel_Apatch":
        raise ValueError(f"Incorrect repository: {REPOSITORY}. Expected lovers-jp/Lovers_Kernel_Apatch")
    result = []
    page = 1
    while True:
        url = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=100&page={page}"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "LoversKernelApatch-Stats",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if TOKEN:
            headers["Authorization"] = f"Bearer {TOKEN}"
        try:
            with urlopen(Request(url, headers=headers), timeout=35) as resp:
                batch = json.load(resp)
        except HTTPError as exc:
            raise RuntimeError(f"GitHub API HTTP {exc.code} (page {page})") from exc
        except URLError as exc:
            raise RuntimeError(f"GitHub API network error: {exc}") from exc
        if not isinstance(batch, list):
            raise RuntimeError("GitHub API returned unexpected data")
        result.extend(release for release in batch if not release.get("draft"))
        if len(batch) < 100:
            break
        page += 1
    return result


def read_snapshot(file):
    with file.open("r", newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    return rows


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def counts(rows):
    output = {key: 0 for key in CATEGORY_LABELS}
    for row in rows:
        output[category(row["asset_name"])] += int(row["downloads"])
    return output


def previous_snapshot():
    previous_files = sorted(p for p in HISTORY.glob("????-??-??.csv") if p.stem < DATE)
    if not previous_files:
        return None, {}
    path = previous_files[-1]
    rows = read_snapshot(path)
    return path.stem, {r["asset_id"]: int(r["downloads"]) for r in rows}


def incremental(rows, previous):
    """Downloads gained by files that are still listed, including newly added assets.

    When an asset is removed it disappears from the current API, so this isn't a
    guaranteed historical count for deleted assets.
    """
    return sum(max(0, int(row["downloads"]) - previous.get(row["asset_id"], 0)) for row in rows)


def markdown_escape(value):
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def create_daily_csv():
    """Generate a daily snapshot history, preserving previously recorded dates."""
    daily = []
    previous = None
    for path in sorted(HISTORY.glob("????-??-??.csv")):
        rows = read_snapshot(path)
        sections = counts(rows)
        item = {
            "date_jst": path.stem,
            "all_downloads": sum(sections.values()),
            "kernel_downloads": sections["kernel"],
            "apatch_susfs_downloads": sections["susfs"],
            "tuner_downloads": sections["tuner"],
            "other_downloads": sections["other"],
            "increase_since_previous_record": "" if previous is None else incremental(rows, previous),
        }
        daily.append(item)
        previous = {r["asset_id"]: int(r["downloads"]) for r in rows}
    write_csv(STATS / "daily.csv", daily, list(daily[0]) if daily else [
        "date_jst", "all_downloads", "kernel_downloads", "apatch_susfs_downloads",
        "tuner_downloads", "other_downloads", "increase_since_previous_record",
    ])


def main():
    releases = releases_from_github()
    rows = []
    for release in releases:
        tag = release.get("tag_name") or "(no tag)"
        for asset in release.get("assets", []):
            if asset.get("state") != "uploaded":
                continue
            rows.append({
                "date_jst": DATE,
                "tag": tag,
                "asset_id": str(asset["id"]),
                "asset_name": str(asset["name"]),
                "downloads": int(asset["download_count"]),
            })

    previous_date, old = previous_snapshot()
    write_csv(HISTORY / f"{DATE}.csv", rows, COLUMNS)
    write_csv(STATS / "latest.csv", rows, COLUMNS)
    create_daily_csv()

    sections = counts(rows)
    total = sum(sections.values())
    increase = "—（初回記録）" if previous_date is None else f"+{incremental(rows, old):,}"
    report = [
        "# Lovers_Kernel_Apatch｜Release ダウンロード統計",
        "",
        f"集計日（日本時間）：**{DATE}**",
        "",
        f"**全添付ファイルの累計ダウンロード数：{total:,} 回**",
        "",
        "| 種類 | 累計DL数 |",
        "|---|---:|",
    ]
    for key, label in CATEGORY_LABELS.items():
        report.append(f"| {label} | {sections[key]:,} |")
    report.extend([
        "",
        f"集計対象：**{len(rows)} ファイル** ／ 前回記録日：**{previous_date or 'なし'}**",
        f"前回記録からの増加：**{increase}**",
        "",
        "## リリース・ファイル別内訳",
        "",
        "| リリース | 種類 | ファイル | 累計DL数 | 前回記録比 |",
        "|---|---|---|---:|---:|",
    ])
    for row in rows:
        old_count = old.get(row["asset_id"])
        delta = "—" if old_count is None else f"+{max(0, row['downloads'] - old_count):,}"
        report.append(
            f"| {markdown_escape(row['tag'])} | {CATEGORY_LABELS[category(row['asset_name'])]} | "
            f"{markdown_escape(row['asset_name'])} | {row['downloads']:,} | {delta} |"
        )
    if not rows:
        report.append("| — | — | 公開されたリリース添付ファイルなし | 0 | — |")
    report.extend([
        "",
        "## データファイル",
        "",
        "- [`latest.csv`](latest.csv)：現在のファイル別累計ダウンロード数",
        "- [`daily.csv`](daily.csv)：日別スナップショットと前回記録からの増加数",
        "- [`history/`](history/)：過去の記録（以前のCSVも維持）",
        "",
        "※ GitHub Releases APIの `download_count` による延べダウンロード数です（人数ではありません）。",
        "",
        "※ GitHubが自動生成するSource codeのZIP/TARは集計されません。",
        "",
        "※ 日別増加はスナップショット間の差分であり、正確なダウンロード日時ではありません。",
        "",
        "※ 削除した添付ファイルはAPIの現在の累計に含まれなくなります。履歴CSVは保持されます。",
        "",
    ])
    (STATS / "README.md").write_text("\n".join(report), encoding="utf-8")
    print(f"Repository: {REPOSITORY}")
    print(f"Release assets: {len(rows)}; total downloads: {total}")
    print(f"Recorded: {STATS / 'README.md'}, latest.csv, daily.csv, history/{DATE}.csv")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
