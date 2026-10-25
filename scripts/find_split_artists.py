#!/usr/bin/env python3
"""Phase 4.5, the featured-artist fold, and the post-merge check: find one
artist split into several by spelling.

Read-only. Looks at the embedded ARTIST tags (the split that matters: a music
app groups by tag, not folder) and at the top-level artist folder names. It
reports three kinds of finding:

  spelling   tag or folder variants that collide once case, accents, curly
             vs straight quotes, '&' vs 'and', a leading 'The', punctuation
             and spacing are ignored (Beyonce/Beyoncé, Jane's/Jane’s,
             Cream/The Cream)
  typo       near-identical names (Wolfang/Wolfgang); always confirm
  featured   'X with Y', 'X feat. Y', 'X ft. Y' where X exists on its own:
             fold into X and move the credit into the track title
             ("Song (feat. Y)")

Genuine collaborations ("X & Y" as an act) are reported only when they
collide with another spelling of themselves, never merged into X.

With --plan it writes a retag plan (retag.py's format) that sets every
variant's files to a canonical spelling: the most common variant, unless you
edit the plan's artist column before applying. Folder merges are listed but
left to you (or Claude) to move, since they need a look first.

Usage:
  find_split_artists.py LIBRARY [--out findings.csv] [--plan retag_plan.csv]
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

FEATURED = re.compile(r"^(?P<main>.+?)\s+(?:with|feat\.?|featuring|ft\.?)\s+(?P<guest>.+)$", re.I)
FIELDS = ["kind", "key", "variants", "canonical", "files", "folders", "note"]


def pick_canonical(variants: Counter) -> str:
    """Most-used spelling; on a tie prefer real accents and straight quotes."""
    def rank(v: str) -> tuple:
        accents = sum(1 for ch in v if ord(ch) > 127 and ch not in "‘’“”")
        curly = sum(1 for ch in v if ch in "‘’“”")
        return (variants[v], accents, -curly, v)
    return max(variants, key=rank)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("library", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--plan", type=Path, help="write a retag plan unifying artist tags")
    ap.add_argument("--typo-threshold", type=float, default=0.88,
                    help="similarity (0-1) for typo candidates (default 0.88)")
    ap.add_argument("--jobs", type=int, default=8)
    args = ap.parse_args()
    c.require_tools()

    if not args.library.is_dir():
        sys.exit("LIBRARY must be a folder of artist folders.")
    rows = c.catalog(args.library, args.jobs)
    lib = Path(c.ff_path(args.library))
    by_key: dict[str, Counter] = defaultdict(Counter)
    files_by_variant: dict[str, list[str]] = defaultdict(list)
    folders_by_key: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        name = (r.get("artist") or "").strip()
        k = c.artist_key(name)
        if not k:  # no tag, or a name of only punctuation: nothing to compare
            continue
        by_key[k][name] += 1
        files_by_variant[name].append(r["path"])
        try:
            folders_by_key[k].add(Path(c.ff_path(r["path"])).relative_to(lib).parts[0])
        except (ValueError, IndexError):
            pass
    top_folders = sorted(p.name for p in lib.iterdir() if p.is_dir() and not p.name.startswith("."))
    folder_keys: dict[str, list[str]] = defaultdict(list)
    for f in top_folders:
        if c.artist_key(f):
            folder_keys[c.artist_key(f)].append(f)

    findings, plan = [], []
    for k, variants in sorted(by_key.items()):
        if len(variants) > 1:
            canonical = pick_canonical(variants)
            tie = len({n for n in variants.values()}) == 1
            findings.append({
                "kind": "spelling", "key": k, "variants": " | ".join(f"{v} ({n})" for v, n in variants.most_common()),
                "canonical": canonical, "files": sum(variants.values()),
                "folders": " | ".join(sorted(folders_by_key[k])),
                "note": ("tie, so the accented/straight-quote spelling was picked: confirm. " if tie else "")
                        + "Fix the tag, not just the folder, or the music app re-splits them",
            })
            for v in variants:
                if v != canonical:
                    plan += [{"path": p, "artist": canonical, "note": f"was {v}"} for p in files_by_variant[v]]
    for k, fs in sorted(folder_keys.items()):
        if len(fs) > 1:
            findings.append({"kind": "spelling", "key": k, "variants": " | ".join(fs),
                             "canonical": fs[0], "folders": " | ".join(fs),
                             "note": "same artist in several top-level folders: merge the folders"})

    keys = sorted(k for k in by_key if len(k) >= 5)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if abs(len(a) - len(b)) > 2 or a[:2] != b[:2]:
                continue
            if c.similar(a, b) >= args.typo_threshold:
                va, vb = by_key[a].most_common(1)[0][0], by_key[b].most_common(1)[0][0]
                findings.append({"kind": "typo", "key": f"{a} ~ {b}",
                                 "variants": f"{va} ({sum(by_key[a].values())}) | {vb} ({sum(by_key[b].values())})",
                                 "canonical": "", "files": sum(by_key[a].values()) + sum(by_key[b].values()),
                                 "folders": " | ".join(sorted(folders_by_key[a] | folders_by_key[b])),
                                 "note": "possible typo: confirm before merging"})

    known = set(by_key) | set(folder_keys)
    seen = set()
    for name in list(files_by_variant) + top_folders:
        m = FEATURED.match(name)
        if not m or name in seen:
            continue
        seen.add(name)
        main_key = c.artist_key(m.group("main"))
        if main_key in known and main_key != c.artist_key(name):
            findings.append({"kind": "featured", "key": c.artist_key(name), "variants": name,
                             "canonical": m.group("main"),
                             "files": len(files_by_variant.get(name, [])),
                             "folders": " | ".join(sorted(folders_by_key.get(c.artist_key(name), {name}))),
                             "note": f"fold into {m.group('main')}; put '(feat. {m.group('guest')})' in "
                                     "the track titles. First confirm same-named live tracks are "
                                     "different performances, not duplicates: ask, durations can't tell"})

    if args.out:
        c.write_csv(args.out, findings, FIELDS)
    if args.plan:
        c.write_csv(args.plan, plan, ["path", "artist", "note"])
    kinds = Counter(f["kind"] for f in findings)
    print(f"{len(rows)} files, {len(by_key)} distinct artists (by key), {len(top_folders)} top-level folders")
    for k in ("spelling", "typo", "featured"):
        print(f"  {k}: {kinds[k]}")
    if not args.out:
        for f in findings:
            print(f"{f['kind'].upper()}: {f['variants']}  -> {f['canonical'] or '?'}  ({f['note']})")
    if args.plan:
        print(f"Retag plan for {len(plan)} files -> {args.plan} (check the artist column, then retag.py)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
