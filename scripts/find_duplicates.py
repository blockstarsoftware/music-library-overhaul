#!/usr/bin/env python3
"""Find duplicates the safe way: durations and audio decide, never titles alone.

Read-only. Writes a findings CSV, plus (with --trash-list) a CSV of the
clear duplicates in the format trash.py move takes. Nothing is removed here.

Modes:
  mixed   Inside each album folder that mixes lossless and lossy tracks, match
          every lossy track to a lossless one: same title and the same version
          markers ("Song" never matches "Song (Mono)" or "Song (Instrumental)"),
          else the same disc and track number with a similar title, which
          catches typos like "Gonna"/"Going To". Within the tolerance (default
          3 s) it is the same recording, but only after the lossless copy
          decodes completely: a truncated lossless file still claims its full
          length, and trashing the lossy copy would lose the only good one.
          Further apart it is a different version: keep it and listen.
  albums  The same album (artist + album tag) in more than one folder (disc
          subfolders count as one album). Redundant only when the album names
          match, every track is within 0.25 s, the best copy decodes
          completely, and, for two lossless copies, the decoded audio is
          identical. Otherwise: different masterings or editions, keep both.
          Different track counts or unknown durations: check by hand.
  tracks  Library-wide report of the same artist + title in different folders
          with durations inside the tolerance, one lossy and one lossless.
          Report only, never written to --trash-list: one song exists in many
          live performances, and two shows can land within seconds of each
          other. Files that look live (show dates, "| Source", SBD/AUD) are
          skipped. Listen before removing anything it lists.

Usage:
  find_duplicates.py MODE LIBRARY [--out findings.csv] [--trash-list dupes.csv]
                     [--tolerance 3]
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

LOSSLESS = {"lossless", "pcm"}
LOSSY = {"lossy", "drm"}
LIVE_HINT = re.compile(r"(?<!\d)(?:19|20)\d\d[.\-_/ ]\d{1,2}[.\-_/ ]\d{1,2}(?!\d)|\|\s*\w|"
                       r"\b(?:sbd|aud|soundboard|audience|bootleg|matrix)\b", re.I)
# Two copies of one master match to within encoder padding (hundredths of a
# second, even across ALAC and AAC). Remasters often differ by only a few
# tenths, so anything looser would call a remaster a duplicate.
SAME_MASTER = 0.25


def title_of(r: dict) -> str:
    return r["title"] or Path(r["path"]).stem


def same_song(a: dict, b: dict) -> bool:
    ka = c.title_key(title_of(a))
    return bool(ka) and ka == c.title_key(title_of(b)) and \
        c.version_tags(title_of(a)) == c.version_tags(title_of(b))


def disc_track(r: dict) -> tuple[int, int] | None:
    t = c.track_no(r.get("track"))
    return None if t is None else (c.disc_of(r), t)


def mode_mixed(rows: list[dict], tol: float) -> tuple[list[dict], list[dict]]:
    by_folder: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_folder[str(c.album_unit(r["path"]))].append(r)
    findings, dupes = [], []
    for folder, rs in sorted(by_folder.items()):
        good = [r for r in rs if r["class"] in LOSSLESS]
        bad = [r for r in rs if r["class"] in LOSSY]
        if not good or not bad:
            continue
        for b in bad:
            match, how = next(((g, "title") for g in good if same_song(b, g)), (None, ""))
            if match is None and disc_track(b):
                bk = c.title_key(title_of(b))
                for g in good:
                    if disc_track(g) == disc_track(b) and \
                            c.similar(bk, c.title_key(title_of(g))) >= 0.6 and \
                            c.version_tags(title_of(b)) == c.version_tags(title_of(g)):
                        match, how = g, "disc+track number, similar title"
                        break
            row = {"mode": "mixed", "folder": folder, "path": b["path"],
                   "class": b["class"], "seconds": b["seconds"]}
            if match is None:
                other = next((g for g in good if c.title_key(title_of(g)) == c.title_key(title_of(b))), None)
                if other is not None:
                    findings.append(dict(row, match_path=other["path"], verdict="different version",
                                         matched_by="title, but version markers differ",
                                         action="keep; listen to confirm"))
                else:
                    findings.append(dict(row, verdict="unique lossy track",
                                         action="keep; add to upgrade list"))
                continue
            bs, gs = c.seconds(b), c.seconds(match)
            diff = abs(bs - gs) if bs is not None and gs is not None else None
            row.update(match_path=match["path"], matched_by=how, match_seconds=match["seconds"],
                       diff_seconds=f"{diff:.2f}" if diff is not None else "")
            if diff is None or diff > tol:
                findings.append(dict(row, verdict="different version", action="keep; listen to confirm"))
            elif not c.decodes_complete(Path(match["path"]), gs):
                findings.append(dict(row, verdict="lossless copy looks damaged",
                                     action="keep both; scan the lossless file"))
            else:
                findings.append(dict(row, verdict="duplicate of lossless track", action="trash lossy copy"))
                dupes.append({"path": b["path"], "reason": "Lossy duplicates of lossless tracks"})
    return findings, dupes


def album_group_key(rs: list[dict]) -> tuple[str, str] | None:
    artists = Counter(c.artist_key(r["album_artist"] or r["artist"]) for r in rs
                      if c.artist_key(r["album_artist"] or r["artist"]))
    albums = Counter(c.title_key(r["album"]) for r in rs if c.title_key(r["album"]))
    if not artists or not albums:
        return None
    return artists.most_common(1)[0][0], albums.most_common(1)[0][0]


def album_names(rs: list[dict]) -> set[str]:
    return {c.fold(r["album"]) for r in rs if r["album"]}


def track_order(rs: list[dict]) -> list[dict]:
    return sorted(rs, key=lambda r: (disc_track(r) or (99, 999), Path(r["path"]).name))


def same_audio(a: dict, b: dict) -> bool:
    ma = c.audio_md5(Path(a["path"]))
    return ma is not None and ma == c.audio_md5(Path(b["path"]))


def judge_copy(i: dict, best: dict) -> tuple[str, str, bool]:
    """(verdict, action, redundant) for copy i against the best copy."""
    if len(i["rows"]) != len(best["rows"]):
        return "different track list", "check by hand", False
    pairs = list(zip(i["rows"], best["rows"]))
    durs = [(c.seconds(a), c.seconds(b)) for a, b in pairs]
    if any(x is None or y is None for x, y in durs):
        return "durations unknown", "check by hand", False
    gap = max(abs(x - y) for x, y in durs)
    if album_names(i["rows"]) != album_names(best["rows"]):
        return f"different edition (album names differ; max track gap {gap:.2f}s)", "keep both", False
    if gap > SAME_MASTER:
        return f"different mastering (max track gap {gap:.2f}s)", "keep both", False
    if not all(c.decodes_complete(Path(b["path"]), c.seconds(b)) for b in best["rows"]):
        return "best copy may be damaged", "scan it before removing either", False
    if all(a["class"] in LOSSLESS and b["class"] in LOSSLESS for a, b in pairs) and \
            not all(same_audio(a, b) for a, b in pairs):
        return "different mastering (lossless audio differs)", "keep both", False
    return "redundant copy", "trash (best copy kept)", True


def mode_albums(rows: list[dict], tol: float) -> tuple[list[dict], list[dict]]:
    by_folder: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_folder[str(c.album_unit(r["path"]))].append(r)
    groups: dict[tuple, list[str]] = defaultdict(list)
    for folder, rs in by_folder.items():
        k = album_group_key(rs)
        if k:
            groups[k].append(folder)
    findings, dupes = [], []
    for key, folders in sorted(groups.items()):
        if len(folders) < 2:
            continue
        info = []
        for f in sorted(folders):
            rs = track_order(by_folder[f])
            lossless = sum(r["class"] in LOSSLESS for r in rs)
            kbps = [int(r["bitrate_kbps"]) for r in rs if str(r["bitrate_kbps"]).isdigit()]
            info.append({"folder": f, "rows": rs, "lossless": lossless,
                         "avg_kbps": round(sum(kbps) / len(kbps)) if kbps else 0})
        best = max(info, key=lambda i: (i["lossless"] / max(1, len(i["rows"])), i["avg_kbps"],
                                        len(i["rows"])))
        for i in info:
            if i is best:
                verdict, action, redundant = "best copy", "keep", False
            else:
                verdict, action, redundant = judge_copy(i, best)
            if redundant:
                dupes += [{"path": r["path"], "reason": "Redundant album copies"} for r in i["rows"]]
            findings.append({
                "mode": "albums", "group": f"{key[0]} / {key[1]}", "folder": i["folder"],
                "tracks": len(i["rows"]), "lossless": i["lossless"], "avg_kbps": i["avg_kbps"],
                "verdict": verdict, "action": action, "match_path": best["folder"],
            })
    return findings, dupes


def looks_live(r: dict) -> bool:
    text = " ".join([r.get("album", ""), str(c.album_unit(r["path"]).name), title_of(r)])
    return bool(LIVE_HINT.search(text)) or "live" in c.version_tags(title_of(r))


def mode_tracks(rows: list[dict], tol: float) -> tuple[list[dict], list[dict]]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        a, t = c.artist_key(r["artist"]), c.title_key(r["title"])
        if a and t and not looks_live(r):
            groups[(a, t, c.version_tags(r["title"]))].append(r)
    findings = []
    for key, rs in sorted(groups.items(), key=lambda kv: kv[0][:2]):
        good = [r for r in rs if r["class"] in LOSSLESS]
        bad = [r for r in rs if r["class"] in LOSSY]
        for b in bad:
            for g in good:
                if c.album_unit(g["path"]) == c.album_unit(b["path"]):
                    continue  # same folder: mixed mode's job
                bs, gs = c.seconds(b), c.seconds(g)
                if bs is None or gs is None or abs(bs - gs) > tol:
                    continue
                findings.append({"mode": "tracks", "path": b["path"], "class": b["class"],
                                 "seconds": b["seconds"], "match_path": g["path"],
                                 "match_seconds": g["seconds"], "diff_seconds": f"{abs(bs - gs):.2f}",
                                 "matched_by": "artist+title", "verdict": "possible lossy copy",
                                 "action": "listen to both before removing"})
                break
    return findings, []


FIELDS = ["mode", "verdict", "action", "path", "class", "seconds", "match_path",
          "match_seconds", "diff_seconds", "matched_by", "group", "folder", "tracks",
          "lossless", "avg_kbps"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["mixed", "albums", "tracks"])
    ap.add_argument("library", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--trash-list", type=Path, help="CSV of clear duplicates for trash.py move")
    ap.add_argument("--tolerance", type=float, default=3.0,
                    help="seconds within which two tracks are the same recording (default 3)")
    ap.add_argument("--jobs", type=int, default=8)
    args = ap.parse_args()
    c.require_tools()

    rows = c.catalog(args.library, args.jobs)
    fn = {"mixed": mode_mixed, "albums": mode_albums, "tracks": mode_tracks}[args.mode]
    findings, dupes = fn(rows, args.tolerance)
    if args.out:
        c.write_csv(args.out, findings, FIELDS)
    if args.trash_list:
        c.write_csv(args.trash_list, dupes, ["path", "reason"])
    verdicts = Counter(f["verdict"].split(" (")[0] for f in findings)
    print(f"{args.mode}: {len(findings)} findings across {len(rows)} files")
    for v, n in verdicts.most_common():
        print(f"  {v}: {n}")
    if not args.out:
        for f in findings:
            print(f"{f['verdict']}: {f.get('path') or f.get('folder')}  [{f['action']}]")
    if dupes:
        where = f" -> {args.trash_list}" if args.trash_list else " (use --trash-list to save them)"
        print(f"{len(dupes)} files are clear duplicates{where}")
    if args.mode == "tracks" and findings:
        print("tracks mode only reports: listen to each pair before removing anything.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
