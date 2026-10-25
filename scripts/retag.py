#!/usr/bin/env python3
"""Rewrite tags in place, safely, from a plan CSV.

The plan has a `path` column plus any of these tag columns:
  title, artist, album, album_artist, track, disc, date, genre, comment,
  composer, compilation
An empty cell leaves that tag alone; the value <clear> removes it. Other
columns (notes, etc.) are ignored.

How each file is rewritten (the method that ended the truncation bug):
  1. ffmpeg stream-copies the file (-c copy: audio untouched, never
     re-encoded) with the new tags into a hidden temp file IN THE SAME FOLDER.
  2. The temp is verified: MP4 atoms complete, ffprobe opens it, duration
     matches the original, every requested tag reads back exactly, and every
     tag you didn't ask to change is still there with the same value.
  3. Only then is it swapped over the original with an atomic rename.
A failure at any step leaves the original untouched.

ffmpeg can't carry some tags through a rewrite: iTunes freeform atoms in MP4
(gapless playback info iTunSMPB, MusicBrainz IDs), and in MP3 ratings and
play counts (POPM) and unique IDs (UFID); MP3 lyrics change form. Files that
would lose a tag are refused and listed. --allow-tag-loss rewrites them
anyway, once the person has agreed to lose those tags.

Dry run by default: prints what would change. Add --apply to write.
Progress is logged to a CSV after every file; --resume skips files the log
already records as done, so a long run can be stopped and restarted.

Usage:
  retag.py PLAN.csv [--apply] [--log LOG.csv] [--resume] [--allow-drop-art]
                    [--allow-tag-loss]
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

TAG_FIELDS = ["title", "artist", "album", "album_artist", "track", "disc", "date",
              "genre", "comment", "composer", "compilation"]
CLEAR = "<clear>"
UNTAGGABLE = {".wav", ".aif", ".aiff", ".aifc"}
LOG_FIELDS = ["path", "status", "changes", "detail"]


def planned_changes(row: dict, current: dict) -> dict[str, str | None]:
    """Tag -> new value (None = remove), only where it differs from now."""
    out: dict[str, str | None] = {}
    for k in TAG_FIELDS:
        v = row.get(k, "")
        if v == "":
            continue
        if v.strip() == CLEAR:
            if k in current:
                out[k] = None
        elif current.get(k) != v:
            out[k] = v
    return out


def build_cmd(src: Path, tmp: Path, changes: dict, audio_only: bool) -> list[str]:
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", c.ff_path(src)]
    cmd += ["-map", "0:a"] if audio_only else ["-map", "0"]
    cmd += ["-c", "copy", "-map_metadata", "0"]
    for k, v in changes.items():
        cmd += ["-metadata", f"{k}={'' if v is None else v}"]
    if src.suffix.lower() == ".mp3":
        cmd += ["-id3v2_version", "3"]
    cmd.append(c.ff_path(tmp))
    return cmd


def readback_problem(src: Path, tmp: Path, changes: dict, before: dict, allow_loss: bool) -> str | None:
    after = c.tags_of(c.ffprobe(tmp))
    for k, v in changes.items():
        got = after.get(k)
        if v is None:
            if got not in (None, ""):
                return f"{k} still reads {got!r} after clearing"
        elif got != v:
            return f"{k} reads back {got!r}, expected {v!r}"
    lost = c.lost_tags(before, after, changes, src, tmp)
    if lost and not allow_loss:
        return ("ffmpeg would drop or change tags you didn't ask to touch: " + ", ".join(lost)
                + " (rerun with --allow-tag-loss to accept)")
    return None


def retag_file(path: Path, changes: dict, allow_drop_art: bool, allow_loss: bool) -> tuple[str, str]:
    probe = c.ffprobe(path)
    before = c.tags_of(probe)
    duration = c.duration_of(probe)
    has_art = any(c.is_art_stream(s) for s in probe.get("streams", []))
    tmp = c.temp_beside(path)
    attempts = [False] + ([True] if has_art and allow_drop_art else [])
    last = ""
    for audio_only in attempts:
        c.remove_quiet(tmp)
        cp = c.run(build_cmd(path, tmp, changes, audio_only), timeout=1800)
        if cp.returncode != 0:
            last = (cp.stderr.strip().splitlines() or ["ffmpeg failed"])[-1]
            continue
        problem = c.verify_output(path, tmp, duration) or readback_problem(path, tmp, changes, before, allow_loss)
        if problem:
            c.remove_quiet(tmp)
            return "failed", problem
        c.atomic_swap(tmp, path, keep_mode_of=path)
        return "ok", "cover art dropped" if audio_only else ""
    c.remove_quiet(tmp)
    if has_art and not allow_drop_art:
        last += " (file has embedded art; --allow-drop-art retries without it)"
    return "failed", last


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan", type=Path)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--log", type=Path, help="progress log CSV (default: PLAN.log.csv)")
    ap.add_argument("--resume", action="store_true", help="skip files the log marks ok")
    ap.add_argument("--allow-drop-art", action="store_true",
                    help="if a copy with cover art fails, retry without the art")
    ap.add_argument("--allow-tag-loss", action="store_true",
                    help="rewrite even when ffmpeg would drop tags it can't carry")
    args = ap.parse_args()
    c.require_tools()

    rows = c.read_csv(args.plan)
    if not rows or "path" not in rows[0]:
        sys.exit("Plan needs a 'path' column.")
    log_path = args.log or args.plan.with_suffix(".log.csv")
    done: set[str] = set()
    if args.resume and log_path.exists():
        done = {r["path"] for r in c.read_csv(log_path) if r.get("status") in ("ok", "unchanged")}

    log_f = None
    writer = None
    if args.apply:
        new = not log_path.exists() or not args.resume
        log_f = open(log_path, "w" if new else "a", newline="", encoding="utf-8",
                     errors="surrogateescape")
        writer = csv.DictWriter(log_f, fieldnames=LOG_FIELDS)
        if new:
            writer.writeheader()

    counts = {"ok": 0, "unchanged": 0, "failed": 0, "skipped": 0, "would change": 0}
    for row in rows:
        p = Path(row["path"]).expanduser()
        if str(p) in done:
            counts["skipped"] += 1
            continue
        status, detail, desc = "", "", ""
        if p.is_symlink():
            status, detail = "failed", "symlink: retag the file it points to instead"
        elif not p.exists():
            status, detail = "failed", "file not found"
        elif p.suffix.lower() in UNTAGGABLE:
            status, detail = "failed", "WAV/AIFF hold tags poorly: convert to ALAC first (convert_lossless.py)"
        elif p.suffix.lower() == ".m4p":
            status, detail = "failed", "DRM-protected .m4p cannot be rewritten"
        else:
            try:
                current = c.tags_of(c.ffprobe(p))
                changes = planned_changes(row, current)
                desc = "; ".join(f"{k}: {current.get(k)!r} -> {v!r}" for k, v in changes.items())
                if not changes:
                    status = "unchanged"
                elif not args.apply:
                    status = "would change"
                else:
                    status, detail = retag_file(p, changes, args.allow_drop_art, args.allow_tag_loss)
            except (c.ToolError, OSError) as e:
                status, detail = "failed", (str(e).strip().splitlines() or ["error"])[-1][:200]
        counts[status] = counts.get(status, 0) + 1
        if (not args.apply and status != "unchanged") or status == "failed":
            print(f"{status.upper()}: {p}\n    {detail or desc}")
        if writer:
            writer.writerow({"path": str(p), "status": status, "changes": desc, "detail": detail})
            log_f.flush()
    if log_f:
        log_f.close()
    print("Summary: " + ", ".join(f"{k} {v}" for k, v in counts.items() if v))
    if args.apply:
        print(f"Log: {log_path}")
    else:
        print("Dry run. Add --apply to write.")
    return 1 if counts.get("failed") else 0


if __name__ == "__main__":
    sys.exit(main())
