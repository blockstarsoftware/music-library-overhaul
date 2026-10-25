#!/usr/bin/env python3
"""Phase 4.1 and Phase 8: what each file really is, and which albums lie.

Read-only. ffprobes every audio file and classifies its codec:
  lossless  ALAC, FLAC, etc.
  pcm       uncompressed WAV/AIFF: already lossless, worth converting to ALAC
            or FLAC for half the size and working tags (convert_lossless.py)
  lossy     AAC, MP3, etc.: cannot be converted up, only re-acquired
  drm       FairPlay .m4p: locked; only re-purchasing frees it
Both ALAC and AAC use .m4a, so the extension tells you nothing.

Each folder is then judged as an album. A folder with lossless AND lossy
tracks is "mixed": it looks lossless but isn't (false-lossless). Usually the
lossy track is a leftover single duplicating a lossless album track; run
find_duplicates.py mixed to check.

Usage:
  audit_codecs.py LIBRARY [--files files.csv] [--albums albums.csv]
                          [--lossy lossy.csv] [--jobs N]
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

ALBUM_FIELDS = ["folder", "verdict", "tracks", "lossless", "pcm", "lossy", "drm",
                "unknown", "lossy_tracks"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("library", type=Path)
    ap.add_argument("--files", type=Path, help="per-file CSV")
    ap.add_argument("--albums", type=Path, help="per-folder CSV")
    ap.add_argument("--lossy", type=Path, help="CSV of every lossy file (re-acquire list)")
    ap.add_argument("--jobs", type=int, default=8)
    args = ap.parse_args()
    c.require_tools()

    rows = c.catalog(args.library, args.jobs)

    by_folder: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_folder[str(c.album_unit(r["path"]))].append(r)
    albums = []
    for folder, rs in sorted(by_folder.items()):
        n = defaultdict(int)
        for r in rs:
            n[r["class"]] += 1
        lossless = n["lossless"] + n["pcm"]
        lossy = n["lossy"] + n["drm"]
        verdict = ("mixed" if lossless and lossy else "lossless" if lossless and not lossy
                   else "lossy" if lossy else "unknown")
        albums.append({
            "folder": folder, "verdict": verdict, "tracks": len(rs),
            "lossless": n["lossless"], "pcm": n["pcm"], "lossy": n["lossy"], "drm": n["drm"],
            "unknown": n["unknown"] + n["unreadable"] + n["none"],
            "lossy_tracks": " | ".join(Path(r["path"]).name for r in rs
                                       if r["class"] in ("lossy", "drm")) if verdict == "mixed" else "",
        })

    if args.files:
        c.write_csv(args.files, rows, c.CATALOG_FIELDS)
    if args.albums:
        c.write_csv(args.albums, albums, ALBUM_FIELDS)
    if args.lossy:
        c.write_csv(args.lossy, [r for r in rows if r["class"] == "lossy"], c.CATALOG_FIELDS)

    total = defaultdict(int)
    for r in rows:
        total[r["class"]] += 1
    print(f"{len(rows)} audio files under {args.library}")
    for k in ("lossless", "pcm", "lossy", "drm", "unknown", "unreadable", "none"):
        if total[k]:
            print(f"  {k}: {total[k]} ({100 * total[k] / max(1, len(rows)):.0f}%)")
    mixed = [a for a in albums if a["verdict"] == "mixed"]
    print(f"{len(albums)} folders: {sum(a['verdict'] == 'lossless' for a in albums)} lossless, "
          f"{sum(a['verdict'] == 'lossy' for a in albums)} lossy, {len(mixed)} mixed (false-lossless)")
    for a in mixed[:40]:
        print(f"  MIXED {a['folder']}  lossy: {a['lossy_tracks']}")
    if len(mixed) > 40:
        print(f"  ... {len(mixed) - 40} more (use --albums)")
    if total["pcm"]:
        print(f"{total['pcm']} PCM files can become ALAC/FLAC with no quality change: convert_lossless.py")
    if total["drm"]:
        print(f"{total['drm']} DRM files are locked: flag for re-purchase, don't try to fix")
    return 0


if __name__ == "__main__":
    sys.exit(main())
