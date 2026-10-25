"""Shared helpers for the music-library-overhaul scripts.

Standard library only (Python 3.9+). Every probe and decode goes through
ffprobe/ffmpeg, which must be on PATH.
"""
from __future__ import annotations

import csv
import datetime as _dt
import difflib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Iterable, Iterator

AUDIO_EXTS = {
    ".mp3", ".m4a", ".m4p", ".m4b", ".aac", ".flac", ".alac", ".wav", ".aif",
    ".aiff", ".aifc", ".ogg", ".oga", ".opus", ".wma", ".ape", ".wv", ".mp2",
}
VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".mkv", ".avi", ".webm", ".mpg", ".mpeg"}
MP4_FAMILY = {".m4a", ".m4p", ".m4b", ".mp4", ".m4v", ".mov", ".alac"}
# Odd names old tools left on intact MP3s; scanned so they can be repaired.
MANGLED_EXTS = {".m", ".mp", ".mp3__"}

LOSSLESS_CODECS = {"alac", "flac", "ape", "wavpack", "tta", "mlp", "truehd"}
LOSSY_CODECS = {
    "mp3", "mp3float", "mp2", "aac", "aac_latm", "vorbis", "opus", "wmav1",
    "wmav2", "wmapro", "ac3", "eac3", "dts",
}
ART_CODECS = {"mjpeg", "png", "bmp", "gif", "tiff", "webp"}

# Folders the scripts never descend into: our own trash, and macOS clutter.
SKIP_DIRS = {"_Run Trash", ".Trash", ".Trashes", ".Spotlight-V100", ".fseventsd"}
TEMP_MARK = ".mlo-tmp"


class ToolError(RuntimeError):
    pass


def require_tools() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:  # filenames that aren't valid UTF-8 must not crash a report
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    missing = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]
    if missing:
        sys.exit(
            "Missing " + " and ".join(missing) + ". Install with: brew install ffmpeg"
        )


def walk_files(root: Path, exts: set[str] | None = None) -> Iterator[Path]:
    """Yield files under root in a stable order, skipping hidden files,
    our temp files and trash folders. exts filters by lowercase suffix."""
    root = Path(root)
    if root.is_file():
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")
        )
        for name in sorted(filenames):
            if name.startswith(".") or TEMP_MARK in name:
                continue
            p = Path(dirpath) / name
            if exts is None or p.suffix.lower() in exts:
                yield p


def ff_path(p: Path | str) -> str:
    """Absolute path for ffmpeg. A relative path whose first part contains a
    colon (Finder's "AC/DC" is "AC:DC" on disk) would be read as a protocol."""
    return os.path.abspath(str(p))


def run(cmd: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise ToolError(f"{cmd[0]} timed out after {timeout:.0f}s (slow disk or an "
                        "online-only cloud file?)")


def ffprobe(path: Path, timeout: float = 120) -> dict:
    """Return ffprobe's format and streams for path, or raise ToolError."""
    cp = run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
         "-show_streams", ff_path(path)],
        timeout=timeout,
    )
    if cp.returncode != 0:
        raise ToolError(cp.stderr.strip() or "ffprobe failed")
    try:
        return json.loads(cp.stdout or "{}")
    except json.JSONDecodeError as e:
        raise ToolError(f"ffprobe output unreadable: {e}")


def audio_streams(probe: dict) -> list[dict]:
    return [s for s in probe.get("streams", []) if s.get("codec_type") == "audio"]


def is_art_stream(s: dict) -> bool:
    """A 'video' stream that is only embedded cover art. When in doubt (an
    image codec with no frame count, as in MKV) it is treated as real video,
    so nothing that might be a picture gets dropped."""
    if s.get("codec_type") != "video":
        return False
    if (s.get("disposition") or {}).get("attached_pic") == 1:
        return True
    if s.get("codec_name") not in ART_CODECS:
        return False
    frames = s.get("nb_frames")
    if frames in ("0", "1"):
        return True
    try:
        return frames is None and float(s.get("duration") or "inf") < 1.0
    except ValueError:
        return False


def real_video_streams(probe: dict) -> list[dict]:
    return [
        s for s in probe.get("streams", [])
        if s.get("codec_type") == "video" and not is_art_stream(s)
    ]


def tags_of(probe: dict) -> dict[str, str]:
    """Format tags merged with the first audio stream's tags, keys lowercased.
    Format-level tags win (that is where MP3 and MP4 tags live)."""
    out: dict[str, str] = {}
    for s in audio_streams(probe)[:1]:
        for k, v in (s.get("tags") or {}).items():
            out[k.lower()] = v
    for k, v in (probe.get("format", {}).get("tags") or {}).items():
        out[k.lower()] = v
    # Normalize the few keys that differ between containers.
    for src, dst in (("tpe1", "artist"), ("tit2", "title"), ("talb", "album"),
                     ("tpos", "disc"), ("trck", "track"), ("tpe2", "album_artist"),
                     ("albumartist", "album_artist"), ("tracknumber", "track"),
                     ("discnumber", "disc")):
        if src in out and dst not in out:
            out[dst] = out[src]
    return out


def duration_of(probe: dict) -> float | None:
    d = probe.get("format", {}).get("duration")
    if d in (None, "N/A"):
        for s in audio_streams(probe):
            if s.get("duration") not in (None, "N/A"):
                d = s["duration"]
                break
    try:
        return float(d) if d is not None else None
    except ValueError:
        return None


def codec_class(probe: dict, path: Path | None = None) -> str:
    """'lossless', 'lossy', 'pcm', 'drm', 'none' or 'unknown' for the main
    audio stream. Integer PCM (WAV/AIFF) is lossless but reported apart
    because it is the one class worth converting; floating-point PCM can't go
    to ALAC or FLAC without change, so it counts as plain lossless."""
    if path is not None and Path(path).suffix.lower() == ".m4p":
        return "drm"
    streams = audio_streams(probe)
    if not streams:
        return "none"
    s = streams[0]
    name = (s.get("codec_name") or "").lower()
    tag = (s.get("codec_tag_string") or "").lower()
    if tag == "drms" or (name == "none" and tag.startswith("drm")):
        return "drm"
    if name.startswith("pcm_f"):
        return "lossless"
    if name.startswith("pcm_"):
        return "pcm"
    if name in LOSSLESS_CODECS:
        return "lossless"
    if name in LOSSY_CODECS:
        return "lossy"
    return "unknown"


def decode_check(path: Path, timeout: float = 900) -> tuple[float | None, list[str]]:
    """Decode the first audio stream fully. Returns (decoded seconds, error
    lines). Decoding is the only reliable test for MP3 and FLAC damage: a
    truncated file can still carry a header claiming its full length."""
    cp = run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", ff_path(path), "-map", "0:a:0",
         "-f", "null", "-progress", "pipe:1", "-nostats", "-"],
        timeout=timeout,
    )
    seconds = None
    for line in cp.stdout.splitlines():
        if line.startswith("out_time_us="):
            try:
                seconds = int(line.split("=", 1)[1]) / 1_000_000
            except ValueError:
                pass
    errors = [l for l in cp.stderr.splitlines() if l.strip()]
    if cp.returncode != 0 and not errors:
        errors = [f"ffmpeg exited {cp.returncode}"]
    return seconds, errors


def decodes_complete(path: Path, header: float | None = None, tolerance: float = 2.0) -> bool:
    """True if the file decodes without errors to (about) its claimed length."""
    try:
        if header is None:
            header = duration_of(ffprobe(path))
        decoded, errors = decode_check(path)
    except ToolError:
        return False
    if errors or decoded is None or header is None:
        return False
    return abs(header - decoded) <= max(tolerance, header * 0.02)


def audio_md5(path: Path, raw: str = "s32le", timeout: float = 900) -> str | None:
    """MD5 of the decoded audio as raw samples (s16le or s32le). Equal
    checksums prove two files hold the same audio, whatever the container."""
    try:
        cp = run(["ffmpeg", "-nostdin", "-v", "error", "-i", ff_path(path), "-map", "0:a:0",
                  "-c:a", f"pcm_{raw}", "-f", "md5", "-"], timeout=timeout)
    except ToolError:
        return None
    out = cp.stdout.strip()
    return out.split("=", 1)[1] if cp.returncode == 0 and out.startswith("MD5=") else None


def _all_zero(f, start: int, size: int) -> bool:
    f.seek(start)
    remaining = size - start
    while remaining > 0:
        chunk = f.read(min(remaining, 1 << 20))
        if not chunk or chunk.strip(b"\x00"):
            return False
        remaining -= len(chunk)
    return True


def mp4_atoms(path: Path) -> tuple[list[tuple[str, int, int]], str | None]:
    """Walk top-level MP4 atoms. Returns (atoms, problem) where problem is
    None, 'no_moov', 'truncated:<atom>', 'bad_atom' or 'trailing_bytes'
    (zero padding or a few stray bytes after complete atoms: harmless)."""
    size = path.stat().st_size
    atoms: list[tuple[str, int, int]] = []
    with open(path, "rb") as f:
        off = 0
        while off + 8 <= size:
            f.seek(off)
            head = f.read(8)
            asize, atype = struct.unpack(">I4s", head)
            name = atype.decode("latin-1")
            if asize == 1:
                ext = f.read(8)
                if len(ext) < 8:
                    return atoms, f"truncated:{name}"
                asize = struct.unpack(">Q", ext)[0]
            elif asize == 0:
                asize = size - off
            if asize < 8 or not re.fullmatch(r"[ -~]{4}", name):
                complete = any(a[0] == "moov" for a in atoms) and any(a[0] == "mdat" for a in atoms)
                if complete and _all_zero(f, off, size):
                    return atoms, "trailing_bytes"
                return atoms, "bad_atom"
            atoms.append((name, off, asize))
            if off + asize > size:
                return atoms, f"truncated:{name}"
            off += asize
    if not any(a[0] == "moov" for a in atoms):
        return atoms, "no_moov"
    if off < size:
        return atoms, "trailing_bytes"
    return atoms, None


# ---------- container sniffing ----------

_BR = {  # kbps by (mpeg1?, layer)
    (True, 1): [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448],
    (True, 2): [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384],
    (True, 3): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    (False, 1): [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256],
    (False, 2): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
    (False, 3): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
}
_SR = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def _mpeg_frame_len(b: bytes) -> int | None:
    """Length of the MPEG audio frame whose header starts b, or None."""
    if len(b) < 4 or b[0] != 0xFF or (b[1] & 0xE0) != 0xE0:
        return None
    version, layer_bits = (b[1] >> 3) & 3, (b[1] >> 1) & 3
    bri, sri, pad = b[2] >> 4, (b[2] >> 2) & 3, (b[2] >> 1) & 1
    if version == 1 or layer_bits == 0 or bri in (0, 15) or sri == 3:
        return None
    layer = 4 - layer_bits
    mpeg1 = version == 3
    br = _BR[(mpeg1, layer)][bri] * 1000
    sr = _SR[version][sri]
    if layer == 1:
        return (12 * br // sr + pad) * 4
    if layer == 3 and not mpeg1:
        return 72 * br // sr + pad
    return 144 * br // sr + pad


def _looks_like_mpeg_audio(data: bytes, start: int = 0, window: int = 16384) -> bool:
    """Three consecutive valid MPEG audio frames, each where the last one's
    length says it should be. A lone 0xFFE sync pattern proves nothing."""
    for i in range(start, min(len(data) - 4, start + window)):
        if data[i] != 0xFF:
            continue
        pos, chained = i, 0
        while chained < 3:
            n = _mpeg_frame_len(data[pos:pos + 4])
            if not n:
                break
            chained += 1
            pos += n
        if chained == 3:
            return True
    return False


_MAGIC = [  # (offset, bytes, kind)
    (0, b"\x1aE\xdf\xa3", "matroska"), (0, b"0&\xb2u\x8ef\xcf\x11", "asf"),
    (0, b"\x00\x00\x01\xba", "mpegps"), (0, b"\x00\x00\x01\xb3", "mpegps"),
    (0, b"wvpk", "wavpack"), (0, b"MAC ", "ape"), (0, b"\xff\xd8\xff", "image"),
    (0, b"\x89PNG", "image"), (0, b"GIF8", "image"), (0, b"%PDF", "document"),
    (0, b"PK\x03\x04", "archive"),
]


def sniff_container(path: Path) -> str | None:
    """Identify the real container from its bytes, independent of the file
    extension. Returns 'mp3', 'mp4', 'flac', 'wav', 'aiff', 'ogg', 'adts', a
    non-audio kind ('matroska', 'avi', 'image'...), or None if unsure."""
    try:
        with open(path, "rb") as f:
            head = f.read(65536)
    except OSError:
        return None
    if len(head) < 12:
        return None
    start = 0
    if head[:3] == b"ID3" and len(head) >= 10:  # skip an ID3v2 tag, then look again
        size = (head[6] << 21) | (head[7] << 14) | (head[8] << 7) | head[9]
        start = 10 + size + (10 if head[5] & 0x10 else 0)
        if start + 12 > len(head):
            with open(path, "rb") as f:
                f.seek(start)
                head = head[:start] + f.read(65536)
    body = head[start:]
    if len(body) < 12:
        return None
    if body[4:8] == b"ftyp":
        return "mp4"
    if body[:4] == b"fLaC":
        return "flac"
    if body[:4] == b"RIFF" and body[8:12] == b"WAVE":
        return "wav"
    if body[:4] == b"RIFF" and body[8:12] == b"AVI ":
        return "avi"
    if body[:4] == b"FORM" and body[8:12] in (b"AIFF", b"AIFC"):
        return "aiff"
    if body[:4] == b"OggS":
        return "ogg"
    for off, magic, kind in _MAGIC:
        if body[off:off + len(magic)] == magic:
            return kind
    if body[0] == 0xFF and (body[1] & 0xF6) == 0xF0:
        return "adts"
    if _looks_like_mpeg_audio(head, start):
        return "mp3"
    return None


CONTAINER_EXT = {
    "mp3": {".mp3", ".mp2"}, "mp4": MP4_FAMILY, "flac": {".flac"},
    "wav": {".wav"}, "aiff": {".aif", ".aiff", ".aifc"}, "ogg": {".ogg", ".oga", ".opus"},
}
# The audio containers repair.py renames into; ffprobe must agree first.
PREFERRED_EXT = {"mp3": ".mp3", "mp4": ".m4a", "flac": ".flac", "wav": ".wav",
                 "aiff": ".aiff", "ogg": ".ogg"}
FFPROBE_FORMAT = {"mp3": "mp3", "mp4": "mp4", "flac": "flac", "wav": "wav",
                  "aiff": "aiff", "ogg": "ogg"}


def misnamed(path: Path, probe: dict | None = None) -> tuple[str, str] | None:
    """(real container, extension to use) when path holds a known audio
    container under the wrong extension and ffprobe agrees, else None."""
    kind = sniff_container(path)
    if kind not in PREFERRED_EXT or path.suffix.lower() in CONTAINER_EXT[kind]:
        return None
    try:
        probe = probe or ffprobe(path)
    except ToolError:
        return None
    if FFPROBE_FORMAT[kind] not in (probe.get("format", {}).get("format_name") or ""):
        return None
    ext = PREFERRED_EXT[kind]
    if kind == "mp4" and real_video_streams(probe):
        ext = ".mp4"
    return kind, ext


CATALOG_FIELDS = ["path", "class", "codec", "bits", "sample_rate", "bitrate_kbps",
                  "seconds", "artist", "album_artist", "album", "title", "track",
                  "disc", "genre", "compilation", "size_bytes"]


def describe_file(p: Path) -> dict:
    """One catalog row: codec class, format details, duration and main tags."""
    row = {k: "" for k in CATALOG_FIELDS}
    row["path"] = str(p)
    try:
        row["size_bytes"] = p.stat().st_size
        probe = ffprobe(p)
    except (ToolError, OSError) as e:
        msg = (str(e).strip().splitlines() or ["unreadable"])[-1][:80]
        return dict(row, **{"class": "unreadable", "codec": msg})
    a = (audio_streams(probe) or [{}])[0]
    tags = tags_of(probe)
    br = a.get("bit_rate") or probe.get("format", {}).get("bit_rate")
    d = duration_of(probe)
    row.update({
        "class": codec_class(probe, p), "codec": a.get("codec_name", ""),
        "bits": a.get("bits_per_raw_sample") or a.get("bits_per_sample") or "",
        "sample_rate": a.get("sample_rate", ""),
        "bitrate_kbps": round(int(br) / 1000) if br and str(br).isdigit() else "",
        "seconds": f"{d:.2f}" if d else "",
    })
    for k in ("artist", "album_artist", "album", "title", "track", "disc", "genre", "compilation"):
        row[k] = tags.get(k, "")
    return row


def catalog(library: Path, jobs: int = 8, exts: set[str] | None = None) -> list[dict]:
    import concurrent.futures as cf
    files = list(walk_files(library, exts or AUDIO_EXTS))
    with cf.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        return list(pool.map(describe_file, files))


DISC_DIR = re.compile(r"^(?:disc|disk|cd|set|d)\s*[-_ ]?(\d+)\b|^encore\b", re.I)


def album_unit(path: str | Path) -> Path:
    """The album folder a file belongs to: its parent, or the grandparent
    when the parent is a disc subfolder ("CD1", "Disc 2", "Set 2", "Encore")."""
    parent = Path(path).parent
    return parent.parent if DISC_DIR.match(parent.name) else parent


def disc_of(row: dict) -> int:
    """Disc number from the tag, else from a disc subfolder's name, else 1."""
    n = track_no(row.get("disc"))
    if n:
        return n
    m = DISC_DIR.match(Path(row["path"]).parent.name)
    if m:
        return int(m.group(1)) if m.group(1) else 99
    return 1


def seconds(row: dict) -> float | None:
    try:
        return float(row.get("seconds") or "")
    except ValueError:
        return None


# ---------- text normalization ----------

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                         "´": "'", "`": "'", "‐": "-", "–": "-",
                         "—": "-"})


def fold(s: str) -> str:
    """Casefolded, straight quotes, accents removed, whitespace collapsed."""
    s = unicodedata.normalize("NFKD", (s or "").translate(_QUOTES))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().casefold()


def _letters(s: str) -> str:
    """Keep letters and digits in any script (Cyrillic, CJK...), drop the rest."""
    return re.sub(r"[\W_]+", "", s)


def artist_key(name: str) -> str:
    """Key under which spelling variants of one artist collide: case, accents,
    curly quotes, '&' vs 'and', a leading 'The', punctuation and spacing.
    Empty for names made only of punctuation ("!!!"); callers must never
    group by an empty key."""
    s = fold(name)
    s = re.sub(r"^the\s+", "", s)
    s = s.replace("&", " and ").replace("+", " and ")
    return _letters(s)


_MARKER_WORDS = (r"live|acoustic|unplugged|remix|mix|remaster(?:ed)?|demo|edit|version|"
                 r"mono|stereo|bonus|single|radio|extended|instrumental|deluxe|"
                 r"alternate|alt|take|session|rehearsal|karaoke|a cappella|acapella|dub")
VERSION_MARKERS = re.compile(
    r"\s*[\(\[][^\)\]]*\b(" + _MARKER_WORDS + r")\b[^\)\]]*[\)\]]"
    r"|\s+-\s+[^-]*\b(" + _MARKER_WORDS + r")\b[^-]*$",
    re.IGNORECASE,
)


def title_key(title: str) -> str:
    """A title with version markers ("(Live)", "- 2011 Remaster"), leading
    track numbers, case, accents and punctuation removed. Use it to group
    versions of a song, never alone to call two tracks duplicates: pair it
    with version_tags()."""
    s = VERSION_MARKERS.sub("", title or "")
    s = fold(s)
    s = re.sub(r"^\d{1,3}[\s.\-_]+", "", s)
    return _letters(s)


def version_tags(title: str) -> frozenset[str]:
    """The version words in a title: "Song (Mono)" -> {'mono'}. Two tracks
    are only the same recording if these match ("Song" vs "Song (Mono)" are
    different mixes even when their durations agree)."""
    found = set()
    for m in VERSION_MARKERS.finditer(title or ""):
        for w in re.findall(_MARKER_WORDS, m.group(0), re.IGNORECASE):
            found.add(fold(w).replace("remastered", "remaster"))
    return frozenset(found)


def similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def track_no(value: str | None) -> int | None:
    m = re.match(r"\s*(\d+)", value or "")
    return int(m.group(1)) if m else None


# ---------- CSV / reports ----------

def read_csv(path: Path) -> list[dict[str, str]]:
    """Read a CSV as UTF-8 (with or without a BOM), falling back to the
    Windows encoding some Excel exports use."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="surrogateescape")
    import io
    return [{(k or "").strip(): (v or "") for k, v in row.items()}
            for row in csv.DictReader(io.StringIO(text, newline=""))]


def write_csv(path: Path, rows: Iterable[dict], fields: list[str]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "w", newline="", encoding="utf-8", errors="surrogateescape") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
            n += 1
    return n


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def now_iso() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat()


# ---------- moving files safely ----------

MANIFEST = "_manifest.jsonl"


def safe_move(src: Path, dest: Path) -> None:
    """Move src to dest (which must not exist). On the same volume this is a
    rename. Across volumes it copies to a temp name at the destination,
    checks the size, renames it into place, and only then removes src, so an
    interrupted move never leaves a partial file under the final name.
    Symlinks are moved as links, never followed."""
    src, dest = Path(src), Path(dest)
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(str(dest))
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(src, dest)
        return
    except OSError as e:
        if getattr(e, "errno", None) != 18:  # EXDEV: different volumes
            raise
    if src.is_symlink():
        os.symlink(os.readlink(src), dest)
        os.unlink(src)
        return
    tmp = dest.with_name(f".{dest.name}{TEMP_MARK}-{os.getpid()}")
    shutil.copy2(src, tmp)
    if tmp.stat().st_size != src.stat().st_size:
        remove_quiet(tmp)
        raise OSError(f"copy of {src} came out the wrong size; original kept")
    os.replace(tmp, dest)
    os.unlink(src)


def move_to_trash(path: Path, library: Path, trash: Path, reason: str) -> Path:
    """Move path into trash/<reason>/<path relative to library>, never
    overwriting, and record the move in trash/_manifest.jsonl so it can be
    restored. A symlink is moved as a link; its target is left alone."""
    path = Path(os.path.abspath(path))
    library, trash = Path(os.path.abspath(library)), Path(os.path.abspath(trash))
    try:
        rel = path.relative_to(library)
    except ValueError:
        rel = Path(path.name)
    dest = trash / reason / rel
    stem, n = dest, 1
    while dest.exists() or dest.is_symlink():
        dest = stem.with_name(f"{stem.stem} ({n}){stem.suffix}")
        n += 1
    safe_move(path, dest)
    with open(trash / MANIFEST, "a", encoding="utf-8", errors="surrogateescape") as f:
        f.write(json.dumps({"time": now_iso(), "reason": reason,
                            "original": str(path), "trashed": str(dest)}) + "\n")
    return dest


def read_manifest(trash: Path) -> list[dict]:
    p = Path(trash) / MANIFEST
    if not p.exists():
        return []
    with open(p, encoding="utf-8", errors="surrogateescape") as f:
        return [json.loads(l) for l in f if l.strip()]


# ---------- safe in-place rewrite ----------

def temp_beside(path: Path, ext: str | None = None) -> Path:
    """A hidden temp path in the same folder (same filesystem), so the final
    swap is an atomic rename. The process id keeps parallel runs apart."""
    path = Path(os.path.abspath(path))
    ext = ext or path.suffix
    return path.with_name(f".{path.stem}{TEMP_MARK}-{os.getpid()}{ext}")


def verify_output(src: Path, out: Path, expect_duration: float | None,
                  tolerance: float = 0.5) -> str | None:
    """Return None if out looks complete, else a reason. Checks size, MP4
    atoms, that ffprobe opens it, and that its duration matches."""
    if not out.exists() or out.stat().st_size == 0:
        return "output missing or empty"
    if out.suffix.lower() in MP4_FAMILY:
        _, problem = mp4_atoms(out)
        if problem and problem != "trailing_bytes":
            return f"output MP4 structure: {problem}"
    try:
        probe = ffprobe(out)
    except ToolError as e:
        return f"output unreadable: {e}"
    if not audio_streams(probe):
        return "output has no audio stream"
    d = duration_of(probe)
    if expect_duration is not None and d is not None and abs(d - expect_duration) > tolerance:
        return f"output duration {d:.2f}s differs from source {expect_duration:.2f}s"
    return None


# Container bookkeeping ffmpeg rewrites on every remux; not user tags.
NOT_TAGS = {"encoder", "major_brand", "minor_version", "compatible_brands",
            "creation_time", "handler_name", "vendor_id", "encoder_options"}

# Raw tag keys (ID3 frame ids, MP4 ilst atoms) behind each field retag.py
# writes. Keys in one group stand in for each other (ID3v2.4 TDRC becomes
# v2.3 TYER on a rewrite).
_ID3_FIELDS = {"title": {"TIT2"}, "artist": {"TPE1"}, "album": {"TALB"},
               "album_artist": {"TPE2"}, "track": {"TRCK"}, "disc": {"TPOS"},
               "date": {"TYER", "TDRC", "TDAT", "TIME", "TRDA", "TORY", "TDOR"},
               "genre": {"TCON"}, "comment": {"COMM"}, "composer": {"TCOM"},
               "compilation": {"TCMP"}}
_MP4_FIELDS = {"title": {"\xa9nam"}, "artist": {"\xa9ART"}, "album": {"\xa9alb"},
               "album_artist": {"aART"}, "track": {"trkn"}, "disc": {"disk"},
               "date": {"\xa9day"}, "genre": {"\xa9gen", "gnre"}, "comment": {"\xa9cmt"},
               "composer": {"\xa9wrt"}, "compilation": {"cpil"}}
_RAW_IGNORE = {"TSSE", "\xa9too"}  # encoder stamps ffmpeg rewrites


def _id3_frame_ids(data: bytes) -> set[str] | None:
    if data[:3] != b"ID3" or len(data) < 10 or data[3] not in (3, 4):
        return None
    ver, flags = data[3], data[5]
    end = 10 + ((data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9])
    pos = 10
    if flags & 0x40:  # extended header
        n = struct.unpack(">I", data[10:14])[0]
        pos += (n + 4) if ver == 3 else ((data[10] << 21) | (data[11] << 14) | (data[12] << 7) | data[13])
    ids = set()
    while pos + 10 <= min(end, len(data)):
        fid = data[pos:pos + 4]
        if not re.fullmatch(rb"[A-Z0-9]{4}", fid):
            break
        b = data[pos + 4:pos + 8]
        size = struct.unpack(">I", b)[0] if ver == 3 else \
            (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]
        ids.add(fid.decode())
        pos += 10 + size
    return ids


def _children(data: bytes, start: int, end: int) -> Iterator[tuple[str, int, int]]:
    """(type, payload start, atom end) for each MP4 atom in data[start:end]."""
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        head = 8
        if size == 1:
            size, head = struct.unpack(">Q", data[pos + 8:pos + 16])[0], 16
        elif size == 0:
            size = end - pos
        if size < head or pos + size > end:
            return
        yield kind.decode("latin-1"), pos + head, pos + size
        pos += size


def _mp4_ilst_keys(path: Path) -> set[str] | None:
    """Keys of the iTunes-style tag atoms in moov/udta/meta/ilst, with
    freeform atoms named '----:<mean>:<name>' (e.g. ----:com.apple.iTunes:iTunSMPB)."""
    atoms, problem = mp4_atoms(path)
    moov = next(((off, size) for name, off, size in atoms if name == "moov"), None)
    if moov is None or moov[1] > 64 << 20:
        return None
    with open(path, "rb") as f:
        f.seek(moov[0])
        data = f.read(moov[1])
    node = (8, len(data))
    for want in ("udta", "meta"):
        node = next(((s, e) for k, s, e in _children(data, *node) if k == want), None)
        if node is None:
            return set()
    s, e = node
    if data[s + 4:s + 8] != b"hdlr":  # ISO meta is a full box: skip version/flags
        s += 4
    ilst = next(((cs, ce) for k, cs, ce in _children(data, s, e) if k == "ilst"), None)
    if ilst is None:
        return set()
    keys = set()
    for k, cs, ce in _children(data, *ilst):
        if k == "----":
            parts = {sk: data[ss + 4:se].decode("utf-8", "replace")
                     for sk, ss, se in _children(data, cs, ce) if sk in ("mean", "name")}
            k = f"----:{parts.get('mean', '')}:{parts.get('name', '')}"
        keys.add(k)
    return keys


def raw_tag_keys(path: Path) -> set[str] | None:
    """The tag keys actually stored in the file, including ones ffprobe never
    shows (MP3 POPM ratings, UFID ids; MP4 freeform atoms). None when the
    format isn't one this reads."""
    try:
        if Path(path).suffix.lower() in MP4_FAMILY:
            return _mp4_ilst_keys(Path(path))
        with open(path, "rb") as f:
            head = f.read(10)
            if head[:3] != b"ID3":
                return None
            size = (head[6] << 21) | (head[7] << 14) | (head[8] << 7) | head[9]
            return _id3_frame_ids(head + f.read(size))
    except (OSError, struct.error, IndexError):
        return None


def lost_tags(before: dict, after: dict, changed: Iterable[str] = (),
              src: Path | None = None, out: Path | None = None) -> list[str]:
    """Tags present before a rewrite that are gone or different after it,
    ignoring the fields deliberately changed. ffmpeg cannot carry some tags
    (MP4 freeform atoms such as iTunSMPB gapless info, MP3 POPM ratings and
    UFID ids), and ffprobe doesn't even show some of them, so with src and
    out the raw tag keys in both files are compared as well."""
    changed = set(changed)
    lost = {k for k, v in before.items()
            if k not in changed and k not in NOT_TAGS and after.get(k) != v}
    if src is not None and out is not None:
        rb, ra = raw_tag_keys(src), raw_tag_keys(out)
        if rb is not None and ra is not None:
            groups = list((_MP4_FIELDS if Path(src).suffix.lower() in MP4_FAMILY
                           else _ID3_FIELDS).items())
            for k in rb - ra - _RAW_IGNORE:
                field = next((f for f, keys in groups if k in keys), None)
                if field is None:
                    lost.add(k)
                elif field not in changed and not (dict(groups)[field] & ra):
                    lost.add(k)
    return sorted(lost)


def atomic_swap(tmp: Path, target: Path, keep_mode_of: Path | None = None) -> None:
    if keep_mode_of is not None and keep_mode_of.exists():
        shutil.copymode(str(keep_mode_of), str(tmp))
    os.replace(tmp, target)


def remove_quiet(p: Path) -> None:
    try:
        p.unlink()
    except FileNotFoundError:
        pass


def print_err(*a) -> None:
    print(*a, file=sys.stderr)
