"""1.13.1 -- the inline-holder reader keeps a row's flags ON REQUEST, and only on request.

The carve's path (1) decoded extents as (fvcn, vlcn, run) with the flags thrown away, so it could not see
a run its own row marks unwritten, READ it, and merged the clusters' current bytes into the carve. The
reader now returns the flags when asked; every other caller must keep getting the 3-tuples it always did.
"""
import struct
import forefst as F


def _holder(rows):
    """A minimal 0x10028 holder: ihdr at +0, stream size @0x38, disk alloc @0x48, the extent table at ihdr."""
    ihdr = 0x50
    body = bytearray(ihdr + 0x28)
    struct.pack_into("<I", body, 0, ihdr)
    struct.pack_into("<Q", body, 0x38, 8192)
    struct.pack_into("<Q", body, 0x48, 8192)
    struct.pack_into("<I", body, ihdr + 0x14, len(rows))
    for vlcn, fvcn, run, flags in rows:
        body += struct.pack("<QIIII", vlcn, flags | (24 << 16), fvcn, 0, run)
    return bytes(body)


ROWS = [(0x1000, 0, 1, 0x0050),       # written
        (0x2000, 1, 1, 0x0040)]       # allocated, NOT written in this version


def test_default_shape_is_unchanged_for_every_other_caller():
    _s, _a, exts = F.parse_snapshot_data_entry(_holder(ROWS))
    assert all(len(e) == 3 for e in exts)


def test_with_flags_returns_the_flags():
    _s, _a, exts = F.parse_snapshot_data_entry(_holder(ROWS), with_flags=True)
    assert [len(e) for e in exts] == [4, 4]
    assert exts[1][3] & 0xFFFF == 0x0040


def test_an_unwritten_run_is_seen_as_unwritten():
    _s, _a, exts = F.parse_snapshot_data_entry(_holder(ROWS), with_flags=True)
    assert not F._extent_never_written(exts[0][3])
    assert F._extent_never_written(exts[1][3])
