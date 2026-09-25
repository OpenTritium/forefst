"""1.13.1 item 1 -- a row's STEP is its declared size rounded up to 8.

RED against 1.13.0, which stepped by the size: after a 28-byte checksummed row it landed 4 bytes short of
the next real row. On win11refstestmftecmd that left 15 of 142 CRC-bearing clusters unverified while
`integrity` printed "every checksummed file cluster matches", and refused 14 carves whose live twins were
byte-identical to what 1.12.3 recovered.
"""
import struct
import forefst as F


def _row(vlcn, fvcn, run, crcs=0):
    """One extent row: VLCN@0, flags@8 (low 0x00D0 when it carries CRCs, row size in the high half),
    FVCN@0x0C, run@0x14, then one CRC-32C per cluster when crcs. Padded to 8 like the driver writes."""
    size = 24 + 4 * crcs
    flags = (0x00D0 if crcs else 0x0040) | (size << 16)
    body = struct.pack("<QIIII", vlcn, flags, fvcn, 0, run) + b"\x11\x22\x33\x44" * crcs
    return body + b"\0" * (((size + 7) & ~7) - size)


def test_step_known_answers():
    for run, crcs, want in ((1, 0, 24), (1, 1, 32), (3, 3, 40), (5, 5, 48), (2, 2, 32)):
        r = _row(0x1000, 0, run, crcs)
        assert F._extent_row_size(r, 0, run) == 24 + 4 * crcs
        assert F._extent_row_step(r, 0, run) == want, (run, crcs)


def test_illegal_size_field_steps_zero_not_a_guess():
    r = bytearray(_row(0x1000, 0, 1))
    struct.pack_into("<H", r, 0x0A, 10)                       # a size no row can have
    assert F._extent_row_step(bytes(r), 0, 1) == 0


def test_a_row_after_a_checksummed_row_is_found():
    """The shape that shipped wrong: a 28-byte CRC row, then a plain row 32 bytes later."""
    rows = _row(0x2000, 0, 1, crcs=1) + _row(0x3000, 1, 4)
    first = F._extent_row_step(rows, 0, 1)
    assert first == 32                                       # 1.13.0 said 28
    nxt = rows[first:first + 24]
    assert struct.unpack_from("<Q", nxt, 0)[0] == 0x3000     # the real second row, not 4 bytes into it
    assert struct.unpack_from("<I", nxt, 0x14)[0] == 4
