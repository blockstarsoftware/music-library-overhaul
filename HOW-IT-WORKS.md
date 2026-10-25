# How it works

Music Library Overhaul is for someone who wants to end up with a library of
music they actually care about, in the best quality they can get: lossless
wherever possible, cleanly tagged, nothing broken, nothing doubled. Over the
years most of us rip CDs, grab downloads, inherit folders and collect music
from all kinds of sources. Much of it seemed worth keeping at the time. This
process helps you repair what's worth keeping, let go of what you're now
clear you don't want, and move the music you'd like to hear but don't need to
own to a streaming service.

Your agent works through it with you one phase at a time. Before each phase
it explains what's about to happen and what it will ask you; afterward it
shows you what it found before anything changes. Every library is different,
so phases that don't apply to you are skipped, and the order can bend to what
your library needs.

## Before you start

- **Back up.** Make a complete copy of your library and leave it untouched.
  Then make a second copy to work on. The agent only ever touches the working
  copy.
- **Expect it to take a while.** Scans of a big library run for hours, and
  the overhaul this was built from (17,000 tracks) took several sessions. You
  can stop anywhere and pick up later.
- **Nothing is deleted outright.** Removed files go to a trash folder, sorted
  by reason, and can be put back.

## The first conversation

The agent starts with a few questions:

- **Where is your working copy?**
- **Which lossless format do you want?** ALAC or FLAC. Your library is
  standardized on it as it's cleaned. If your library lives in Apple Music,
  choose ALAC: Apple Music doesn't play FLAC.
- **Where does your core collection end and the long tail begin?** A useful
  trick: sort your artist folders by size. Lossless albums are many times
  larger than loose MP3s, so there's usually a visible drop where the serious
  collection ends and the stray singles begin. That line splits the library
  into two tiers, which are handled differently.
- **Do you collect live recordings** of particular artists (soundboards,
  audience tapes, Nugs, FM broadcasts)? If so, they get a phase of their own.
- **Would you like to move music you don't need to own, but still want to
  hear, to streaming playlists** (on Spotify, for example)?

## The phases

### 0. Integrity check

The agent first checks every file for damage: files cut short by an
interrupted copy, empty files, files that won't open, and files that are fine
but carry the wrong extension. It decodes every MP3 and FLAC in full, because
a truncated one can look and play normally right up to where it stops. Some
problems are repaired on the spot (a wrong extension, an MP3 whose header
lies about its length); the rest go on a list of tracks to get again. The
check runs once more at the very end.

### 1. Live recordings (if you collect them)

For collectors of live shows. Show folders tend to have messy or missing
tags, so the agent works from folder names, filenames and setlists instead.
It reads each show's date from its folder name, guesses the source, and
proposes a name like `1996.12.03 Robinson Center Music Hall, Little Rock, AR | SBD`.
You correct venues and sources (a setlist screenshot helps when a folder has
no useful name at all), and then it applies the tags, disc numbers and track
numbers in one careful pass. Live recordings stay in your local library:
most of them aren't on any streaming service.

### 2. The long-tail cull

This is where you decide what stays. The cull makes two separations: first,
what you still want and what you don't; then, of what you want, what you
need to own locally and what you only need to be able to reach.

The agent gives you a spreadsheet with one row per artist (compilations are
kept together as one row) showing track counts, sizes, albums and sample
titles. You type one letter per row:

- **K, keep.** It stays in your library.
- **D, delete.** You're done with it, and it goes to the trash.
- **S, stream.** You'd still like to hear it but don't need to own it. It
  leaves your library and goes on a streaming playlist.
- **U, upgrade.** Keep it for now, and add it to a list of music to find
  again in lossless.
- **B, both.** Keep it locally, and also put it on the streaming playlists
  so they're complete.

The agent checks every row before anything moves, shows you the result as a
dry run, and only then carries it out.

### 3. Streaming playlists (if you chose to offload)

The S and B music becomes playlists sorted by genre, built from each file's
real tags. You import them into Spotify (or another service) through
TuneMyMusic or Soundiiz, which usually means paying for a month of one of
them, since their free plans stop at a few hundred tracks. Expect some tracks
not to match: sometimes a tag needs correcting, sometimes it's quicker to
find the track by hand, and sometimes the music just isn't on streaming.
Those are better kept locally, and the agent can bring them back out of the
trash.

### 4. Deep clean of your core collection

On the serious tier, the agent looks for:

- **False-lossless albums:** albums that look lossless but have lossy tracks
  hidden in them. Usually that's a leftover MP3 or AAC copy of a song the
  album already has in lossless, and it can go. When the two differ in length
  (a live take, an edit, a mono mix), both stay, and you get to listen.
- **The same album twice:** true duplicates go, keeping the best copy;
  remasters and different editions both stay.
- **One artist split into several by spelling** (Beyoncé and Beyonce, a
  missing "The", "&" versus "and"). The agent proposes one spelling, you
  confirm it, and it fixes the tags so your music app stops splitting them.
- **Folders like "X with Y,"** folded into X with the guest credited in the
  song title.

### 5. Music and everything else

Lectures, audiobooks, podcasts, guided meditations and voice recordings get
found and moved to a folder of their own. You confirm each one. Long DJ mixes
and symphonies are recognized as music.

### 6. The "Unknown Artist" drawer

Files with no tags at all usually have informative filenames. The agent tags
them from those and files them where they belong, checking first whether you
already have them.

### 7. Videos

Video files in a music library are often songs in a video wrapper, or a song
whose album art got mistaken for video. Those become ordinary audio files.
Real music videos and concert clips move to a separate Music Videos folder.

### 8. Formats

WAV and AIFF files are converted to your chosen lossless format, ALAC or
FLAC, with a check that proves the audio came through identical. That saves
about half the space and fixes their tags; the sound stays exactly the same.
Lossy files can't be turned into lossless, so they go on the list to find
again. Old iTunes Store purchases protected by DRM (`.m4p`) are flagged,
since nothing can convert them.

### 9. Merge and final check

If your library was split into tiers, the tiers merge back into one. Merging
tends to reveal a few more same-artist folder pairs and duplicates, which get
cleaned up, and then a final full integrity check confirms everything is
intact.

### Bringing it back into your music app

The process ends with a clean folder. For Apple Music, the route this was
built on: confirm your backup, delete the old library from inside Music
(deleting the files in the Finder leaves them in iTunes Match) and clear your
phone, then import the clean folder into a fresh library. Play counts,
ratings and playlists don't come along. With iTunes Match, give it time: a
550 GB library took about a week and a half to match and upload.

## What you end up with

- A library of music you chose, in your lossless format wherever possible,
  tagged consistently and checked for damage.
- Streaming playlists for the music you'd rather not store, if you chose that.
- Lists of what to find again in lossless, tracks that need replacing, and
  DRM files.
- A trash folder of everything removed, sorted by reason, restorable until
  you empty it.
