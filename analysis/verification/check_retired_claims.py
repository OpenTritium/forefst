#!/usr/bin/env python3
"""A claim this project has RETRACTED must not reappear in a live page or in the tools.

The hard-link claim ("a name-scoped timestomp leaves the sibling names at the true birth") was reported
corrected twice and was still on eleven live pages AND inside forefst.py -- printed output included -- when
a third review found it. Every gate passed throughout, because none of them could see it:

  * check_doc_drift.py compares sentences across pages for NUMERIC disagreement. This claim has no numbers.
  * check_doc_vocabulary.py is deliberately scoped to retired output tokens INSIDE FENCED CODE BLOCKS,
    because flagging prose there would over-reach.

So a retired PROSE claim had no owner. This is that owner.

Scope: the published docs and both tools. The CHANGELOG is excluded by design -- it is a historical record
and a released entry is never rewritten, so a retired claim legitimately survives in an old entry.

Matching: hard wraps are joined before matching, because a claim split across two lines is the normal case
and a line-by-line scan misses it (the same defect the figures register had). Each entry carries an
`unless` regex so that text STATING the correction -- which necessarily quotes the claim -- does not fire.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPEC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "retired_claims.tsv")


def _tree():
    """Dev keeps the pages under forefstdev/docs; a PUBLISHED clone has docs/ at its root.

    Resolving this wrong is how a gate passes only in the maintainer's checkout. Both layouts are probed,
    so a reader can run this against the published tree and see for themselves that a retracted claim is
    absent -- which is the whole point of shipping it.
    """
    override = os.environ.get("FOREFST_TREE")
    if override:
        return os.path.join(ROOT, override)
    if os.path.isdir(os.path.join(ROOT, "forefstdev", "docs")):
        return os.path.join(ROOT, "forefstdev")
    return ROOT


TREE = _tree()
DOCS = os.path.join(TREE, "docs")
TOOLS = [os.path.join(TREE, "forefst.py"), os.path.join(TREE, "refsanalysis.py")]
EXCLUDE_NAMES = {"changelog.md"}
EXCLUDE_DIRS = {"website"}          # generated from the pages above it


def load_spec():
    rows = []
    with open(SPEC, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            p = line.rstrip("\n").split("\t")
            if p[0] == "id":
                continue
            if len(p) < 5:
                continue
            rows.append({"id": p[0], "pattern": p[1], "unless": p[2],
                         "retired_by": p[3], "correct": p[4]})
    return rows


def targets():
    for dirpath, dirnames, filenames in os.walk(DOCS):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            if fn.endswith(".md") and fn not in EXCLUDE_NAMES:
                yield os.path.join(dirpath, fn)
    for t in TOOLS:
        if os.path.exists(t):
            yield t


def sentences(text):
    """(sentence, line_number) with hard wraps joined."""
    out, buf, start = [], [], 1
    for i, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            if buf:
                out.append((" ".join(buf), start)); buf = []
            continue
        if not buf:
            start = i
        buf.append(line.strip())
    if buf:
        out.append((" ".join(buf), start))
    split = []
    for para, ln in out:
        for s in re.split(r"(?<=[.!?])\s+", para):
            if s.strip():
                split.append((s.strip(), ln))
    return split


def main():
    spec = load_spec()
    if not spec:
        print("retired claims: FAIL - the specification is empty; the gate would pass vacuously")
        return 1

    hits, scanned, unreadable = [], 0, []
    for path in targets():
        scanned += 1
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError as e:
            # A file this gate cannot read is a file it cannot clear. Silence here would let an
            # unreadable page pass as clean, which is the defect this repository's lint exists to stop.
            unreadable.append("%s: %s" % (os.path.relpath(path, ROOT), e))
            continue
        for sent, ln in sentences(text):
            for e in spec:
                if not re.search(e["pattern"], sent, re.I):
                    continue
                if e["unless"] and re.search(e["unless"], sent, re.I):
                    continue
                hits.append((os.path.relpath(path, ROOT), ln, e["id"], sent[:110], e["correct"]))

    # Dead-pattern guard: every pattern must still match the claim it retired, or it has silently
    # stopped protecting anything. Each entry's own `correct` line is NOT the claim, so a canary is used.
    CANARY = {
        "hl-sibling-true-birth": "a name-scoped timestomp leaves the sibling names at the true birth",
        "hl-latest-authentic":   "the latest Created among the siblings is the authentic birth",
        "hl-never-clean-sibling": "flagged on the backdated name and never on the clean sibling",
        "hl-stomp-causes-divergence": "the names disagree on Created, which a name-scoped stomp is the natural cause of",
        # E97-E100, retired 2026-09-19. Each canary is the claim AS THE PROJECT ONCE WROTE IT.
        "hole-is-vlcn-zero":       "an inline extent record with VLCN == 0 is a sparse hole, not a readable extent",
        "integrity-flag-run-one":  "each checksummed cluster is its own extent with flag 0x1C00D0 and run_length 1",
        "mlog-budget-minus-first": "remaining = total_size - first_record_offset",
        "mlog-commit-always-zero": "commit is marked at the checkpoint layer, so this is 0 on every volume, healthy or not",
        "vbr-sector-always-512":   "| 0x20 | 4 | Bytes per sector | u32 | 512 (always) |",
        # E113, retired 2026-09-23 -- each is the v1.13.0 text verbatim (changelog / RC3 evidence).
        "n94-carves-invented":     "Deleted-content recovery refuses two kinds of invented bytes.",
        "carve-cover-coincidence": "a misaligned walk whose cluster counts summed to exactly the file's allocation by coincidence, satisfying the cover guard",
        "gfsareplay-is-metadata":  "nine of the fourteen open with GFSAREPLAY, a filesystem-internal signature",
    }
    dead = []
    for e in spec:
        c = CANARY.get(e["id"])
        if c is None:
            dead.append("%s has no canary: the gate cannot prove the pattern still matches" % e["id"])
        elif not re.search(e["pattern"], c, re.I):
            dead.append("%s no longer matches its own canary: %r" % (e["id"], c))
    if dead:
        print("retired claims: FAIL - %d dead pattern(s)" % len(dead))
        for d in dead:
            print("   - %s" % d)
        return 1

    if unreadable:
        print("retired claims: FAIL - %d file(s) could not be read, so they were not checked"
              % len(unreadable))
        for u in unreadable:
            print("   - %s" % u)
        return 1

    if hits:
        print("retired claims: FAIL - %d occurrence(s) of a retracted claim in %d file(s) scanned"
              % (len(hits), scanned))
        for f, ln, cid, sent, correct in hits[:20]:
            print("   %s:%d  [%s]" % (f, ln, cid))
            print("      %s" % sent)
            print("      say instead: %s" % correct)
        return 1
    print("retired claims: PASS - %d claim(s) checked over %d file(s); none reappeared, all patterns live"
          % (len(spec), scanned))
    return 0


if __name__ == "__main__":
    sys.exit(main())
