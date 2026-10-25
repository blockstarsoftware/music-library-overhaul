#!/usr/bin/env python3
"""Phase 8, category 1: convert uncompressed PCM (WAV/AIFF) to ALAC or FLAC.

This is a space and tagging fix, not a quality upgrade: PCM is already
lossless. ALAC and FLAC are lossless too, roughly half the size, and hold tags
properly (WAV/AIFF often end up "Unknown Album" in music apps).

Each conversion is proved lossless before the original is touched: the audio
of the source and of the new file are both decoded to raw samples and their
MD5 checksums must match. 8-bit sources become 16-bit (ALAC has no 8-bit
mode); that widening is exact, so they are compared at 16-bit. Tags are
carried over; embedded cover art is dropped (-map 0:a), since ffmpeg cannot
copy it into ALAC from these formats.

Only after the check passes does the original go to the trash and the new
file take its place beside it.

Usage:
  convert_lossless.py LIBRARY [--to alac|flac] [--apply --trash TRASH]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402


def sample_plan(stream: dict, to: str) -> tuple[str, str]:
    """(encoder sample_fmt, raw format used for the MD5 comparison)."""
    bits = int(stream.get("bits_per_raw_sample") or stream.get("bits_per_sample") or 16)
    if bits <= 16:
        return ("s16p" if to == "alac" else "s16"), "s16le"
    return ("s32p" if to == "alac" else "s32"), "s32le"


def convert(p: Path, to: str, allow_loss: bool) -> tuple[Path | None, str]:
    probe = c.ffprobe(p)
    streams = c.audio_streams(probe)
    if not streams:
        return None, "no audio stream"
    fmt, raw = sample_plan(streams[0], to)
    ext = ".m4a" if to == "alac" else ".flac"
    target = p.with_suffix(ext)
    if target.exists():
        return None, f"{target.name} already exists"
    tmp = c.temp_beside(p, ext)
    c.remove_quiet(tmp)
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", c.ff_path(p), "-map", "0:a:0",
           "-c:a", to, "-sample_fmt", fmt, "-map_metadata", "0", c.ff_path(tmp)]
    cp = c.run(cmd, timeout=1800)
    if cp.returncode != 0:
        c.remove_quiet(tmp)
        return None, (cp.stderr.strip().splitlines() or ["ffmpeg failed"])[-1]
    problem = c.verify_output(p, tmp, c.duration_of(probe), tolerance=0.05)
    if problem is None:
        a, b = c.audio_md5(p, raw), c.audio_md5(tmp, raw)
        if not a or a != b:
            problem = "decoded audio differs from the source: not lossless, original kept"
    if problem is None:
        lost = c.lost_tags(c.tags_of(probe), c.tags_of(c.ffprobe(tmp)))
        if lost and not allow_loss:
            problem = ("these tags wouldn't survive: " + ", ".join(lost)
                       + " (rerun with --allow-tag-loss to accept)")
    if problem:
        c.remove_quiet(tmp)
        return None, problem
    c.atomic_swap(tmp, target, keep_mode_of=p)
    return target, f"{c.human_size(p.stat().st_size)} -> {c.human_size(target.stat().st_size)}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("library", type=Path)
    ap.add_argument("--to", choices=["alac", "flac"], default="alac")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--trash", type=Path)
    ap.add_argument("--allow-tag-loss", action="store_true")
    args = ap.parse_args()
    c.require_tools()
    if args.apply and not args.trash:
        sys.exit("--apply needs --trash DIR for the originals")

    lib = Path(c.ff_path(args.library))
    failed = done = 0
    for p in c.walk_files(lib, c.AUDIO_EXTS):
        if p.is_symlink():
            continue
        try:
            probe = c.ffprobe(p)
        except c.ToolError:
            continue
        if c.codec_class(probe, p) != "pcm":
            continue
        if not args.apply:
            print(f"would convert: {p}")
            done += 1
            continue
        try:
            target, note = convert(p, args.to, args.allow_tag_loss)
            if target:
                c.move_to_trash(p, lib, args.trash, "Converted PCM originals")
        except (c.ToolError, OSError) as e:
            target, note = None, (str(e).strip().splitlines() or ["error"])[-1]
        if target:
            print(f"converted: {p.name} -> {target.name}  ({note}, verified identical audio)")
            done += 1
        else:
            print(f"FAILED: {p}  {note}")
            failed += 1
    print(f"{'Converted' if args.apply else 'Would convert'} {done}; failed {failed}.")
    if not args.apply:
        print(f"Dry run. Add --apply --trash DIR to convert to {args.to.upper()}.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
