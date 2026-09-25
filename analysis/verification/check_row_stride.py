#!/usr/bin/env python3
"""Gate: extent rows are stepped ONLY by _extent_row_step().

Why this exists. A row's declared SIZE (24, or 24 + 4*run) and its STEP (the size rounded up to 8) are
different things; extent_descriptors.md says rows are 8-byte aligned. 1.13.0 stepped by the size, and
eight loops in forefst.py computed their own stride -- four of them as `base + i * 24`, which the first
census missed because it only looked for `+=`. The consequences shipped: `integrity` verified 127 of 142
CRC-bearing clusters and printed "every ... matches", and carves were refused whose live twins were
byte-identical to what 1.12.3 had recovered.

A stride computed anywhere else fails this gate. A fixed stride that is a deliberate FALLBACK (a row whose
size field is illegal, probed and validated before it is taken) must carry `# stride-fallback:` with its
reason on the same line -- so every guess is visible and named, and a new one cannot slip in unmarked.
"""
import io, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS = ["forefstdev/forefst.py", "forefstdev/refsanalysis.py"]
if not os.path.isdir(os.path.join(ROOT, "forefstdev")):          # package / published layout
    TOOLS = [t for t in ("forefst.py", "refsanalysis.py") if os.path.isfile(os.path.join(ROOT, t))]

PATTERNS = [
    (re.compile(r"\+\s*\w+\s*\*\s*(24|32)\b"),                   "index-form fixed stride (base + i * 24/32)"),
    (re.compile(r"\+=\s*(24|32)\b"),                              "fixed stride (+= 24/32)"),
    (re.compile(r"(\+=|=\s*\w+\s*\+)\s*\(?\s*_extent_row_size\("), "stepping by the row SIZE, not its aligned step"),
]
MARK = "# stride-fallback:"


def scan(text, name):
    bad = []
    for i, line in enumerate(text.splitlines(), 1):
        code = line.split("#", 1)[0] if MARK not in line else line
        for rx, why in PATTERNS:
            if rx.search(code):
                if MARK in line and len(line.split(MARK, 1)[1].strip()) >= 12:
                    continue                         # a named, justified fallback
                bad.append((name, i, why, line.strip()[:100]))
    return bad


def _self_test():
    """The gate must be able to fail. Known answers, run every time."""
    cases = [
        ("        base = eo + i * 24\n", 1),
        ("        pos += 24\n", 1),
        ("        pos += _extent_row_size(v, pos, run)\n", 1),
        ("        pos += 24   # stride-fallback: illegal size field, probed by _ext() first\n", 0),
        ("        pos += 24   # stride-fallback: x\n", 1),              # a marker without a reason does not count
        ("        pos += _extent_row_step(v, pos, run)\n", 0),
        ("        x = y * 24\n", 0),                                    # multiplication, not a stride
    ]
    fails = [(src, want, len(scan(src, "t"))) for src, want in cases if len(scan(src, "t")) != want]
    return fails


def main():
    st = _self_test()
    if st:
        for src, want, got in st:
            print("  self-test: %r expected %d finding(s), got %d" % (src.strip(), want, got))
        print("row stride: FAIL -- the gate's own known-answer test failed; its verdict cannot be trusted")
        return 1
    bad = []
    for t in TOOLS:
        p = os.path.join(ROOT, t)
        bad += scan(io.open(p, encoding="utf-8").read(), t)
    for name, i, why, line in bad:
        print("  %s:%d  %s\n      %s" % (name, i, why, line))
    print("row stride: %s -- %d stride site(s) outside _extent_row_step() (self-test %d/%d)"
          % ("FAIL" if bad else "PASS", len(bad), 7, 7))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
