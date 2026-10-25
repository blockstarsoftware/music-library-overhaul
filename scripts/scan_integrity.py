#!/usr/bin/env python3
"""Phase 0 (and the final check): find damaged files before trusting a library.

Read-only. For every audio file it checks:
  - zero-byte files
  - the real container (from its bytes, confirmed by ffprobe) against the
    extension, which catches intact MP3s with mangled names like .m, .mp2 or
    .mp3__
  - MP4-family files (.m4a/.m4p/...): the atom structure, flagging a missing
    moov atom or an atom (usually mdat) that runs past the end of the file
  - that ffprobe can open the file at all
  - every non-MP4 file (MP3, FLAC, WAV, AIFF, Ogg...): a full decode,
    comparing the decoded length to the length the header claims. A truncated
    MP3 or FLAC probes and plays without errors and still claims its full
    length, so decoding is the only reliable test. MP4 files are covered by
    the atom check; --decode all decodes them too.

Usage:
  scan_integrity.py LIBRARY [--out report.csv] [--decode auto|mp3|all|none] [--jobs N]

Exit status is 1 when any file has an error-level finding.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

FIELDS = ["status", "severity", "path", "extension", "container", "codec", "class",
          "size_bytes", "header_seconds", "decoded_seconds", "detail"]
ERROR, WARN, INFO, OK = "error", "warn", "info", "ok"


def wants_decode(mode: str, container: str | None, ext: str) -> bool:
    if mode == "all":
        return True
    if mode == "none":
        return False
    if mode == "mp3":
        return container == "mp3" or ext == ".mp3"
    return container != "mp4" and ext not in c.MP4_FAMILY  # auto


def check(path: Path, decode: str, tolerance: float) -> list[dict]:
    row = {"path": str(path), "extension": path.suffix.lower(), "size_bytes": 0}
    found: list[tuple[str, str, str]] = []  # (status, severity, detail)
    try:
        size = path.stat().st_size
    except OSError as e:
        return [dict(row, status="unreadable", severity=ERROR, detail=str(e))]
    row["size_bytes"] = size
    if size == 0:
        return [dict(row, status="zero_byte", severity=ERROR, detail="empty file")]

    container = c.sniff_container(path)
    row["container"] = container or ""
    ext = path.suffix.lower()

    if ext in c.MP4_FAMILY or container == "mp4":
        _, problem = c.mp4_atoms(path)
        if problem == "no_moov":
            found.append(("no_moov", ERROR, "moov atom missing: file truncated or never finished"))
        elif problem and problem.startswith("truncated"):
            atom = problem.split(":", 1)[1]
            found.append(("truncated", ERROR, f"{atom} atom runs past end of file"))
        elif problem == "trailing_bytes":
            found.append(("trailing_bytes", WARN, "padding or stray bytes after the last atom "
                                                  "(plays normally)"))
        elif problem:
            found.append(("bad_atom", ERROR, "atom structure unreadable"))

    probe = None
    try:
        probe = c.ffprobe(path)
    except c.ToolError as e:
        if not any(s[1] == ERROR for s in found):
            found.append(("unreadable", ERROR, (str(e).strip().splitlines() or ["?"])[-1][:200]))
    if probe is not None:
        wrong = c.misnamed(path, probe)
        if wrong:
            found.append(("wrong_extension", WARN,
                          f"file is really {wrong[0]}; rename to {wrong[1]} (repair.py extensions)"))
        streams = c.audio_streams(probe)
        row["codec"] = streams[0].get("codec_name", "") if streams else ""
        row["class"] = c.codec_class(probe, path)
        header = c.duration_of(probe)
        row["header_seconds"] = f"{header:.3f}" if header is not None else ""
        if not streams:
            found.append(("no_audio", WARN, "no audio stream"))
        elif row["class"] == "drm":
            found.append(("drm", INFO, "FairPlay-protected purchase: plays only in Apple Music "
                                       "on an authorized account; no tool can process it"))
        elif wants_decode(decode, container, ext):
            try:
                decoded, errors = c.decode_check(path)
            except c.ToolError as e:
                decoded, errors = None, [str(e)]
            row["decoded_seconds"] = f"{decoded:.3f}" if decoded is not None else ""
            if errors:
                found.append(("decode_errors", ERROR, " | ".join(errors[:3])[:300]))
            if decoded is not None and header is not None:
                gap = header - decoded
                if abs(gap) > max(tolerance, header * 0.02):
                    fixable = " or only the header is wrong (repair.py mp3-header fixes it)" \
                        if container == "mp3" else ""
                    found.append((
                        "length_mismatch", ERROR,
                        f"header claims {header:.1f}s, audio decodes to {decoded:.1f}s. "
                        f"Either the file is truncated (audio missing: re-acquire){fixable}. "
                        "Listen to the end or compare with the real track length to tell which."))
    if not found:
        return [dict(row, status="ok", severity=OK, detail="")]
    return [dict(row, status=s, severity=sev, detail=d) for s, sev, d in found]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("library", type=Path)
    ap.add_argument("--out", type=Path, help="CSV report (default: print problems only)")
    ap.add_argument("--decode", choices=["auto", "mp3", "all", "none"], default="auto",
                    help="which files get a full decode (default auto: everything but MP4)")
    ap.add_argument("--tolerance", type=float, default=2.0,
                    help="seconds of header/decode disagreement allowed (default 2)")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--all-extensions", action="store_true",
                    help="scan every file, not only known audio extensions (finds "
                         "audio hiding under odd names)")
    args = ap.parse_args()
    c.require_tools()

    known = c.AUDIO_EXTS | c.VIDEO_EXTS | c.MANGLED_EXTS
    files = list(c.walk_files(args.library, None if args.all_extensions else known))
    if args.all_extensions:
        files = [f for f in files if f.suffix.lower() in known or c.sniff_container(f) in c.PREFERRED_EXT]
    rows: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = {pool.submit(check, f, args.decode, args.tolerance): f for f in files}
        for i, fut in enumerate(cf.as_completed(futures), 1):
            try:
                rows.extend(fut.result())
            except Exception as e:  # one odd file must not end the scan
                rows.append({"path": str(futures[fut]), "status": "scan_failed",
                             "severity": ERROR, "detail": repr(e)[:200]})
            if i % 250 == 0:
                c.print_err(f"  scanned {i}/{len(files)}")
    rows.sort(key=lambda r: ({ERROR: 0, WARN: 1, INFO: 2, OK: 3}[r["severity"]], r["path"]))

    if args.out:
        c.write_csv(args.out, rows, FIELDS)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"Scanned {len(files)} files under {args.library}")
    for status, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {status}: {n}")
    problems = [r for r in rows if r["severity"] in (ERROR, WARN)]
    if not args.out:
        for r in problems:
            print(f"{r['severity'].upper()} {r['status']}: {r['path']}  {r['detail']}")
    elif problems:
        print(f"{len(problems)} findings written to {args.out}")
    return 1 if any(r["severity"] == ERROR for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
