#!/usr/bin/env python3
"""Phase 7: sort video-extension files into real videos and audio in disguise.

A .mp4/.mov/.m4v in a music library is often not video at all. Each file is
probed and put in one of three groups:
  audio-only   no video stream: a song in a video container
  art-only     the only "video" is embedded cover art (one mjpeg/png frame)
  real video   an actual h264/hevc/mpeg4 picture: a music video or concert clip

With --apply:
  audio-only and art-only files are rewrapped losslessly (-c:a copy, art
  stream dropped) to .m4a (AAC/ALAC audio) or .mp3 (MP3 audio) beside the
  original, which goes to the trash. They stay in their music folder.
  real videos move to --videos DIR, keeping their artist/show folders.
  Audio formats that fit neither container are reported, not touched.
Afterwards, folders left with no audio are listed (not deleted).

Usage:
  probe_videos.py LIBRARY [--out report.csv]
  probe_videos.py LIBRARY --apply --videos "Music Videos" --trash TRASH
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

FIELDS = ["kind", "path", "audio_codec", "video_codec", "action"]
M4A_AUDIO = {"aac", "alac"}


def classify(p: Path) -> dict:
    row = {"path": str(p)}
    try:
        probe = c.ffprobe(p)
    except c.ToolError as e:
        return dict(row, kind="unreadable", action=str(e).strip().splitlines()[-1][:120])
    a = c.audio_streams(probe)
    real = c.real_video_streams(probe)
    art = [s for s in probe.get("streams", []) if c.is_art_stream(s)]
    row["audio_codec"] = a[0].get("codec_name", "") if a else ""
    row["video_codec"] = (real or art or [{}])[0].get("codec_name", "")
    if real:
        row["kind"] = "real video"
    elif not a:
        row["kind"] = "no audio or video"
    elif len(a) > 1:
        row["kind"] = "several audio tracks"
        row["action"] = "left alone: a rewrap would keep only the first track; decide by hand"
    else:
        row["kind"] = "art-only" if art else "audio-only"
    return row


def rewrap(p: Path, codec: str) -> tuple[Path | None, str]:
    if codec in M4A_AUDIO:
        ext, fmt = ".m4a", "ipod"
    elif codec in ("mp3", "mp3float"):
        ext, fmt = ".mp3", "mp3"
    else:
        return None, f"{codec} audio fits neither .m4a nor .mp3: convert by hand"
    target = p.with_suffix(ext)
    if target.exists():
        return None, f"{target.name} already exists"
    tmp = c.temp_beside(p, ext)
    c.remove_quiet(tmp)
    cp = c.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", c.ff_path(p), "-map", "0:a:0",
                "-c:a", "copy", "-map_metadata", "0", "-f", fmt, c.ff_path(tmp)], timeout=1800)
    if cp.returncode != 0:
        c.remove_quiet(tmp)
        return None, (cp.stderr.strip().splitlines() or ["ffmpeg failed"])[-1]
    problem = c.verify_output(p, tmp, c.duration_of(c.ffprobe(p)))
    if problem:
        c.remove_quiet(tmp)
        return None, problem
    c.atomic_swap(tmp, target, keep_mode_of=p)
    return target, ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("library", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--videos", type=Path, help="where real videos go (outside the library)")
    ap.add_argument("--trash", type=Path, help="where rewrapped originals go")
    args = ap.parse_args()
    c.require_tools()
    if args.apply and not (args.videos and args.trash):
        sys.exit("--apply needs --videos DIR and --trash DIR")

    lib = Path(c.ff_path(args.library))
    rows = [classify(p) for p in c.walk_files(lib, c.VIDEO_EXTS) if not p.is_symlink()]
    touched = set()
    for r in rows:
        p = Path(r["path"])
        try:
            if r["kind"] in ("audio-only", "art-only"):
                if not args.apply:
                    r["action"] = "would rewrap to audio file in place"
                    continue
                target, err = rewrap(p, r["audio_codec"])
                if target:
                    c.move_to_trash(p, lib, args.trash, "Rewrapped video containers")
                    r["action"] = f"rewrapped to {target.name}"
                else:
                    r["action"] = f"left alone: {err}"
            elif r["kind"] == "real video":
                dest = Path(c.ff_path(args.videos)) / p.relative_to(lib) if args.videos else None
                if not args.apply:
                    r["action"] = "would move to music videos folder"
                    continue
                if dest.exists():
                    r["action"] = (f"left alone: {dest} already exists. Compare the two before "
                                   "removing either; one may be an incomplete copy")
                    continue
                c.safe_move(p, dest)
                touched.add(p.parent)
                r["action"] = f"moved to {dest}"
        except (c.ToolError, OSError) as e:
            r["action"] = f"failed, original left in place: {e}"
    if args.out:
        c.write_csv(args.out, rows, FIELDS)
    for kind in ("audio-only", "art-only", "real video", "several audio tracks", "no audio or video", "unreadable"):
        n = sum(r["kind"] == kind for r in rows)
        if n:
            print(f"{kind}: {n}")
    for r in rows:
        print(f"  {r['kind']}: {r['path']}  [{r.get('action', '')}]")
    for folder in sorted(touched):
        if folder.exists() and not any(True for _ in c.walk_files(folder, c.AUDIO_EXTS)):
            print(f"No audio left in {folder}: remove it once you've looked")
    if not args.apply:
        print("Dry run. Add --apply --videos DIR --trash DIR to act.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
