#!/usr/bin/env python3
"""End-to-end tests: every script run from the command line against the
synthetic library in fixtures.py. Needs ffmpeg/ffprobe on PATH.

    python3 tests/test_scripts.py        (about a minute)
"""
from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))
import common as c  # noqa: E402
import fixtures  # noqa: E402
import plan_shows  # noqa: E402

PRISTINE: Path | None = None


def setUpModule():
    global PRISTINE
    PRISTINE = Path(tempfile.mkdtemp(prefix="mlo-pristine-"))
    fixtures.build(PRISTINE)


def tearDownModule():
    shutil.rmtree(PRISTINE, ignore_errors=True)


def run(script: str, *args, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                          capture_output=True, text=True, cwd=cwd)


def rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def tags(path: Path) -> dict:
    return c.tags_of(c.ffprobe(path))


class Base(unittest.TestCase):
    """Each test gets its own copy of the library, so tests that write are
    independent of each other."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mlo-test-"))
        shutil.copytree(PRISTINE, self.tmp / "w")
        self.lib = self.tmp / "w" / "library"
        self.others = self.tmp / "w" / "others"
        self.trash = self.tmp / "trash"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ok(self, cp, codes=(0,)):
        self.assertIn(cp.returncode, codes, cp.stdout + cp.stderr)
        return cp.stdout


class Helpers(unittest.TestCase):
    def test_artist_key_collapses_spellings(self):
        k = c.artist_key
        self.assertEqual(k("Beyoncé"), k("Beyonce"))
        self.assertEqual(k("Jane’s Addiction"), k("Jane's Addiction"))
        self.assertEqual(k("The Cream"), k("Cream"))
        self.assertEqual(k("Simon & Garfunkel"), k("Simon and Garfunkel"))
        self.assertNotEqual(k("Jimmy Page & The Black Crowes"), k("The Black Crowes"))

    def test_title_key_strips_version_markers(self):
        self.assertEqual(c.title_key("Wiser Time (Live)"), c.title_key("Wiser Time"))
        self.assertEqual(c.title_key("Song - 2011 Remaster"), c.title_key("Song"))
        self.assertEqual(c.title_key("03 Song [Remastered]"), c.title_key("Song"))

    def test_parse_date_formats(self):
        p = plan_shows.parse_date
        self.assertEqual(p("1996_12_03 Little Rock, AR")[0], "1996.12.03")
        self.assertEqual(p("10-22-2005 Fonda Theater")[0], "2005.10.22")
        self.assertEqual(p("10/22/2005 Fonda")[0], "2005.10.22")
        self.assertEqual(p("gd77-05-08")[0], "1977.05.08")
        self.assertEqual(p("Show 2019.04.14 RuhrCongress")[0], "2019.04.14")
        self.assertEqual(p("No date here")[0], "")
        self.assertEqual(p("1996_12_03 Little Rock, AR")[1], "Little Rock, AR")

    def test_album_unit_folds_disc_folders(self):
        self.assertEqual(c.album_unit("/a/Show/CD2/01.m4a"), Path("/a/Show"))
        self.assertEqual(c.album_unit("/a/Show/Disc 1/01.m4a"), Path("/a/Show"))
        self.assertEqual(c.album_unit("/a/Album/01.m4a"), Path("/a/Album"))


class Integrity(Base):
    def test_scan_finds_every_planted_fault(self):
        out = self.tmp / "scan.csv"
        self.ok(run("scan_integrity.py", self.lib, "--out", out), codes=(1,))
        by = {}
        for r in rows(out):
            by.setdefault(Path(r["path"]).name, set()).add(r["status"])
        self.assertIn("truncated", by["2-09 I Want More.m4a"])
        self.assertIn("length_mismatch", by["Crawling.mp3"])
        self.assertIn("wrong_extension", by["track.m"])
        self.assertIn("zero_byte", by["empty.mp3"])
        self.assertIn("drm", by["Fat Bottomed Girls.m4p"])
        self.assertEqual(by["01 Gone.m4a"], {"ok"})
        self.assertEqual(by["Formation.m4a"], {"ok"})

    def test_repair_extension_and_header(self):
        self.ok(run("repair.py", "extensions", self.lib, "--apply"))
        self.assertTrue((self.lib / "Odd Files" / "track.mp3").exists())
        crawl = self.lib / "Linkin Park" / "Hybrid Theory" / "Crawling.mp3"
        before = crawl.read_bytes()
        self.ok(run("repair.py", "mp3-header", crawl, "--apply"))
        decoded, _ = c.decode_check(crawl)
        header = c.duration_of(c.ffprobe(crawl))
        self.assertLess(abs(header - decoded), 0.5)
        self.assertEqual(tags(crawl)["title"], "Crawling")
        self.assertNotEqual(before, crawl.read_bytes())


class Retag(Base):
    def test_retag_writes_verifies_and_keeps_art(self):
        song = self.lib / "Kanye West" / "Sunday Service.mp4"
        mp3 = self.lib / "Prince" / "Singles" / "Purple Rain.mp3"
        flac = self.lib / "Wolfgang Amadeus Mozart" / "Sonatas" / "K. 310.flac"
        plan = self.tmp / "plan.csv"
        c.write_csv(plan, [
            {"path": song, "album": "Coachella | Webcast", "track": "1/1"},
            {"path": mp3, "artist": "Prince & The Revolution", "disc": "1/2", "genre": "<clear>"},
            {"path": flac, "artist": "Wolfgang Amadeus Mozart", "date": "1777"},
        ], ["path", "artist", "album", "track", "disc", "date", "genre"])
        out = self.ok(run("retag.py", plan))
        self.assertIn("Dry run", out)
        self.assertEqual(tags(mp3)["artist"], "Prince")  # dry run wrote nothing
        self.ok(run("retag.py", plan, "--apply"))
        self.assertEqual(tags(song)["album"], "Coachella | Webcast")
        self.assertEqual(tags(song)["track"], "1/1")
        self.assertTrue(any(c.is_art_stream(s) for s in c.ffprobe(song)["streams"]))
        self.assertEqual(tags(mp3)["artist"], "Prince & The Revolution")
        self.assertEqual(tags(mp3)["disc"], "1/2")
        self.assertEqual(tags(mp3).get("title"), "Purple Rain")  # untouched tags survive
        self.assertEqual(tags(flac)["artist"], "Wolfgang Amadeus Mozart")
        self.assertFalse(list(self.lib.rglob(f"*{c.TEMP_MARK}*")))
        log = rows(plan.with_suffix(".log.csv"))
        self.assertEqual({r["status"] for r in log}, {"ok"})
        out = self.ok(run("retag.py", plan, "--apply", "--resume"))
        self.assertIn("skipped 3", out)

    def test_retag_refuses_damaged_and_untaggable(self):
        bad = self.lib / "Tedeschi Trucks Band" / "2019.04.14 RuhrCongress" / "2-09 I Want More.m4a"
        wav = self.lib / "Bungie" / "Marathon 2 Theme.wav"
        before = bad.read_bytes()
        plan = self.tmp / "plan.csv"
        c.write_csv(plan, [{"path": bad, "title": "X"}, {"path": wav, "title": "Y"}], ["path", "title"])
        self.ok(run("retag.py", plan, "--apply"), codes=(1,))
        self.assertEqual(before, bad.read_bytes())
        self.assertIn("convert to ALAC", "".join(r["detail"] for r in rows(plan.with_suffix(".log.csv"))))


class Audits(Base):
    def test_codec_audit_finds_false_lossless(self):
        albums = self.tmp / "albums.csv"
        self.ok(run("audit_codecs.py", self.lib, "--albums", albums))
        by = {Path(r["folder"]).name: r for r in rows(albums)}
        self.assertEqual(by["Amorica"]["verdict"], "mixed")
        self.assertEqual(by["Superunknown (copy)"]["verdict"], "lossy")
        self.assertEqual(by["Superunknown"]["verdict"], "lossless")
        self.assertEqual(by["10-22-2005 Fonda Theater"]["tracks"], "3")  # discs folded

    def test_mixed_duplicates_use_durations(self):
        out, tl = self.tmp / "mixed.csv", self.tmp / "dupes.csv"
        self.ok(run("find_duplicates.py", "mixed", self.lib, "--out", out, "--trash-list", tl))
        v = {Path(r["path"]).name: r["verdict"] for r in rows(out)}
        self.assertEqual(v["A Conspiracy (single).m4a"], "duplicate of lossless track")
        self.assertEqual(v["Wiser Tyme.mp3"], "duplicate of lossless track")  # caught by track number
        self.assertEqual(v["Wiser Time (Live).mp3"], "different version")  # live take kept
        self.assertEqual(len(rows(tl)), 2)

    def test_album_duplicates_keep_remasters(self):
        out = self.tmp / "albums.csv"
        self.ok(run("find_duplicates.py", "albums", self.lib, "--out", out))
        v = {Path(r["folder"]).name: r["verdict"] for r in rows(out)}
        self.assertEqual(v["Superunknown"], "best copy")
        self.assertEqual(v["Superunknown (copy)"], "redundant copy")
        self.assertTrue(v["Superunknown (2014 Remaster)"].startswith("different"))
        self.assertNotIn("CD1", v)

    def test_track_duplicates_across_folders(self):
        out = self.tmp / "tracks.csv"
        self.ok(run("find_duplicates.py", "tracks", self.lib, "--out", out))
        names = {Path(r["path"]).name for r in rows(out)}
        self.assertIn("Purple Rain.mp3", names)
        self.assertNotIn("Wiser Time (Live).mp3", names)

    def test_split_artists(self):
        out, plan = self.tmp / "split.csv", self.tmp / "plan.csv"
        self.ok(run("find_split_artists.py", self.lib, "--out", out, "--plan", plan))
        f = rows(out)
        variants = " ".join(r["variants"] for r in f)
        self.assertIn("Beyoncé", variants)
        self.assertIn("The Cream", variants)
        self.assertTrue(any(r["kind"] == "typo" and "Wolfang" in r["variants"] for r in f))
        self.assertTrue(any(r["kind"] == "featured" and r["canonical"] == "En Vogue" for r in f))
        p = {Path(r["path"]).name: r["artist"] for r in rows(plan)}
        self.assertEqual(p["Halo.mp3"], "Beyoncé")
        self.assertEqual(p["Stop.m4a"], "Jane's Addiction")

    def test_nonmusic_skips_classical(self):
        out = self.tmp / "nm.csv"
        self.ok(run("find_nonmusic.py", self.lib, "--out", out))
        folders = [r["folder"] for r in rows(out)]
        self.assertTrue(any(f.endswith("Alan Watts/Lectures") for f in folders))
        self.assertFalse(any("Symphonies" in f for f in folders))


class Rewrites(Base):
    def test_videos_sorted_and_rewrapped(self):
        videos = self.tmp / "Music Videos"
        self.ok(run("probe_videos.py", self.lib, "--apply", "--videos", videos, "--trash", self.trash))
        self.assertTrue((videos / "Robert Randolph" / "2019 TV Clip.mp4").exists())
        self.assertFalse((self.lib / "Robert Randolph" / "2019 TV Clip.mp4").exists())
        for p in (self.lib / "En Vogue" / "Live" / "Free Your Mind (Live).m4a",
                  self.lib / "Kanye West" / "Sunday Service.m4a"):
            self.assertTrue(p.exists(), p)
            self.assertFalse(c.real_video_streams(c.ffprobe(p)))
        self.assertTrue((self.trash / "Rewrapped video containers" / "Kanye West" / "Sunday Service.mp4").exists())

    def test_pcm_conversion_is_verified_lossless(self):
        self.ok(run("convert_lossless.py", self.lib, "--apply", "--trash", self.trash))
        for name, folder in (("I Wrote a Simple Song.m4a", "Billy Preston/Unknown Album"),
                             ("Marathon 2 Theme.m4a", "Bungie"), ("Durandal 24bit.m4a", "Bungie")):
            p = self.lib / folder / name
            self.assertTrue(p.exists(), p)
            self.assertEqual(c.ffprobe(p)["streams"][0]["codec_name"], "alac")
        self.assertEqual(tags(self.lib / "Bungie" / "Marathon 2 Theme.m4a")["title"], "Marathon 2 Theme")
        self.assertFalse(list(self.lib.rglob("*.aiff")) + list(self.lib.rglob("*.wav")))
        self.assertEqual(len(c.read_manifest(self.trash)), 3)

    def test_trash_restore_round_trip(self):
        target = self.lib / "Prince" / "Singles" / "Purple Rain.mp3"
        lst = self.tmp / "rm.csv"
        c.write_csv(lst, [{"path": target, "reason": "Lossy duplicates"}], ["path", "reason"])
        self.ok(run("trash.py", "move", lst, "--library", self.lib, "--trash", self.trash, "--apply"))
        self.assertFalse(target.exists())
        self.assertTrue((self.trash / "Lossy duplicates" / "Prince" / "Singles" / "Purple Rain.mp3").exists())
        self.ok(run("trash.py", "restore", "--trash", self.trash, "--apply"))
        self.assertTrue(target.exists())


class Cull(Base):
    def test_cull_and_streaming_playlists(self):
        sheet = self.tmp / "cull.csv"
        self.ok(run("cull_sheet.py", "build", self.others, "--sheet", sheet))
        r = rows(sheet)
        comps = [x for x in r if x["kind"] == "compilation"]
        self.assertEqual([x["name"] for x in comps], ["Billboard Top 100 of 1971"])
        self.assertIn("Artist F", [x["name"] for x in r])  # "Greatest Hits" is not a comp
        actions = {"Artist A": "D", "Artist B": "s", "Artist C": "3", "Artist F": "U",
                   "Billboard Top 100 of 1971": "K"}
        for x in r:
            x["action"] = actions.get(x["name"], "")
        c.write_csv(sheet, r, list(r[0]))
        lists = self.tmp / "lists"
        self.ok(run("cull_sheet.py", "apply", sheet, "--trash", self.trash, "--lists", lists))
        self.assertTrue((self.others / "Artist A" / "Song A.mp3").exists())  # dry run
        self.ok(run("cull_sheet.py", "apply", sheet, "--trash", self.trash, "--lists", lists, "--apply"))
        self.assertTrue((self.trash / "Deleted (discarded)" / "Artist A" / "Song A.mp3").exists())
        self.assertTrue((self.trash / "Streaming-listed (removed from library)" / "Artist C" / "Song C.mp3").exists())
        self.assertTrue((self.others / "Artist D" / "Comp D.mp3").exists())
        self.assertTrue((self.others / "Artist F" / "Greatest Hits" / "Hit F.mp3").exists())
        stream = rows(lists / "streaming_list.csv")
        self.assertEqual(sorted(x["title"] for x in stream), ["Song B (Live)", "Song C"])
        self.assertEqual([x["title"] for x in rows(lists / "upgrade_wanted.csv")], ["Hit F"])

        pl = self.tmp / "playlists"
        out = self.ok(run("streaming_csv.py", lists / "streaming_list.csv", "--out-dir", pl,
                          "--by-genre", "--prefix", "Online ", "--strip-versions",
                          "--blank-bootleg-albums"))
        self.assertIn("live bootlegs", out)
        rock = rows(pl / "Online Pop, Rock & Alternative.csv")
        self.assertEqual(rock, [{"title": "Song B", "artist": "Artist B", "album": "", "isrc": "",
                                 "platform": "", "trackId": "", "duration": "", "addedDate": "",
                                 "url": ""}])
        with open(pl / "Online Rap & Hip-Hop.csv", encoding="utf-8") as f:
            self.assertEqual(f.readline().strip(),
                             "title,artist,album,isrc,platform,trackId,duration,addedDate,url")


class Playlists(Base):
    def test_both_action_and_playlist_options(self):
        sheet = self.tmp / "cull.csv"
        self.ok(run("cull_sheet.py", "build", self.others, "--sheet", sheet))
        r = rows(sheet)
        actions = {"Artist A": "B", "Artist B": "S", "Artist C": "s"}
        for x in r:
            x["action"] = actions.get(x["name"], "")
        c.write_csv(sheet, r, list(r[0]))
        lists = self.tmp / "lists"
        self.ok(run("cull_sheet.py", "apply", sheet, "--trash", self.trash, "--lists", lists, "--apply"))
        self.assertTrue((self.others / "Artist A" / "Song A.mp3").exists())  # B stays local
        self.assertFalse((self.others / "Artist C" / "Song C.mp3").exists())
        stream = {x["title"]: x["local"] for x in rows(lists / "streaming_list.csv")}
        self.assertEqual(stream, {"Song A": "yes", "Song B (Live)": "no", "Song C": "no"})

        pl = self.tmp / "pl"
        out = self.ok(run("streaming_csv.py", lists / "streaming_list.csv", "--out-dir", pl,
                          "--txt", "--max-per-playlist", "2", "--strip-versions"))
        self.assertIn("Streaming Import (1 of 2): 2 tracks", out)
        self.assertEqual(sorted(p.name for p in pl.iterdir()),
                         ["Streaming Import (1 of 2).csv", "Streaming Import (1 of 2).txt",
                          "Streaming Import (2 of 2).csv", "Streaming Import (2 of 2).txt"])
        lines = (pl / "Streaming Import (1 of 2).txt").read_text().splitlines() + \
            (pl / "Streaming Import (2 of 2).txt").read_text().splitlines()
        self.assertEqual(sorted(lines), ["Artist A - Song A", "Artist B - Song B", "Artist C - Song C"])


class Shows(Base):
    def test_show_inventory_expand_and_retag(self):
        bc = self.lib / "The Black Crowes"
        shows, plan = self.tmp / "shows.csv", self.tmp / "plan.csv"
        self.ok(run("plan_shows.py", "inventory", bc, "--out", shows))
        by = {r["folder"]: r for r in rows(shows)}
        lr = by["1996_12_03 Little Rock, AR SBD"]
        self.assertEqual(lr["date"], "1996.12.03")
        self.assertEqual(lr["source_guess"], "SBD")
        self.assertEqual(lr["target_album"], "1996.12.03 Little Rock, AR | SBD")
        fonda = by["10-22-2005 Fonda Theater"]
        self.assertEqual((fonda["date"], fonda["discs"], fonda["tracks"]), ("2005.10.22", "2", "3"))
        out = []
        for r in rows(shows):
            if r["folder"] == "1996_12_03 Little Rock, AR SBD":
                r["target_album"] = "1996.12.03 Robinson Center Music Hall, Little Rock, AR | SBD"
                r["artist"] = "The Black Crowes"
            elif r["folder"] == "10-22-2005 Fonda Theater":
                r["target_album"] = "2005.10.22 Fonda Theatre, Los Angeles, CA | AUD"
            else:
                r["target_album"] = ""
            out.append(r)
        c.write_csv(shows, out, list(out[0]))
        self.ok(run("plan_shows.py", "expand", shows, "--artist-dir", bc, "--out", plan))
        p = {Path(r["path"]).name: r for r in rows(plan)}
        self.assertEqual(len(p), 5)
        self.assertEqual((p["01 Remedy.mp3"]["track"], p["01 Remedy.mp3"]["disc"]), ("1/2", "1"))
        self.assertEqual((p["01 Hard To Handle.m4a"]["disc"], p["01 Hard To Handle.m4a"]["track"]), ("2/2", "1/1"))
        self.assertEqual(p["02 Thorn In My Pride.m4a"]["track"], "2/2")
        self.ok(run("retag.py", plan, "--apply"))
        t = tags(bc / "1996_12_03 Little Rock, AR SBD" / "02 Jealous Again.mp3")
        self.assertEqual(t["album"], "1996.12.03 Robinson Center Music Hall, Little Rock, AR | SBD")
        self.assertEqual((t["track"], t["date"], t["artist"]), ("2/2", "1996", "The Black Crowes"))
        t = tags(bc / "10-22-2005 Fonda Theater" / "CD2" / "01 Hard To Handle.m4a")
        self.assertEqual((t["album"], t["disc"]), ("2005.10.22 Fonda Theatre, Los Angeles, CA | AUD", "2/2"))


def add_freeform_atom(path: Path, mean: str, name: str, value: str) -> None:
    """Append an iTunes freeform ('----') tag atom to an M4A whose moov atom
    comes last, as ffmpeg writes them, fixing the parent atoms' sizes."""
    import struct
    data = bytearray(path.read_bytes())

    def box(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", 8 + len(payload)) + kind + payload

    atom = box(b"----", box(b"mean", b"\0\0\0\0" + mean.encode())
               + box(b"name", b"\0\0\0\0" + name.encode())
               + box(b"data", struct.pack(">II", 1, 0) + value.encode()))
    chain, pos, end = [], 0, len(data)
    for want in (b"moov", b"udta", b"meta", b"ilst"):
        while pos < end:
            size, kind = struct.unpack(">I4s", data[pos:pos + 8])
            if kind == want:
                break
            pos += size
        else:
            raise AssertionError(f"no {want!r} atom")
        chain.append(pos)
        end, pos = pos + size, pos + 8 + (4 if want == b"meta" else 0)
    assert end == len(data) or chain[0] + struct.unpack(">I", data[chain[0]:chain[0] + 4])[0] == len(data)
    data[end:end] = atom
    for off in chain:
        size = struct.unpack(">I", data[off:off + 4])[0]
        data[off:off + 4] = struct.pack(">I", size + len(atom))
    path.write_bytes(bytes(data))


def id3_with_rating(mpeg: Path, out: Path) -> None:
    """An MP3 with TIT2 plus a POPM rating and a UFID id: frames ffprobe never shows."""
    import struct

    def frame(fid: str, body: bytes) -> bytes:
        return fid.encode() + struct.pack(">I", len(body)) + b"\0\0" + body

    frames = frame("TIT2", b"\0Rated") + frame("POPM", b"me@example.com\0\xff\0\0\0\x07") + \
        frame("UFID", b"http://musicbrainz.org\0abc")
    n = len(frames)
    size = bytes([(n >> 21) & 127, (n >> 14) & 127, (n >> 7) & 127, n & 127])
    out.write_bytes(b"ID3\x03\0\0" + size + frames + mpeg.read_bytes())


class ReviewRegressions(Base):
    """Cases an independent review found, each of which would have removed or
    mislabeled good music."""

    def test_truncated_flac_is_caught_and_protects_its_lossy_copy(self):
        album = self.tmp / "lib" / "Artist" / "Album"
        flac = fixtures.tone(album / "01 Song.flac", 20, "flac", {"title": "Song", "artist": "A", "album": "Album"})
        fixtures.tone(album / "Song.mp3", 20, "mp3", {"title": "Song", "artist": "A", "album": "Album"})
        fixtures.truncate(flac, 0.25)
        scan = self.tmp / "scan.csv"
        run("scan_integrity.py", self.tmp / "lib", "--out", scan)
        bad = {r["status"] for r in rows(scan) if r["path"].endswith("01 Song.flac")}
        self.assertTrue(bad & {"length_mismatch", "decode_errors"}, bad)
        out, tl = self.tmp / "m.csv", self.tmp / "t.csv"
        self.ok(run("find_duplicates.py", "mixed", self.tmp / "lib", "--out", out, "--trash-list", tl))
        self.assertEqual(rows(out)[0]["verdict"], "lossless copy looks damaged")
        self.assertEqual(rows(tl), [])

    def test_mixes_and_different_songs_are_not_duplicates(self):
        lib = self.tmp / "lib"
        deluxe = lib / "Band" / "Album (Deluxe)"
        base = {"artist": "Band", "album": "Album (Deluxe)"}
        fixtures.tone(deluxe / "01 Song.m4a", 10, "alac", dict(base, title="Song", track="1"))
        fixtures.tone(deluxe / "Song (Mono).mp3", 10, "mp3", dict(base, title="Song (Mono)"))
        fixtures.tone(deluxe / "Song (Instrumental).mp3", 10, "mp3", dict(base, title="Song (Instrumental)"))
        show = lib / "Band" / "1977.05.08 Barton Hall"
        fixtures.tone(show / "CD1" / "03 Tennessee Jed.m4a", 8, "alac",
                      {"artist": "Band", "title": "Tennessee Jed", "track": "3"})
        fixtures.tone(show / "CD2" / "03 Sugaree.mp3", 9, "mp3",
                      {"artist": "Band", "title": "Sugaree", "track": "3"})
        out, tl = self.tmp / "m.csv", self.tmp / "t.csv"
        self.ok(run("find_duplicates.py", "mixed", lib, "--out", out, "--trash-list", tl))
        self.assertEqual(rows(tl), [], rows(out))
        v = {Path(r["path"]).name: r["verdict"] for r in rows(out)}
        self.assertEqual(v["Song (Mono).mp3"], "different version")
        self.assertEqual(v["03 Sugaree.mp3"], "unique lossy track")

    def test_tracks_mode_never_writes_a_trash_list(self):
        lib = self.tmp / "lib"
        fixtures.tone(lib / "Grateful Dead" / "1990.03.29 Nassau Coliseum, Uniondale, NY | SBD" / "Drums.flac",
                      30, "flac", {"artist": "Grateful Dead", "title": "Drums"})
        fixtures.tone(lib / "Grateful Dead" / "1991.09.10 Madison Square Garden | AUD" / "Drums.mp3",
                      31.5, "mp3", {"artist": "Grateful Dead", "title": "Drums"})
        fixtures.tone(lib / "Prince" / "Hits" / "Kiss.m4a", 5, "alac", {"artist": "Prince", "title": "Kiss"})
        fixtures.tone(lib / "Prince" / "Singles" / "Kiss.mp3", 5, "mp3", {"artist": "Prince", "title": "Kiss"})
        out, tl = self.tmp / "t.csv", self.tmp / "tl.csv"
        self.ok(run("find_duplicates.py", "tracks", lib, "--out", out, "--trash-list", tl))
        self.assertEqual(rows(tl), [])
        names = [Path(r["path"]).name for r in rows(out)]
        self.assertEqual(names, ["Kiss.mp3"])  # the live shows are left alone

    def test_cull_refuses_unclear_actions_before_moving_anything(self):
        sheet = self.tmp / "cull.csv"
        self.ok(run("cull_sheet.py", "build", self.others, "--sheet", sheet))
        r = rows(sheet)
        for x, a in zip(r, ["Save", "D", "?", "S"]):
            x["action"] = a
        c.write_csv(sheet, r, list(r[0]))
        cp = run("cull_sheet.py", "apply", sheet, "--trash", self.trash, "--lists", self.tmp / "l", "--apply")
        self.assertEqual(cp.returncode, 1)
        self.assertIn("Nothing was changed", cp.stdout)
        self.assertFalse(self.trash.exists())
        self.assertFalse((self.tmp / "l").exists())
        cp = run("cull_sheet.py", "build", self.others, "--sheet", sheet)
        self.assertNotEqual(cp.returncode, 0)  # won't overwrite decisions

    def test_generic_album_with_one_compilation_flag_is_not_a_comp(self):
        o = self.tmp / "o"
        for a, flag in (("F", ""), ("G", ""), ("H", "1")):
            tags = {"artist": f"Artist {a}", "title": f"Hit {a}", "album": "Greatest Hits"}
            if flag:
                tags["compilation"] = flag
            fixtures.tone(o / f"Artist {a}" / "Greatest Hits" / f"Hit {a}.m4a", 2, "aac", tags)
        sheet = self.tmp / "s.csv"
        self.ok(run("cull_sheet.py", "build", o, "--sheet", sheet))
        self.assertEqual(sorted(x["name"] for x in rows(sheet)), ["Artist F", "Artist G", "Artist H"])

    def test_non_latin_and_punctuation_artists_are_not_merged(self):
        lib = self.tmp / "lib"
        for name in ("Кино", "宇多田ヒカル", "!!!"):
            fixtures.tone(lib / name / "A" / "t.mp3", 2, "mp3", {"artist": name, "title": "t"})
        out, plan = self.tmp / "s.csv", self.tmp / "p.csv"
        self.ok(run("find_split_artists.py", lib, "--out", out, "--plan", plan))
        self.assertEqual(rows(out), [])
        self.assertEqual(rows(plan), [])

    def test_sniffing_only_renames_real_mislabeled_audio(self):
        lib = self.tmp / "lib" / "X"
        fixtures.tone(lib / "adts.aac", 2, "aac", fmt="adts")
        fixtures.tone(lib / "audio.mkv", 2, "aac", fmt="matroska")
        flac = fixtures.tone(lib / "tagged.flac", 2, "flac")
        flac.write_bytes(b"ID3\x03\0\0\0\0\0\0" + flac.read_bytes())  # empty ID3 tag in front
        mp3 = fixtures.tone(lib / "real.mp3", 2, "mp3")
        mp3.rename(lib / "real.mp3__")
        out = self.ok(run("repair.py", "extensions", self.tmp / "lib", "--apply",
                          "--log", self.tmp / "renames.csv"))
        self.assertEqual(sorted(p.name for p in lib.iterdir()),
                         ["adts.aac", "audio.mkv", "real.mp3", "tagged.flac"], out)
        self.assertEqual(len(rows(self.tmp / "renames.csv")), 1)

    def test_zero_padding_after_mp4_is_only_a_warning(self):
        p = fixtures.tone(self.tmp / "lib" / "a.m4a", 2, "alac", {"title": "t"})
        p.write_bytes(p.read_bytes() + b"\0" * 4096)
        scan = self.tmp / "scan.csv"
        self.ok(run("scan_integrity.py", self.tmp / "lib", "--out", scan))
        self.assertEqual([r["status"] for r in rows(scan)], ["trailing_bytes"])

    def test_colon_in_relative_path(self):
        fixtures.tone(self.tmp / "AC:DC" / "Back in Black" / "Hells Bells.m4a", 2, "alac",
                      {"artist": "AC/DC", "title": "Hells Bells"})
        out = self.ok(run("scan_integrity.py", "AC:DC", cwd=self.tmp))
        self.assertIn("ok: 1", out)

    def test_retag_refuses_to_drop_tags_ffprobe_cannot_see(self):
        raw = fixtures.tone(self.tmp / "raw.mp3", 2, "mp3")
        rated = self.tmp / "lib" / "rated.mp3"
        rated.parent.mkdir(parents=True)
        id3_with_rating(raw, rated)
        m4a = fixtures.tone(self.tmp / "lib" / "gapless.m4a", 2, "aac", {"title": "Gapless"})
        add_freeform_atom(m4a, "com.apple.iTunes", "iTunSMPB", " 00000000 00000840")
        self.assertIn("----:com.apple.iTunes:iTunSMPB", c.raw_tag_keys(m4a))
        plan = self.tmp / "plan.csv"
        c.write_csv(plan, [{"path": rated, "album": "New"}, {"path": m4a, "album": "New"}], ["path", "album"])
        before = rated.read_bytes(), m4a.read_bytes()
        cp = run("retag.py", plan, "--apply")
        self.assertEqual(cp.returncode, 1)
        self.assertIn("POPM", cp.stdout)
        self.assertIn("iTunSMPB", cp.stdout)
        self.assertEqual(before, (rated.read_bytes(), m4a.read_bytes()))
        self.ok(run("retag.py", plan, "--apply", "--allow-tag-loss"))
        self.assertEqual(tags(rated)["album"], "New")

    def test_image_codec_video_without_frame_count_is_kept_as_video(self):
        mkv = self.tmp / "lib" / "Band" / "Concert.mkv"
        mkv.parent.mkdir(parents=True)
        fixtures.ff(["-f", "lavfi", "-i", "sine=duration=3", "-f", "lavfi", "-i",
                     "testsrc=s=160x120:d=3:r=10", "-c:a", "aac", "-c:v", "mjpeg", "-shortest", str(mkv)])
        out = self.ok(run("probe_videos.py", self.tmp / "lib"))
        self.assertIn("real video: 1", out)


if __name__ == "__main__":
    c.require_tools()
    unittest.main(verbosity=2)
