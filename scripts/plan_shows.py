#!/usr/bin/env python3
"""Phase 1: inventory a live-recording collection and plan its retag.

Live shows rarely have trustworthy tags; the folder name, the filenames and
the setlist are usually the real source of identity. This works in two steps
so every show gets a human look before anything is written.

  plan_shows.py inventory ARTIST_DIR --out shows.csv [--vocab vocab.txt]
      One row per show folder (disc subfolders like "Disc 2", "CD1", "Set 2"
      or "Encore" are folded into their show). Columns: the folder, a date
      parsed from its name (many formats: 1996_12_03, 10-22-2005, 05.10.22,
      1996-12-03...), the album tags the files carry now, track and disc
      counts, total minutes, a guessed source (SBD, AUD, FM, Nugs...), and a
      prefilled target_album in the convention
          YYYY.MM.DD Venue, City, ST | Source
      built from the date and the rest of the folder name. Check and finish
      target_album for every row (look up venues, add the source, spell out
      countries for non-US shows); blank it to skip a show.

  plan_shows.py expand shows.csv --out retag_plan.csv
      A per-file plan for retag.py: album = target_album, disc = N/TOTAL,
      track = n/N per disc (from existing track numbers, else filename
      order), date = the show year, plus artist when the row's artist column
      is filled. Review it, then: retag.py retag_plan.csv --apply

--vocab takes "keyword=Label" lines to extend the source vocabulary.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

DISC_DIR = c.DISC_DIR
SOURCES = [("soundboard", "SBD"), ("sbd", "SBD"), ("audience", "AUD"), ("aud", "AUD"),
           ("matrix", "Matrix"), ("mtx", "Matrix"), ("nugs", "Nugs"), ("fm", "FM"),
           ("radio", "Radio"), ("youtube", "YouTube"), ("dvd", "DVD"), ("tv", "TV"),
           ("webcast", "Webcast")]
SHOW_FIELDS = ["folder", "date", "artist", "current_albums", "tracks", "discs", "minutes",
               "source_guess", "target_album", "notes"]
PLAN_FIELDS = ["path", "artist", "album", "disc", "track", "date", "note"]

DATE_PATTERNS = [
    (re.compile(r"(?<!\d)(19\d\d|20\d\d)[-._/ ](\d{1,2})[-._/ ](\d{1,2})(?!\d)"), "ymd"),
    (re.compile(r"(?<!\d)(\d{1,2})[-._/ ](\d{1,2})[-._/ ](19\d\d|20\d\d)(?!\d)"), "mdy"),
    (re.compile(r"(?<!\d)(\d{2})[-._/](\d{2})[-._/](\d{2})(?!\d)"), "short"),
    (re.compile(r"(?<!\d)(19\d\d|20\d\d)(\d{2})(\d{2})(?!\d)"), "ymd"),
]


def parse_date(text: str) -> tuple[str, str]:
    """Return (YYYY.MM.DD, text with the date removed) or ('', text)."""
    for pat, kind in DATE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        a, b, d = m.groups()
        if kind == "ymd":
            y, mo, dd = int(a), int(b), int(d)
        elif kind == "mdy":
            y, mo, dd = int(d), int(a), int(b)
        else:  # two-digit year: yy.mm.dd if the first part can't be a month, else mm.dd.yy
            x, yv, z = int(a), int(b), int(d)
            if x > 12:
                y, mo, dd = x, yv, z
            else:
                mo, dd, y = x, yv, z
            y += 1900 if y >= 50 else 2000
        if not (1 <= mo <= 12 and 1 <= dd <= 31):
            continue
        rest = (text[:m.start()] + " " + text[m.end():]).strip(" -_.,")
        return f"{y:04d}.{mo:02d}.{dd:02d}", re.sub(r"\s+", " ", rest)
    return "", text


def guess_source(texts: list[str], vocab: list[tuple[str, str]]) -> str:
    blob = " ".join(texts).lower()
    for kw, label in vocab:
        if re.search(rf"(?<![a-z]){re.escape(kw)}(?![a-z])", blob):
            return label
    return ""


def show_folders(root: Path) -> dict[Path, list[tuple[int, Path]]]:
    """Map each show folder to [(disc number, file)], folding disc subfolders."""
    shows: dict[Path, list[tuple[int, Path]]] = defaultdict(list)
    for f in c.walk_files(root, c.AUDIO_EXTS):
        folder, disc = f.parent, 0
        m = DISC_DIR.match(folder.name)
        if m and folder != root:
            disc = int(m.group(1)) if m.group(1) else 99  # "Encore" sorts last
            folder = folder.parent
        shows[folder].append((disc, f))
    return shows


def cmd_inventory(args) -> int:
    root = args.artist_dir.resolve()
    vocab = list(SOURCES)
    if args.vocab:
        for line in args.vocab.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                vocab.insert(0, (k.strip().lower(), v.strip()))
    out = []
    for folder, items in sorted(show_folders(root).items()):
        rows = [c.describe_file(p) for _, p in items]
        discs = sorted({d for d, _ in items})
        name = folder.name if folder != root else "(loose files)"
        date, rest = parse_date(name)
        albums = Counter(r["album"] for r in rows if r["album"])
        if not date and albums:
            date, _ = parse_date(albums.most_common(1)[0][0])
        artist = Counter(r["artist"] for r in rows if r["artist"]).most_common(1)
        source = guess_source([name] + list(albums), vocab)
        rest = re.sub(rf"\b{re.escape(source)}\b", "", rest, flags=re.I).strip(" -_|,") if source else rest
        target = (f"{date} {rest}".strip() + (f" | {source}" if source else "")) if date else ""
        out.append({
            "folder": str(folder.relative_to(root)) if folder != root else ".",
            "date": date, "artist": artist[0][0] if artist else "",
            "current_albums": " | ".join(a for a, _ in albums.most_common(3)),
            "tracks": len(rows), "discs": len(discs) if any(discs) else 1,
            "minutes": round(sum(c.seconds(r) or 0 for r in rows) / 60),
            "source_guess": source, "target_album": target, "notes": "",
        })
    c.write_csv(args.out, out, SHOW_FIELDS)
    undated = sum(1 for r in out if not r["date"])
    print(f"{len(out)} shows -> {args.out} ({undated} with no date found: identify them from the "
          "setlist, e.g. a screenshot from setlist.fm)")
    print("Finish the target_album column, then: plan_shows.py expand")
    return 0


def cmd_expand(args) -> int:
    shows = c.read_csv(args.shows)
    plan = []
    for s in shows:
        target = s.get("target_album", "").strip()
        if not target:
            continue
        folder = (args.artist_dir / s["folder"]).resolve()
        if not folder.exists():
            sys.exit(f"Show folder not found: {folder}")
        items = show_folders(folder).get(folder, [])
        rows = {str(p): c.describe_file(p) for _, p in items}
        discs = sorted({d for d, _ in items})
        multi = len(discs) > 1
        year = target[:4] if re.match(r"\d{4}", target) else ""
        for di, d in enumerate(discs, 1):
            files = sorted((p for dd, p in items if dd == d),
                           key=lambda p: (c.track_no(rows[str(p)]["track"]) or 999, p.name))
            for ti, p in enumerate(files, 1):
                plan.append({
                    "path": str(p), "artist": s.get("artist", "").strip(), "album": target,
                    "disc": f"{di}/{len(discs)}" if multi else "1",
                    "track": f"{ti}/{len(files)}", "date": year, "note": s.get("notes", ""),
                })
    c.write_csv(args.out, plan, PLAN_FIELDS)
    print(f"{len(plan)} files planned -> {args.out}. Review it, then: retag.py {args.out} --apply")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("inventory")
    i.add_argument("artist_dir", type=Path)
    i.add_argument("--out", type=Path, required=True)
    i.add_argument("--vocab", type=Path)
    e = sub.add_parser("expand")
    e.add_argument("shows", type=Path)
    e.add_argument("--artist-dir", type=Path, required=True,
                   help="the same folder given to inventory")
    e.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    c.require_tools()
    return cmd_inventory(args) if args.cmd == "inventory" else cmd_expand(args)


if __name__ == "__main__":
    sys.exit(main())
