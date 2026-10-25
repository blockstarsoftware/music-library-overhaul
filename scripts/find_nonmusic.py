#!/usr/bin/env python3
"""Phase 5: find spoken word and other non-music hiding in the library.

Read-only. Scores every audio file on signals that it isn't music:
  - genre tag of Speech, Spoken, Podcast, Audiobook, Lecture, Talk, Comedy...
  - words like lecture, talk, sermon, interview, podcast, episode, chapter,
    audiobook, meditation, dharma in the artist, album, title or path
  - very long duration (default over 20 minutes)
  - an artist on your own list (--artists FILE, one name per line)
and damps the usual false positives: long DJ mixes, classical works and prog
suites are music (genre Classical/Electronic/Dance/Prog, or 'mix', 'symphony',
'concerto', 'suite', 'live at' in the tags).

Results are grouped by folder, since spoken word usually comes in folders.
Confirm each folder with the user, then move confirmed ones out of the music
library (they are not junk: put them in their own folder, not the trash).

Usage:
  find_nonmusic.py LIBRARY [--out candidates.csv] [--minutes 20] [--artists FILE]
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

SPOKEN_GENRES = re.compile(r"speech|spoken|podcast|audiobook|audio book|lecture|talk|"
                           r"comedy|books? ?&? ?spoken|religion|education|meditation|news", re.I)
SPOKEN_WORDS = re.compile(r"\b(lectures?|talks?|sermons?|interviews?|podcasts?|episodes?|"
                          r"ep\.? ?\d+|chapters?|audiobooks?|meditations?|guided|dharma|"
                          r"teachings?|seminars?|workshops?|q ?& ?a|keynotes?|voice ?memos?|"
                          r"recording \d+)\b", re.I)
MUSIC_GENRES = re.compile(r"classical|symphon|opera|electronic|dance|house|techno|trance|"
                          r"ambient|prog|jazz|jam|soundtrack", re.I)
MUSIC_WORDS = re.compile(r"\b(mix|mixed|dj|symphony|concerto|sonata|suite|movement|"
                         r"opus|op\. ?\d+|live at|set)\b", re.I)
FIELDS = ["folder", "score", "files", "minutes_total", "signals", "sample"]


def score(r: dict, minutes: float, artists: set[str]) -> tuple[int, list[str]]:
    s, why = 0, []
    text = " ".join([r.get("artist", ""), r.get("album", ""), r.get("title", ""),
                     str(Path(r["path"]).relative_to(Path(r["path"]).anchor))])
    genre = r.get("genre", "")
    if genre and SPOKEN_GENRES.search(genre):
        s += 3
        why.append(f"genre {genre}")
    m = SPOKEN_WORDS.search(text)
    if m:
        s += 2
        why.append(f"word '{m.group(0)}'")
    secs = c.seconds(r) or 0
    if secs > minutes * 60:
        s += 2
        why.append(f"{secs / 60:.0f} min")
    if artists and c.artist_key(r.get("artist", "")) in artists:
        s += 3
        why.append("listed artist")
    if s and (MUSIC_GENRES.search(genre) or MUSIC_WORDS.search(text)):
        s -= 2
        why.append("music signal (mix/classical/suite): check")
    return s, why


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("library", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--minutes", type=float, default=20.0)
    ap.add_argument("--artists", type=Path, help="file of known spoken-word artists, one per line")
    ap.add_argument("--min-score", type=int, default=2)
    ap.add_argument("--jobs", type=int, default=8)
    args = ap.parse_args()
    c.require_tools()

    artists = set()
    if args.artists:
        artists = {c.artist_key(l) for l in args.artists.read_text().splitlines() if l.strip()}
    rows = c.catalog(args.library, args.jobs)
    folders: dict[str, dict] = defaultdict(lambda: {"score": 0, "files": 0, "secs": 0.0,
                                                     "signals": set(), "sample": ""})
    for r in rows:
        s, why = score(r, args.minutes, artists)
        if s < args.min_score:
            continue
        f = folders[str(c.album_unit(r["path"]))]
        f["score"] = max(f["score"], s)
        f["files"] += 1
        f["secs"] += c.seconds(r) or 0
        f["signals"].update(why)
        f["sample"] = f["sample"] or Path(r["path"]).name
    out = [{"folder": k, "score": v["score"], "files": v["files"],
            "minutes_total": round(v["secs"] / 60), "signals": "; ".join(sorted(v["signals"])),
            "sample": v["sample"]} for k, v in folders.items()]
    out.sort(key=lambda r: (-r["score"], r["folder"]))
    if args.out:
        c.write_csv(args.out, out, FIELDS)
    print(f"{len(out)} folders with likely non-music, from {len(rows)} files")
    for r in out[: (None if not args.out else 25)]:
        print(f"  [{r['score']}] {r['folder']}  ({r['files']} files, {r['minutes_total']} min: {r['signals']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
