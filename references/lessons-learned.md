# Lessons learned

Details from the run this skill was distilled from: a 17,000-track, 550 GB
library cleaned over several sessions. Read when something behaves
unexpectedly, or before doing anything by hand that the scripts don't cover.

## The truncation bug

Early in the run, files kept getting truncated during retagging, and at first it
looked like disk corruption. The cause turned out to be the tagging pipeline.
The retagged file was written to
a temp on another filesystem, then copied over the original. When a batch hit
the shell's timeout, the copy was killed partway, leaving a half-written
original. The evidence: every truncated file's modification time matched the
moment its folder was processed.

The fix, built into `retag.py` and every script that rewrites a file:

1. Write ffmpeg's output to a temp file **in the same folder** as the original
   (same filesystem).
2. **Verify** the temp before swapping: MP4 atoms complete, ffprobe opens it,
   the duration matches, and every tag reads back.
3. Swap with an **atomic rename** (`os.replace`), which cannot half-write.
4. Never copy a temp across a mount onto a live file under timeout pressure.
5. Scan every fresh batch before trusting it.

One file truncated by the very first, unsafe attempt slipped through for weeks
because its folder was never scanned again. Rescan anything an early or
interrupted pass touched, and run the full scan again at the end.

## Tags

- **Tag values can contain literal junk characters,** e.g. an album stored as
  `"Live at..."` with the quote marks inside the value. Exact string matching
  silently fails on these; match by filename or substring, and check that the
  tag changed after writing. `retag.py` reads every written tag back.
- **Fix the tag, not only the folder.** Music apps group by the embedded artist
  tag, so renaming a folder alone leaves the split in place.
- **Tier merges re-expose duplicates.** Unifying an artist's tags across two
  tiers does not merge their folders; once the tiers combine, the same artist
  shows up as two side-by-side folders. Run the split check again on the merged
  library and merge the folders too.
- MP3 tags are written as ID3v2.3, the version older players and iTunes read
  most reliably.
- **ffmpeg drops some tags on any rewrite**, and ffprobe doesn't show several
  of them, so the loss is silent: MP4 freeform atoms (iTunSMPB gapless info,
  MusicBrainz IDs), MP3 POPM (rating and play count) and UFID; MP3 lyrics
  (USLT) come back in another form. The scripts read the raw tag frames before
  and after and refuse the rewrite unless `--allow-tag-loss` is given. Gapless
  info matters most for live shows, where songs run into each other.

## Formats

- **ALAC and AAC share `.m4a`.** Only probing the codec tells them apart, which
  is how a "lossless" album hides lossy tracks.
- **MP3 and FLAC corruption hides from structural checks.** Decode the file
  and compare the decoded length with the header's claim (a truncated FLAC
  still reports its full length from its STREAMINFO block). Some MP3
  mismatches are only a lying header (fixable by remuxing with `-write_xing
  1`); others are missing audio (re-acquire).
- **Titles alone never prove a duplicate.** Mono and stereo mixes,
  instrumentals and demos often run within a second of the album version, and
  the same song from two different concerts can too. The scripts require
  matching version markers, keep live material out of library-wide matching,
  and check that the copy being kept decodes completely.
- **Odd extensions** (`.m`, `.mp2`, `.mp3__`) were all intact MP3s with mangled
  names. Sniff the content before discarding anything for its name.
- **Embedded cover art is a video stream** to ffmpeg. Stream copies keep it in
  ffmpeg 9; older versions can choke on it, which is what `retag.py
  --allow-drop-art` is for. Converting PCM to ALAC drops it (`-map 0:a`).
- **8-bit PCM** (old game audio) becomes 16-bit in ALAC, which has no 8-bit
  mode. The widening is exact; the file may grow slightly instead of shrinking.
- **FairPlay `.m4p`** files produce ffmpeg errors like "channel element not
  allocated" or "Reserved bit set": that is the encryption, not damage.

## Getting the library back into Apple Music

- The cleaned folder went into a **fresh library**, after the old library was
  removed everywhere. The original, disorganized library was backed up first.
- **Removal has to happen inside Music.** Deleting the files in the Finder
  leaves every track in iTunes Match, ready to sync back. Either delete the
  tracks from the old library in Music, or delete the files first, create a
  new library with iTunes Match on (it shows the whole Match library, not
  downloaded) and delete them all from Music there. The phone was cleared too.
- **iTunes Match is slow on a big library:** about a week and a half to match
  and upload a 550 GB, 17,000-track library.

## Moving files

- A move within one filesystem is a rename, so reorganizing hundreds of
  gigabytes between folders on the same disk is instant. Cross-filesystem
  moves copy, and that is where truncation risk lives.
- A Finder copy error (such as -51 or -8084) during a large copy can be Finder
  fragility rather than damage; the integrity scan settles it.
- Removed files went to a trash split by reason ("Deleted (discarded)",
  "Streaming-listed", "Lossy duplicates"...). Roughly half the removed tracks
  in the original run were traded to streaming playlists rather than
  discarded, and the split made that visible.
