#!/usr/bin/env python3
"""Lossless repairs for two problems scan_integrity.py finds.

  repair.py extensions LIBRARY [--apply]
      Rename files whose real container doesn't match their extension
      (an intact MP3 named .m, .mp2 or .mp3__, an MP4 named .mp3) to the right
      extension. Nothing inside the file changes.

  repair.py mp3-header FILE... [--apply]
  repair.py mp3-header --from-report REPORT.csv [--apply]
      Rebuild an MP3's length header (the Xing/Info frame) by remuxing with
      ffmpeg -c copy -write_xing 1. Fixes files whose header claims the wrong
      length (e.g. 4x too long, or a nonsense bitrate). Audio frames are copied
      untouched, so this never helps a truly truncated file: afterwards its
      header simply tells the truth about how short it is.

Dry run by default; --apply writes. Rewrites use the same temp-in-folder,
verify, atomic-rename method as retag.py.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402


def cmd_extensions(args) -> int:
    known = c.AUDIO_EXTS | c.VIDEO_EXTS | c.MANGLED_EXTS
    log = args.log or Path("extension_renames.csv")
    done = []
    for p in c.walk_files(args.library):
        if p.is_symlink() or (p.suffix.lower() not in known and not args.all_extensions):
            continue
        wrong = c.misnamed(p)  # the bytes and ffprobe must both agree
        if not wrong:
            continue
        target = p.with_suffix(wrong[1])
        i = 1
        while target.exists():
            target = p.with_name(f"{p.stem} ({i}){wrong[1]}")
            i += 1
        if args.apply:
            p.rename(target)
            done.append({"time": c.now_iso(), "original": str(p), "renamed": str(target)})
            print(f"renamed: {p}\n     -> {target.name}")
        else:
            print(f"would rename: {p}\n          -> {target.name}")
            done.append({})
    if args.apply and done:
        new = not log.exists()
        rows = ([] if new else c.read_csv(log)) + done
        c.write_csv(log, rows, ["time", "original", "renamed"])
        print(f"Renamed {len(done)} files; logged to {log} (rename back from it to undo).")
    else:
        print(f"{'Renamed' if args.apply else 'Would rename'} {len(done)} files.")
    if not args.apply:
        print("Dry run. Add --apply to rename.")
    return 0


def fix_header(p: Path, apply: bool, allow_loss: bool) -> tuple[str, str]:
    if p.is_symlink():
        return "failed", "symlink: repair the file it points to instead"
    probe = c.ffprobe(p)
    header = c.duration_of(probe)
    claimed = f"{header:.1f}s" if header is not None else "no length"
    decoded, errors = c.decode_check(p)
    if decoded is None:
        return "failed", "could not decode"
    if header is not None and abs(header - decoded) <= 0.5:
        return "unchanged", f"header already matches audio ({decoded:.1f}s)"
    if not apply:
        return "would fix", f"header {claimed} -> {decoded:.1f}s"
    tmp = c.temp_beside(p)
    c.remove_quiet(tmp)
    cp = c.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", c.ff_path(p), "-map", "0",
                "-c", "copy", "-map_metadata", "0", "-id3v2_version", "3",
                "-write_xing", "1", c.ff_path(tmp)], timeout=1800)
    if cp.returncode != 0:
        c.remove_quiet(tmp)
        return "failed", (cp.stderr.strip().splitlines() or ["ffmpeg failed"])[-1]
    problem = c.verify_output(p, tmp, decoded, tolerance=0.5)
    if problem is None:
        new_decoded, _ = c.decode_check(tmp)
        if new_decoded is None or abs(new_decoded - decoded) > 0.1:
            problem = "remuxed audio length changed"
    if problem is None:
        lost = c.lost_tags(c.tags_of(probe), c.tags_of(c.ffprobe(tmp)), (), p, tmp)
        if lost and not allow_loss:
            problem = ("the rewrite would drop tags: " + ", ".join(lost)
                       + " (rerun with --allow-tag-loss to accept)")
    if problem:
        c.remove_quiet(tmp)
        return "failed", problem
    c.atomic_swap(tmp, p, keep_mode_of=p)
    note = f"header {claimed} -> {decoded:.1f}s"
    if errors:
        note += "; decode errors remain, audio itself is damaged"
    return "fixed", note


def cmd_mp3_header(args) -> int:
    files = [Path(f) for f in args.files]
    if args.from_report:
        files += [Path(r["path"]) for r in c.read_csv(args.from_report)
                  if r.get("status") == "length_mismatch"
                  and (r.get("container") == "mp3" or r["path"].lower().endswith(".mp3"))]
    if not files:
        sys.exit("No files given.")
    failed = 0
    for p in files:
        try:
            status, note = fix_header(p, args.apply, args.allow_tag_loss)
        except (c.ToolError, OSError) as e:
            status, note = "failed", (str(e).strip().splitlines() or ["error"])[-1]
        failed += status == "failed"
        print(f"{status}: {p}  {note}")
    if not args.apply:
        print("Dry run. Add --apply to rewrite.")
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extensions")
    e.add_argument("library", type=Path)
    e.add_argument("--all-extensions", action="store_true",
                   help="also sniff files with non-audio extensions")
    e.add_argument("--log", type=Path, help="rename log CSV (default ./extension_renames.csv)")
    e.add_argument("--apply", action="store_true")
    m = sub.add_parser("mp3-header")
    m.add_argument("files", nargs="*")
    m.add_argument("--from-report", type=Path)
    m.add_argument("--allow-tag-loss", action="store_true")
    m.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    c.require_tools()
    return cmd_extensions(args) if args.cmd == "extensions" else cmd_mp3_header(args)


if __name__ == "__main__":
    sys.exit(main())
