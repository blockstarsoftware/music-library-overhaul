#!/usr/bin/env python3
"""Recoverable removal: move files to a trash folder by reason, or put them back.

Nothing in this toolkit hard-deletes. Removals go to
TRASH/<reason>/<path relative to the library>, and every move is recorded in
TRASH/_manifest.jsonl, which `restore` reads to undo it.

Usage:
  trash.py move LIST.csv --library LIB --trash TRASH [--reason R] [--apply]
      LIST.csv needs a `path` column; an optional `reason` column overrides
      --reason per row (e.g. "Deleted (discarded)", "Lossy duplicates").
  trash.py restore --trash TRASH [--match TEXT] [--apply]
      Move trashed files back to where they came from. --match limits it to
      originals whose path contains TEXT.
  trash.py list --trash TRASH
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402


def cmd_move(args) -> int:
    rows = c.read_csv(args.list)
    if not rows or "path" not in rows[0]:
        sys.exit("List needs a 'path' column.")
    moved = missing = 0
    for r in rows:
        p = Path(r["path"]).expanduser()
        reason = (r.get("reason") or args.reason).strip()
        if not p.exists():
            print(f"MISSING: {p}")
            missing += 1
            continue
        if args.apply:
            try:
                dest = c.move_to_trash(p, args.library, args.trash, reason)
            except OSError as e:
                print(f"FAILED (left in place): {p}  {e}")
                missing += 1
                continue
            print(f"moved: {p}\n    -> {dest}")
        else:
            print(f"would move ({reason}): {p}")
        moved += 1
    verb = "Moved" if args.apply else "Would move"
    print(f"{verb} {moved} files; {missing} missing or failed.")
    if not args.apply:
        print("Dry run. Add --apply to move.")
    return 1 if missing else 0


def cmd_restore(args) -> int:
    entries = c.read_manifest(args.trash)
    restored = skipped = 0
    for e in entries:
        if args.match and args.match not in e["original"]:
            continue
        src, dst = Path(e["trashed"]), Path(e["original"])
        if not (src.exists() or src.is_symlink()):
            continue  # already restored or removed by hand
        if dst.exists() or dst.is_symlink():
            print(f"SKIP (something is already at the original path): {dst}")
            skipped += 1
            continue
        if args.apply:
            try:
                c.safe_move(src, dst)
            except OSError as e:
                print(f"FAILED: {dst}  {e}")
                skipped += 1
                continue
            print(f"restored: {dst}")
        else:
            print(f"would restore: {dst}")
        restored += 1
    verb = "Restored" if args.apply else "Would restore"
    print(f"{verb} {restored} files; {skipped} skipped.")
    if not args.apply:
        print("Dry run. Add --apply to restore.")
    return 0


def cmd_list(args) -> int:
    entries = [e for e in c.read_manifest(args.trash) if Path(e["trashed"]).exists()]
    by_reason: dict[str, int] = {}
    for e in entries:
        by_reason[e["reason"]] = by_reason.get(e["reason"], 0) + 1
    print(f"{len(entries)} files in {args.trash}")
    for k, v in sorted(by_reason.items()):
        print(f"  {k}: {v}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("move")
    m.add_argument("list", type=Path)
    m.add_argument("--library", type=Path, required=True)
    m.add_argument("--trash", type=Path, required=True)
    m.add_argument("--reason", default="Removed")
    m.add_argument("--apply", action="store_true")
    r = sub.add_parser("restore")
    r.add_argument("--trash", type=Path, required=True)
    r.add_argument("--match")
    r.add_argument("--apply", action="store_true")
    l = sub.add_parser("list")
    l.add_argument("--trash", type=Path, required=True)
    args = ap.parse_args()
    return {"move": cmd_move, "restore": cmd_restore, "list": cmd_list}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
