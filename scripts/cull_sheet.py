#!/usr/bin/env python3
"""Phase 2: decide the long tail one artist at a time, in a spreadsheet.

  cull_sheet.py build TIER --sheet cull.csv [--force]
      One row per top-level artist folder in TIER (artist, track count, size,
      albums, sample titles) with an empty `action` column. Compilations are
      detected (an album tag shared by several artist folders, a compilation
      flag, or "Various Artists"; never a generic name like "Greatest Hits")
      and get one row for the whole comp, so nobody decides a comp track by
      track. Open the CSV in Numbers or Excel and fill the action column with
      exactly one of:
          K  keep          stays local
          D  delete        to the trash ("Deleted (discarded)")
          S  streaming     to the trash ("Streaming-listed") and logged for a
                           streaming playlist (streaming_csv.py)
          U  upgrade       stays local, logged to re-acquire in lossless
          B  both          stays local AND is logged for the streaming
                           playlists, so the streaming side is complete
      1-5 and the full words (keep, delete, streaming, upgrade, both) work
      too; anything else is refused. Blank rows are left undecided. build won't
      overwrite a sheet that already holds decisions unless you pass --force.

  cull_sheet.py apply cull.csv --trash TRASH --lists DIR [--apply]
      Checks every row first and stops before touching anything if one is
      unreadable or doesn't match the files the sheet was built from. Then
      writes DIR/streaming_list.csv and DIR/upgrade_wanted.csv (from the
      files' real tags) and DIR/decisions_log.csv, and only then moves files.
      The dry run (default) prints how each row was read.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

ACTIONS = {"k": "keep", "1": "keep", "keep": "keep",
           "d": "delete", "2": "delete", "delete": "delete",
           "s": "streaming", "3": "streaming", "streaming": "streaming", "stream": "streaming",
           "u": "upgrade", "4": "upgrade", "upgrade": "upgrade",
           "b": "both", "5": "both", "both": "both"}
SHEET_FIELDS = ["id", "kind", "name", "tracks", "size_mb", "albums", "sample_titles", "action"]
STREAM_FIELDS = ["title", "artist", "album", "genre", "seconds", "playlist", "local", "path"]
UPGRADE_FIELDS = ["artist", "album", "title", "codec", "bitrate_kbps", "path"]
LOG_FIELDS = ["time", "id", "kind", "name", "tracks", "action"]
REASONS = {"delete": "Deleted (discarded)", "streaming": "Streaming-listed (removed from library)"}
GENERIC_ALBUMS = {c.title_key(a) for a in (
    "Greatest Hits", "The Best Of", "Best Of", "The Very Best Of", "Hits", "Singles", "Live",
    "Unknown Album", "Anthology", "The Collection", "Collection", "Essentials", "The Essential",
    "Gold", "Untitled", "Demo", "Demos", "Single", "EP", "Untitled Album", "Album")}


def sidecar(sheet: Path) -> Path:
    return sheet.with_suffix(".files.json")


def norm_id(value: str) -> str:
    """Row ids survive Excel turning '0007' into '7'."""
    v = value.strip()
    return f"{int(v):04d}" if v.isdigit() else v


def cmd_build(args) -> int:
    if args.sheet.exists() and not args.force:
        if any(r.get("action", "").strip() for r in c.read_csv(args.sheet)):
            sys.exit(f"{args.sheet} already holds decisions. Use another name, or --force.")
    tier = Path(c.ff_path(args.tier))
    rows = c.catalog(tier, args.jobs)
    by_folder: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        rel = Path(c.ff_path(r["path"])).relative_to(tier)
        top = rel.parts[0] if len(rel.parts) > 1 else "(loose files)"
        by_folder[top].append(r)

    album_folders: dict[str, set[str]] = defaultdict(set)
    album_name: dict[str, str] = {}
    for folder, rs in by_folder.items():
        for r in rs:
            k = c.title_key(r["album"])
            if k:
                album_folders[k].add(folder)
                album_name.setdefault(k, r["album"])
    # A compilation: an album shared by several artist folders, flagged as a
    # compilation, or credited to Various Artists. Never a name many unrelated
    # artists use ("Greatest Hits"): a whole row of different artists' albums
    # would then be one decision.
    comp_keys = {k for k, fs in album_folders.items() if len(fs) >= 2}
    for r in rows:
        k = c.title_key(r["album"])
        if k and (c.artist_key(r["album_artist"]) in ("variousartists", "various", "va")
                  or r.get("compilation") == "1"):
            comp_keys.add(k)
    comp_keys -= GENERIC_ALBUMS

    sheet = []
    comps: dict[str, list[dict]] = defaultdict(list)
    for folder in sorted(by_folder, key=str.lower):
        rest = []
        for r in by_folder[folder]:
            k = c.title_key(r["album"])
            (comps[k] if k in comp_keys else rest).append(r)
        if rest:
            sheet.append(("artist", folder, rest))
    for k in sorted(comps, key=lambda k: album_name[k].lower()):
        sheet.append(("compilation", album_name[k], comps[k]))

    out, files = [], {}
    for i, (kind, name, rs) in enumerate(sheet, 1):
        rid = f"{i:04d}"
        files[rid] = {"name": name, "paths": [r["path"] for r in rs]}
        albums = Counter(r["album"] for r in rs if r["album"])
        out.append({
            "id": rid, "kind": kind, "name": name, "tracks": len(rs),
            "size_mb": round(sum(int(r.get("size_bytes") or 0) for r in rs) / 1e6, 1),
            "albums": " | ".join(a for a, _ in albums.most_common(3)),
            "sample_titles": " | ".join((r["title"] or Path(r["path"]).stem) for r in rs[:3]),
            "action": "",
        })
    c.write_csv(args.sheet, out, SHEET_FIELDS)
    sidecar(args.sheet).write_text(json.dumps({"tier": str(tier), "files": files}, indent=1,
                                              ensure_ascii=False), encoding="utf-8",
                                   errors="surrogateescape")
    singles = sum(1 for r in out if r["kind"] == "artist" and r["tracks"] == 1)
    print(f"{len(out)} rows ({len(comps)} compilations, {singles} single-track artists) -> {args.sheet}")
    print("Fill the action column with K, D, S, U or B, then run: cull_sheet.py apply")
    return 0


def append_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8", errors="surrogateescape") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def cmd_apply(args) -> int:
    meta = json.loads(sidecar(args.sheet).read_text(encoding="utf-8", errors="surrogateescape"))
    tier, files = Path(meta["tier"]), meta["files"]
    sheet = c.read_csv(args.sheet)

    # 1. Read and check every row before anything is touched.
    plan, problems, undecided = [], [], 0
    for row in sheet:
        raw = row.get("action", "").strip().lower()
        if not raw:
            undecided += 1
            continue
        rid = norm_id(row.get("id", ""))
        action = ACTIONS.get(raw)
        entry = files.get(rid)
        if not action:
            problems.append(f"row {row.get('id')} ({row.get('name')}): {raw!r} is not K, D, S, U or B")
        elif entry is None or entry["name"] != row.get("name"):
            problems.append(f"row {row.get('id')} ({row.get('name')}): doesn't match the files this "
                            "sheet was built from; rebuild the sheet")
        else:
            paths = [Path(p) for p in entry["paths"] if os.path.exists(p)]
            plan.append((rid, row, action, paths))
    if problems:
        print("Nothing was changed. Fix these rows first:\n  " + "\n  ".join(problems))
        return 1

    counts = Counter()
    for rid, row, action, paths in plan:
        counts[action] += len(paths)
        if not args.apply:
            print(f"  {row['name']}: {action} ({len(paths)} tracks)")
    summary = ", ".join(f"{k} {v}" for k, v in counts.items())
    print(f"Decisions (tracks): {summary or 'none'}; {undecided} rows undecided")
    if not args.apply:
        print("Dry run. Add --apply to write the lists and move files.")
        return 0

    # 2. Write every list from the files' real tags, while they are still in place.
    stream_rows = [dict(c.describe_file(p), local="yes" if a == "both" else "no")
                   for _, _, a, ps in plan if a in ("streaming", "both") for p in ps]
    upgrade_rows = [c.describe_file(p) for _, _, a, ps in plan if a == "upgrade" for p in ps]
    log_rows = [{"time": c.now_iso(), "id": rid, "kind": row["kind"], "name": row["name"],
                 "tracks": len(ps), "action": a} for rid, row, a, ps in plan]
    args.lists.mkdir(parents=True, exist_ok=True)
    append_csv(args.lists / "streaming_list.csv", stream_rows, STREAM_FIELDS)
    append_csv(args.lists / "upgrade_wanted.csv", upgrade_rows, UPGRADE_FIELDS)
    append_csv(args.lists / "decisions_log.csv", log_rows, LOG_FIELDS)

    # 3. Only now move files.
    failed = []
    for _, _, action, paths in plan:
        if action not in REASONS:
            continue
        for p in paths:
            try:
                c.move_to_trash(p, tier, args.trash, REASONS[action])
            except OSError as e:
                failed.append(f"{p}: {e}")
    print(f"Lists updated in {args.lists}; removals in {args.trash}")
    if failed:
        print(f"{len(failed)} files could not be moved (left in place):\n  " + "\n  ".join(failed[:20]))
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("tier", type=Path)
    b.add_argument("--sheet", type=Path, required=True)
    b.add_argument("--force", action="store_true", help="overwrite a sheet that holds decisions")
    b.add_argument("--jobs", type=int, default=8)
    a = sub.add_parser("apply")
    a.add_argument("sheet", type=Path)
    a.add_argument("--trash", type=Path, required=True)
    a.add_argument("--lists", type=Path, required=True)
    a.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    c.require_tools()
    return cmd_build(args) if args.cmd == "build" else cmd_apply(args)


if __name__ == "__main__":
    sys.exit(main())
