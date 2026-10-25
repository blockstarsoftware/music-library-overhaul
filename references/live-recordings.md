# Live recordings: conventions and the problems that come up

Read before Phase 1. People who collect live shows accumulate hundreds of
recordings from many sources and tools, so handle them apart from normal
albums.

## The convention

Album tag: `YYYY.MM.DD Venue, City, ST | Source`

- Date is the show date, not the recording or upload date.
- Venue uses its standard name ("The Beacon Theatre", not "Beacon").
- US shows use the two-letter state code; for other countries spell out the
  country ("Bochum, Germany").
- `| Source` names the provenance. Keep a source vocabulary and use it
  consistently: SBD (soundboard), AUD (audience), Matrix, FM (add the station
  when known, e.g. "FM - WXPN"), Nugs, YouTube, TV, Radio, DVD, webcast,
  festival names. Omit `| Source` only when it is truly unknown.
- Discs as `N/TOTAL`; a single-disc show gets `1`. If the source splits sets
  (Set 1, Set 2, Encore), those are discs 1, 2, 3 with track numbers restarting
  per disc. One continuous block means no disc split.
- Pick the conventions with the person before writing anything, and extend
  `plan_shows.py --vocab` with their own source keywords.

## Where identity comes from

The tags are often inconsistent or absent: proper tags, tags like
`10/22/2005 Fonda Theater`, or nothing at all. The source of truth is usually
**folder name, then filenames, then setlist**, not the embedded tags. Read
what's there for each show before assuming.

- **Inventory first.** `plan_shows.py inventory` maps every messy folder to a
  prefilled target name before anything is written.
- **Complete identity from names.** `1996_12_03 Little Rock, AR` becomes, after
  looking up the venue, `1996.12.03 Robinson Center Music Hall, Little Rock, AR | Source`.
- **Identify a show by its setlist** when even the name is cryptic. If a folder
  is just numbered tracks, the songs identify the show. Ask the person for a
  screenshot of the setlist (setlist.fm, a streaming page) and take titles and
  order from it.

## Problems that come up

- **Multi-disc reconciliation.** Merge a show's discs into one folder, or into
  disc subfolders ("CD1", "Disc 2", "Set 2", "Encore"; the scripts treat those
  as one album). Watch for conflicts: two folders both claiming "disc 2/2", a
  disc with an unexpected track count, or a stray one-track folder that
  duplicates a track already on the real disc. Check track counts and
  durations before merging.
- **Live and studio takes are different recordings.** The same song appears as
  a studio track and a live take; durations differ, so never collapse one into
  the other. Within one live set, a one-track stray whose duration exactly
  matches a track on the full show is a redundant duplicate.
- **Different masterings of the same show are not duplicates** (a "24-bit
  original" and a "2025 remaster"). Keep both, but **unify their artist tag**
  so the music app groups them: collaboration credits drift ("Jimmy Page & The
  Black Crowes" vs "The Black Crowes With Jimmy Page"). Choose the canonical
  form with the person.
- **Recovering "missing" shows.** A restore from backup can drop folders. Keep
  a list of expected vs present shows. When the person supplies the missing
  ones, scan them first: live shows are large multi-gigabyte files, exactly the
  ones an interrupted Finder copy truncates.
- **Artist overrides.** Side projects and acoustic duos inside a main artist's
  collection get their own artist tag, not the band's.

## Keep live material local

Bootlegs, soundboards, audience tapes and one-off live versions usually don't
exist on streaming services. They are the strongest keep-local category and
should never be offloaded to a streaming playlist. A streaming import that
reports a live track "not found" confirms it belongs local.
