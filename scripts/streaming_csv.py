#!/usr/bin/env python3
"""Phase 3: turn a streaming list into import-ready playlist CSVs.

Input is a CSV with title and artist columns (cull_sheet.py writes one,
streaming_list.csv, from the files' real tags). An optional `playlist`
column names the playlist for each row; fill it in by hand, or use
--by-genre to sort by the genre tag into a few broad playlists.

Output is one CSV per playlist in the format Soundiiz imports:
  title,artist,album,isrc,platform,trackId,duration,addedDate,url
Matching runs on title and artist; the other columns stay blank.
  --txt                   also write each playlist as a plain text list,
                          one "Artist - Title" per line, which any import
                          service (TuneMyMusic, Soundiiz...) reads
  --max-per-playlist N    split playlists longer than N tracks into
                          numbered parts ("Online Rock (1 of 3)"), for
                          free plans that cap playlist size

Cleanups that fix most failed matches:
  --strip-versions        drop "(Live)", "(Acoustic)", "(Remix)", "- 2011
                          Remaster" and similar from titles
  --blank-bootleg-albums  blank album tags that are show dates or carry a
                          "| Source" marker; a bootleg album never matches
Rows that look like live bootlegs are listed as likely missing from
streaming: those usually belong in the local library instead.

Usage:
  streaming_csv.py streaming_list.csv --out-dir playlists/ [--by-genre]
                   [--prefix "Online "] [--strip-versions] [--blank-bootleg-albums]
                   [--txt] [--max-per-playlist N]
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

SOUNDIIZ = ["title", "artist", "album", "isrc", "platform", "trackId", "duration", "addedDate", "url"]
BOOTLEG_ALBUM = re.compile(r"^\s*\d{4}[.\-/_ ]\d{1,2}[.\-/_ ]\d{1,2}\b|\|\s*\w|\b(sbd|aud|bootleg|soundboard)\b", re.I)
GENRE_BUCKETS = [
    ("Rap & Hip-Hop", r"rap|hip.?hop|trap|grime"),
    ("Electronic & Dance", r"electr|dance|house|techno|trance|edm|dubstep|drum|ambient|idm"),
    ("Soul, Funk & R&B", r"soul|funk|r&b|rnb|rhythm|motown|disco|gospel"),
    ("Classic Rock", r"classic rock|blues|southern|psychedel|hard rock|jam"),
    ("Pop, Rock & Alternative", r"pop|rock|alt|indie|punk|grunge|metal|new wave|singer"),
    ("Country & Folk", r"country|folk|americana|bluegrass"),
    ("Jazz", r"jazz|swing|bebop"),
    ("Classical", r"classical|symphon|opera|baroque"),
]


def bucket(genre: str) -> str:
    for name, pat in GENRE_BUCKETS:
        if genre and re.search(pat, genre, re.I):
            return name
    return "Other"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("list", type=Path)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--by-genre", action="store_true")
    ap.add_argument("--default-playlist", default="Streaming Import")
    ap.add_argument("--prefix", default="", help='prefix for playlist names, e.g. "Online "')
    ap.add_argument("--strip-versions", action="store_true")
    ap.add_argument("--blank-bootleg-albums", action="store_true")
    ap.add_argument("--txt", action="store_true", help='also write "Artist - Title" text lists')
    ap.add_argument("--max-per-playlist", type=int, default=0,
                    help="split playlists longer than this into numbered parts")
    args = ap.parse_args()

    rows = c.read_csv(args.list)
    if not rows or not {"title", "artist"} <= set(rows[0]):
        sys.exit("List needs title and artist columns.")
    playlists: dict[str, list[dict]] = defaultdict(list)
    bootlegs, skipped = [], 0
    for r in rows:
        title, artist, album = r["title"].strip(), r["artist"].strip(), r.get("album", "").strip()
        if not title or not artist:
            skipped += 1
            continue
        if album and BOOTLEG_ALBUM.search(album):
            bootlegs.append(f"{artist} - {title} [{album}]")
            if args.blank_bootleg_albums:
                album = ""
        if args.strip_versions:
            title = c.VERSION_MARKERS.sub("", title).strip() or title
        name = r.get("playlist", "").strip() or (bucket(r.get("genre", "")) if args.by_genre
                                                 else args.default_playlist)
        playlists[args.prefix + name].append({"title": title, "artist": artist, "album": album})
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, items in sorted(playlists.items()):
        n = args.max_per_playlist
        parts = [items[i:i + n] for i in range(0, len(items), n)] if n > 0 else [items]
        for i, part in enumerate(parts, 1):
            pname = f"{name} ({i} of {len(parts)})" if len(parts) > 1 else name
            safe = re.sub(r'[\\/:*?"<>|]+', "-", pname).strip()
            c.write_csv(args.out_dir / f"{safe}.csv", part, SOUNDIIZ)
            written = f"{safe}.csv"
            if args.txt:
                with open(args.out_dir / f"{safe}.txt", "w", encoding="utf-8",
                          errors="surrogateescape") as f:
                    f.writelines(f"{t['artist']} - {t['title']}\n" for t in part)
                written += " and .txt"
            print(f"{pname}: {len(part)} tracks -> {written}")
    if skipped:
        print(f"{skipped} rows skipped for missing title or artist: fix their tags first")
    if bootlegs:
        print(f"{len(bootlegs)} look like live bootlegs and probably aren't on streaming "
              "(consider keeping them local):")
        for b in bootlegs[:20]:
            print(f"  {b}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
