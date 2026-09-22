"""K008: a bulk exporter must not let two source names that sanitise to one path clobber each other.

`_safe_filename`/`_safe_relpath` map every character outside [alnum . _ - space] to '_', so two distinct
volume names (`xbpt(txt` and `xbpt)txt`, or `a:b` and `a?b`) can collapse to one on-disk path. The
deleted/carve writers guard this with `_collision_free_path`; `export resident-all`, `recyclebin` and the
metadata bundle did not, so the second write silently overwrote the first — a wrong_bytes defect (the
first file's content is lost). This pins the guard using the tool's real functions in the real write
pattern, so it cannot regress. (No corpus volume has such names — Windows filenames rarely sanitise —
which is why this is a unit pin rather than a golden row.)
"""
import os
import forefst as m


def test_sanitize_collision_is_confirmed():
    # the two names really do collapse to one sanitized path
    assert m._safe_relpath("xbpt(txt") == m._safe_relpath("xbpt)txt")


def test_collision_free_path_preserves_both(tmp_path):
    out = str(tmp_path)
    fails = []
    pairs = [("xbpt(txt", b"ONE"), ("xbpt)txt", b"TWO")]
    for name, content in pairs:
        dest = m._collision_free_path(os.path.join(out, m._safe_relpath(name)))
        m._guarded_extract_write(dest, content, fails)
    files = sorted(os.listdir(out))
    assert len(files) == 2, "both distinct files must survive, got %r" % files
    bodies = sorted(open(os.path.join(out, fn), "rb").read() for fn in files)
    assert bodies == [b"ONE", b"TWO"], "content of both files must be preserved, got %r" % bodies


def test_without_guard_a_file_is_lost(tmp_path):
    # documents the defect: the SAME loop WITHOUT the guard loses a file (this is what the shipped
    # resident-all writer did). Kept so the guard's necessity is self-evident in the test file.
    out = str(tmp_path)
    fails = []
    for name, content in [("xbpt(txt", b"ONE"), ("xbpt)txt", b"TWO")]:
        dest = os.path.join(out, m._safe_relpath(name))   # NO _collision_free_path
        m._guarded_extract_write(dest, content, fails)
    assert len(os.listdir(out)) == 1   # the defect: one file overwritten
