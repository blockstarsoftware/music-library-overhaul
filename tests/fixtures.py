#!/usr/bin/env python3
"""Build a small synthetic music library with every problem the skill handles.

All audio is generated sine tones; nothing here is real music. Used by the
tests, and handy for trying the scripts safely:
    python3 tests/fixtures.py /tmp/demo-library
creates /tmp/demo-library/library (the "serious" tier) and
/tmp/demo-library/others (a long tail to cull).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CODECS = {
    "alac": ["-c:a", "alac"],
    "aac": ["-c:a", "aac", "-b:a", "96k"],
    "mp3": ["-c:a", "libmp3lame", "-b:a", "96k"],
    "mp3low": ["-ar", "8000", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "8k"],
    "flac": ["-c:a", "flac"],
    "s16": ["-c:a", "pcm_s16le"],
    "s16be": ["-c:a", "pcm_s16be"],
    "u8": ["-c:a", "pcm_u8"],
    "s24be": ["-c:a", "pcm_s24be"],
}
FREQ = [220, 262, 294, 330, 349, 392, 440, 494, 523]


def ff(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y"] + args, check=True)


def tone(path: Path, seconds: float, codec: str, tags: dict | None = None, n: int = 0,
         fmt: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = []
    for k, v in (tags or {}).items():
        meta += ["-metadata", f"{k}={v}"]
    out = ["-f", fmt] if fmt else []
    extra = ["-id3v2_version", "3"] if codec.startswith("mp3") else []
    ff(["-f", "lavfi", "-i", f"sine=frequency={FREQ[n % len(FREQ)]}:duration={seconds}"]
       + CODECS[codec] + meta + extra + out + [str(path)])
    return path


def truncate(path: Path, keep: float = 0.5) -> None:
    data = path.read_bytes()
    path.write_bytes(data[: int(len(data) * keep)])


def build(root: Path) -> tuple[Path, Path]:
    lib, others = root / "library", root / "others"
    bc = lib / "The Black Crowes"

    # Phase 1: live shows with blank or messy tags, one with disc folders.
    tone(bc / "1996_12_03 Little Rock, AR SBD" / "01 Remedy.mp3", 3, "mp3", n=1)
    tone(bc / "1996_12_03 Little Rock, AR SBD" / "02 Jealous Again.mp3", 3, "mp3", n=2)
    show = bc / "10-22-2005 Fonda Theater"
    for d, names in ((1, ["Sting Me", "Thorn In My Pride"]), (2, ["Hard To Handle"])):
        for i, t in enumerate(names, 1):
            tone(show / f"CD{d}" / f"{i:02d} {t}.m4a", 2, "aac", n=i,
                 tags={"album": "10/22/2005 Fonda Theater", "artist": "The Black Crowes",
                       "title": t, "track": str(i)})

    # Phase 4: a lossless album with lossy leftovers (false-lossless).
    am = bc / "Amorica"
    base = {"artist": "The Black Crowes", "album": "Amorica"}
    tone(am / "01 Gone.m4a", 5, "alac", dict(base, title="Gone", track="1/3"), n=1)
    tone(am / "02 A Conspiracy.m4a", 6, "alac", dict(base, title="A Conspiracy", track="2/3"), n=2)
    tone(am / "03 Wiser Time.m4a", 7, "alac", dict(base, title="Wiser Time", track="3/3"), n=3)
    tone(am / "A Conspiracy (single).m4a", 6, "aac", dict(base, title="A Conspiracy"), n=2)
    tone(am / "Wiser Tyme.mp3", 7, "mp3", dict(base, title="Wiser Tyme", track="3"), n=3)
    tone(am / "Wiser Time (Live).mp3", 12, "mp3", dict(base, title="Wiser Time (Live)"), n=3)

    # Duplicate albums: a redundant lossy copy and a different mastering.
    sg = lib / "Soundgarden"
    for folder, codec, durs, album in (
            ("Superunknown", "alac", (4, 5), "Superunknown"),
            ("Superunknown (copy)", "aac", (4, 5), "Superunknown"),
            ("Superunknown (2014 Remaster)", "alac", (4.6, 5.7), "Superunknown (2014 Remaster)")):
        for i, (t, d) in enumerate(zip(("Let Me Drown", "My Wave"), durs), 1):
            tone(sg / folder / f"{i:02d} {t}.m4a", d, codec,
                 {"artist": "Soundgarden", "album": album, "title": t, "track": str(i)}, n=i)

    # A stray lossy single of a song owned losslessly elsewhere.
    tone(lib / "Prince" / "Purple Rain" / "Purple Rain.m4a", 5, "alac",
         {"artist": "Prince", "album": "Purple Rain", "title": "Purple Rain"}, n=4)
    tone(lib / "Prince" / "Singles" / "Purple Rain.mp3", 5, "mp3",
         {"artist": "Prince", "album": "Singles", "title": "Purple Rain"}, n=4)

    # Split artists: accents, curly quotes, a typo, 'The', featured artists.
    tone(lib / "Beyoncé" / "Lemonade" / "Formation.m4a", 3, "alac",
         {"artist": "Beyoncé", "album": "Lemonade", "title": "Formation"})
    tone(lib / "Beyonce" / "Singles" / "Halo.mp3", 3, "mp3",
         {"artist": "Beyonce", "album": "Singles", "title": "Halo"})
    tone(lib / "Jane’s Addiction" / "Ritual" / "Stop.m4a", 3, "alac",
         {"artist": "Jane’s Addiction", "album": "Ritual", "title": "Stop"})
    tone(lib / "Janes Addiction" / "Nothing's Shocking" / "Jane Says.m4a", 3, "alac",
         {"artist": "Jane's Addiction", "album": "Nothing's Shocking", "title": "Jane Says"})
    tone(lib / "Wolfgang Amadeus Mozart" / "Sonatas" / "K. 309.flac", 3, "flac",
         {"artist": "Wolfgang Amadeus Mozart", "album": "Sonatas", "title": "K. 309"})
    tone(lib / "Wolfgang Amadeus Mozart" / "Sonatas" / "K. 310.flac", 3, "flac",
         {"artist": "Wolfang Amadeus Mozart", "album": "Sonatas", "title": "K. 310"})
    tone(lib / "Cream" / "Disraeli Gears" / "Sunshine.m4a", 3, "alac",
         {"artist": "Cream", "album": "Disraeli Gears", "title": "Sunshine"})
    tone(lib / "The Cream" / "Wheels of Fire" / "White Room.m4a", 3, "alac",
         {"artist": "Cream", "album": "Wheels of Fire", "title": "White Room"})
    tone(lib / "En Vogue" / "Funky Divas" / "Free Your Mind.m4a", 4, "alac",
         {"artist": "En Vogue", "album": "Funky Divas", "title": "Free Your Mind"})
    tone(lib / "En Vogue with Kelly Clarkson" / "Live" / "Free Your Mind Live.m4a", 5, "aac",
         {"artist": "En Vogue with Kelly Clarkson", "album": "Live", "title": "Free Your Mind Live"})

    # Phase 5: spoken word, and a long classical work that must not be flagged.
    tone(lib / "Alan Watts" / "Lectures" / "Talk 1.mp3", 1300, "mp3low",
         {"artist": "Alan Watts", "album": "Lectures", "title": "Talk 1", "genre": "Speech"})
    tone(lib / "Wolfgang Amadeus Mozart" / "Symphonies" / "Symphony No. 40.mp3", 1300, "mp3low",
         {"artist": "Wolfgang Amadeus Mozart", "album": "Symphonies",
          "title": "Symphony No. 40", "genre": "Classical"})

    # Phase 7: real video, audio in a video wrapper, art-only "video".
    rr = lib / "Robert Randolph" / "2019 TV Clip.mp4"
    rr.parent.mkdir(parents=True, exist_ok=True)
    ff(["-f", "lavfi", "-i", "sine=frequency=330:duration=3", "-f", "lavfi", "-i",
        "testsrc=s=160x120:d=3:r=10", "-c:a", "aac", "-c:v", "mpeg4", "-shortest", str(rr)])
    tone(lib / "En Vogue" / "Live" / "Free Your Mind (Live).mov", 4, "aac",
         {"artist": "En Vogue", "title": "Free Your Mind (Live)"}, n=5, fmt="mov")
    art_src = tone(root / "tmp" / "ss.m4a", 3, "aac", {"artist": "Kanye West", "title": "Sunday Service"})
    png = root / "tmp" / "cover.png"
    ff(["-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1", "-frames:v", "1", str(png)])
    kw = lib / "Kanye West" / "Sunday Service.mp4"
    kw.parent.mkdir(parents=True, exist_ok=True)
    ff(["-i", str(art_src), "-i", str(png), "-map", "0", "-map", "1", "-c", "copy",
        "-disposition:v:0", "attached_pic", str(kw)])

    # Phase 8: PCM to convert (16-bit AIFF, 8-bit WAV), and a DRM stand-in.
    tone(lib / "Billy Preston" / "Unknown Album" / "I Wrote a Simple Song.aiff", 3, "s16be",
         {"artist": "Billy Preston", "title": "I Wrote a Simple Song"}, fmt="aiff")
    tone(lib / "Bungie" / "Marathon 2 Theme.wav", 3, "u8",
         {"artist": "Bungie", "title": "Marathon 2 Theme"})
    tone(lib / "Bungie" / "Durandal 24bit.aiff", 3, "s24be",
         {"artist": "Bungie", "title": "Durandal"}, fmt="aiff")
    drm = tone(lib / "Queen" / "Fat Bottomed Girls.m4a", 3, "aac",
               {"artist": "Queen", "title": "Fat Bottomed Girls"})
    drm.rename(drm.with_suffix(".m4p"))

    # Phase 0: damage.
    t = tone(lib / "Tedeschi Trucks Band" / "2019.04.14 RuhrCongress" / "2-09 I Want More.m4a", 6,
             "aac", {"artist": "Tedeschi Trucks Band", "title": "I Want More"})
    truncate(t)
    t = tone(lib / "Linkin Park" / "Hybrid Theory" / "Crawling.mp3", 6, "mp3",
             {"artist": "Linkin Park", "album": "Hybrid Theory", "title": "Crawling"})
    truncate(t)
    odd = tone(lib / "Odd Files" / "track.mp3", 3, "mp3", {"artist": "Odd", "title": "Track"})
    odd.rename(odd.with_suffix(".m"))
    (lib / "Odd Files" / "empty.mp3").write_bytes(b"")

    # Phase 2: a long tail with a compilation and a generic album name.
    tone(others / "Artist A" / "Song A.mp3", 2, "mp3", {"artist": "Artist A", "title": "Song A"})
    tone(others / "Artist B" / "Song B (Live).mp3", 2, "mp3",
         {"artist": "Artist B", "title": "Song B (Live)", "album": "2001.05.05 Club | AUD", "genre": "Rock"})
    tone(others / "Artist C" / "Song C.mp3", 2, "mp3",
         {"artist": "Artist C", "title": "Song C", "genre": "Hip-Hop"})
    for a in ("D", "E"):
        tone(others / f"Artist {a}" / f"Comp {a}.mp3", 2, "mp3",
             {"artist": f"Artist {a}", "title": f"Comp {a}", "album": "Billboard Top 100 of 1971"})
    for a in ("F", "G"):
        tone(others / f"Artist {a}" / "Greatest Hits" / f"Hit {a}.mp3", 2, "mp3",
             {"artist": f"Artist {a}", "title": f"Hit {a}", "album": "Greatest Hits"})

    for p in (root / "tmp").glob("*"):
        p.unlink()
    (root / "tmp").rmdir()
    return lib, others


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: fixtures.py OUTDIR")
    lib, others = build(Path(sys.argv[1]))
    print(f"Built {lib} and {others}")
