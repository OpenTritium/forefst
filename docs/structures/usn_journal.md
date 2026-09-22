# USN Journal

The USN (Update Sequence Number) Journal records every change to files and directories on the
volume. ReFS uses the `USN_RECORD_V3` format with 128-bit file IDs (NTFS uses the older `USN_RECORD_V2`
form with a 64-bit file reference). The journal is **not active by default** — it must be enabled with `fsutil usn createjournal`.

**On-disk ReFS journal records are version 3.** ReFS's 128-bit file IDs require the `USN_RECORD_V3` layout;
`fsutil usn queryjournal` on ReFS reports `Maximum record version supported : 3`. Version 2 (NTFS's 64-bit
form) and version 4 (`USN_RECORD_V4`, the NTFS-only range-tracking / extent record — `fsutil usn
enablerangetracking` refuses a ReFS volume with *"A local NTFS volume is required for this operation"*) do
**not** occur on a ReFS journal (erratum E58). The parser decodes every record with the **V3 field layout**;
it still *accepts* a V2 or V4 record if one is present (a non-ReFS journal, or crafted/corrupt input) but
prints a one-time note that such records are parsed with V3 offsets and their fields are not validated —
it does not silently refuse them.

## USN_RECORD_V3 layout

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0x00 | 4 | Record length (u32) | Total record size = `pad8(0x4C + UTF-16 name byte length)`; name-dominated, driver minimum 80 (0x50), observed **80–408 B** across the corpus, no fixed ceiling — all records 8-byte aligned. On `winsider` (217,892 records) the maximum is **408** and **1,779 records exceed 312 B** (320 B ×488, 328 ×379, 336 ×741, 344 ×119, 352 ×4, 360 ×4, 368 ×2, 384 ×38, 408 ×4); `winsiderv2` independently reaches 408 with 1,644 over 312. The long ones are legitimate WinSxS component names, so do not treat a record above 312 B as malformed |
| 0x04 | 2 | Major version (u16) | 3 on every ReFS record (the 128-bit File ID requires the V3 layout). The parser decodes with V3 offsets and *tolerates* a stray V2/V4 — a non-ReFS/corrupt input — with a one-time note rather than refusing it (see above) |
| 0x06 | 2 | Minor version (u16) | Always 0 |
| 0x08 | 16 | File ID (u128) | See 128-bit File ID structure below |
| 0x18 | 16 | Parent file ID (u128) | Same format, but this is the **current** parent directory's reference — and it can be **absent**: 234 records on each of `lab314_main`, `lab314_main_step3` and `lab314_main_step3_dirty` carry an empty name AND parent OID `0x0`, so a reader must handle a record with neither. Unlike the File ID at 0x08 — the file's fixed identity — this tracks where the name currently lives, so it **changes when the file is moved** to another directory. Its ordinal (lower 8 bytes) is always **0**: a directory is addressed as `OID:0`, so the parent reference reduces to the parent directory's own OID. |
| 0x28 | 8 | USN (u64) | The record's own USN = its **virtual byte offset** in the journal. Monotonic **within one journal instance**, and it can far exceed the live `$J` stream size because `$J` is a sliding window. It is **not globally unique on the volume**: `fsutil usn createjournal` restarts numbering at 0 **without changing the UsnJournalId**, so USNs are reused. Measured on `lab314_main` — Windows' own `fsutil queryjournal` before and after shows the same id `0x01dd3e1feaee8191` with `Next Usn 0` then `First USN 0, Next USN 3142048`. After such a restart a file's `$SI+0x40` LastUsn may point at **another object's** record: 8 of 4,680 do, and 38 more resolve to no record at all. |
| 0x30 | 8 | Timestamp (FILETIME) | 100 ns ticks since 1601-01-01 |
| 0x38 | 4 | Reason (u32) | See Reason codes below |
| 0x3C | 4 | Source info (u32) | Structurally **0** in every ReFS record (the source-info mechanism is unused on ReFS) |
| 0x40 | 4 | Security ID (u32) | Structurally **0** in every ReFS record (the record carries no SecurityId) |
| 0x44 | 4 | File attributes (u32) | Current WIN32_FILE_ATTRIBUTE flags |
| 0x48 | 2 | File name length (u16) | In bytes |
| 0x4A | 2 | File name offset (u16) | Offset from record start |
| 0x4C | var | File name (UTF-16LE) | — |

## 128-bit File ID structure

| Component | Size | Meaning |
|-----------|------|---------|
| First 8 bytes (`+0x08`) | u64 | Per-directory entry **ordinal** — monotonically allocated, **never reused after deletion** (a deleted ordinal stays a permanent gap) |
| Second 8 bytes (`+0x10`) | u64 | The **creation (home) directory's** Object Table OID — the directory the file was born in, frozen for the life of the object |

Read them in that order **on disk**: record 0 of `lab314_main` at physical `0x19008000` runs `58 00 00 00 | 03 00 | 00 00 | 00*8 | 0c 07 …`, i.e. `+0x08` is the ordinal `0` and `+0x10` is the home OID `0x70c`; the parent pair at `+0x18`/`+0x20` is likewise ordinal `0` then parent OID `0x705`. "Upper/lower half of a u128" describes the numeric value, not the byte order, and reading the first 8 bytes as the OID gets both fields wrong.

This File ID is exactly the `(HomeOid, ordinal)` FileRef described in [File IDs](../concepts/file_ids.md).
The upper 8 bytes name the directory whose B+-tree holds the file's object (its type-0x40 backing), and the
lower 8 bytes identify that object within the tree, so a USN record resolves to a
[B+-tree node](btree_node.md) location without a separate lookup table.

The File ID is **stable in two senses**. It is *temporally* stable — the ordinal is never re-used within
its directory, so a deleted file's File ID is never reassigned to a later file. It is also *spatially*
stable — **renaming or moving a file does not change its File ID.** The upper half is the *creation*
directory, not the current parent, so when a file is moved the File ID (0x08) stays fixed while the Parent
file ID (0x18) changes to the new directory. Across 1,858 real cross-directory moves in the corpus, the
File ID was unchanged in every case. A USN record therefore points to the same file across the whole
journal, through any number of renames and moves.

## Reason codes

Reason codes are bitmask flags. A single record can combine multiple flags (e.g.
`0x80000100` = FILE_CREATE + CLOSE).

| Code (hex) | Name | Description |
|------------|------|-------------|
| 0x00000001 | DATA_OVERWRITE | Default data stream content overwritten |
| 0x00000002 | DATA_EXTEND | Default data stream extended |
| 0x00000004 | DATA_TRUNCATION | Default data stream truncated |
| 0x00000010 | NAMED_DATA_OVERWRITE | Named data stream (ADS) overwritten |
| 0x00000020 | NAMED_DATA_EXTEND | Named data stream extended |
| 0x00000040 | NAMED_DATA_TRUNCATION | Named data stream truncated |
| 0x00000100 | FILE_CREATE | File or directory creation |
| 0x00000200 | FILE_DELETE | File deleted |
| 0x00000400 | EA_CHANGE | Extended attributes changed |
| 0x00000800 | SECURITY_CHANGE | Security descriptor (ACL) changed |
| 0x00001000 | RENAME_OLD_NAME | Source name in rename operation |
| 0x00002000 | RENAME_NEW_NAME | Target name in rename operation |
| 0x00004000 | INDEXABLE_CHANGE | Content indexing attribute changed |
| 0x00008000 | BASIC_INFO_CHANGE | Timestamps or file attributes changed |
| 0x00010000 | HARD_LINK_CHANGE | Hard link count changed |
| 0x00020000 | COMPRESSION_CHANGE | Compression state changed |
| 0x00040000 | ENCRYPTION_CHANGE | EFS encryption state changed |
| 0x00080000 | OBJECT_ID_CHANGE | Object ID changed |
| 0x00100000 | REPARSE_POINT_CHANGE | Reparse point set or removed |
| 0x00200000 | STREAM_CHANGE | Named data stream added or removed |
| 0x00400000 | TRANSACTED_CHANGE | Change within a TxF transaction |
| 0x00800000 | INTEGRITY_CHANGE | Data integrity attribute changed |
| 0x80000000 | CLOSE | Handle closed (OR-ed with the final reason) |

## Forensic patterns

The reason-code combination, not just the individual flag, is the forensic signature of an operation:

| Operation | USN signature |
|-----------|---------------|
| Rename (same directory) | RENAME_OLD_NAME (0x1000) + RENAME_NEW_NAME (0x2000); same File ID **and** same Parent file ID, only the name differs |
| Move (to another directory) | RENAME_OLD_NAME + RENAME_NEW_NAME; **same File ID**, but the **Parent file ID changes** (old directory → new directory) — the file's identity is preserved, only its location moves |
| Sparse flag set | Basic info change (0x8000); file attributes change from 0x20 to 0x220 |
| EFS encrypt/decrypt | Transient `EFS0.LOG` in system directory (OID 0x701); reason 0x40000 |
| $RECYCLE.BIN creation | Created on demand at first Explorer deletion |
| Junction creation | Reparse point change (0x100000) as a separate event |
| Symlink creation | Reparse change combined with create (0x100100) |
| ADS on symlink | Not possible — ADS cannot be written to symlink files on ReFS |

## Storage location

The Change Journal is stored as a file entry inside OID 0x520, the **FS Metadata directory** — the
ReFS equivalent of NTFS `$Extend` (see [System OIDs](system_oids.md)). When journaling is active a
type 0x30 B+-tree row appears with key `"Change Journal"` (UTF-16LE). Fresh volumes have no such
entry — it is created by `RefsCreateUsnJournal` and removed by `RefsDeleteUsnJournal`.

### Change Journal file entry structure

The "Change Journal" filename entry in OID 0x520 carries a `stream_count` field (3 on v3.14). Its value
length is **704 B on 28 of the 34 volumes that have one** — not "~720"; the other lengths measured are
3016 B (×4), 856 B, 3576 B and 720 B (×1 each). The value holds three sub-records after the standard
directory-entry header (the embedded sub-record markers are described in
[Directory Entries](directory_entries.md)). **Their offsets are not fixed** — locate them by walking the
records, never by seeking a constant:

| Sub-record | Type | Identified by | Content |
|------------|------|---------------|---------|
| 1 | Multi-instance (0x80000002) | type `0x000E0080`, sub_id `0x8` | A 40-byte value with **no node header and no extents** — stream-set metadata, not `$J` |
| 2 | Multi-instance (0x80000002) | type `0x000E0080`, sub_id `0x1000` | **The `$J` extents** — its value *is* the extent node (hdr `0x88`, level 0) |
| 3 | Single-instance (0x80000001) | type `0xF0` | **`$Max`** — a 44-byte value, at content `+0x280` / `+0x290` / `+0x150` depending on layout, never `0x288` |

The `$J` data stream contains the actual `USN_RECORD_V3` entries as non-resident extent data. The
`$Max` stream holds the journal size parameters, and is also surfaced as the type-0xF0
`$LOGGED_UTILITY_STREAM` attribute (single-instance marker 0x80000001) on the Change Journal file —
not to be confused with the type-0x100 `$EFS` attribute. The single-instance sub-record at 0x288
contains organizational metadata including a creation timestamp and journal configuration.

`$J` is a **bounded rolling log**: it is pre-allocated to a fixed size (typically 32 MiB or 128 MiB, set
by `$Max`) and, once full, the oldest records are believed to be overwritten **in place** as new ones are appended — so its
records fill the entire allocation. forefst therefore reads the **whole allocated window** (every extent),
not a shorter "logical size" — the two multi-instance markers each carry a fixed data-stream *type* tag
(`0x000E0080` = 917,632), not a byte length, and capping the read at that constant would truncate every
journal larger than ~896 KiB.

The journal does nonetheless **declare its own lengths** (erratum E103), in the embedded `$DATA` row whose inline-header
offset (value+0x00) is `0x88`: allocated size, stream size, valid data length and disk allocation at
`+0x30`, `+0x38`, `+0x40`, `+0x48`. On all 21 corpus volumes that have a journal, exactly one row matches
and **all four equal the sum of the `$J` extents' clusters** — across 32, 64 and 128 MiB allocations, both
cluster sizes and a 4Kn volume. Reading the whole allocation is still the right thing for recovery, since
records fill it; but a declared length that *disagrees* with the allocation is evidence that the
declaration was truncated or edited, and `usn --info` reports both the declared values and any mismatch. Each record is self-describing (a record length and its own USN).

**`$J` is framed in 4 KiB pages, and a record never straddles one.** Over the 7 journals measured
(332,745 records) **0 cross a 4 KiB boundary**. When the next record would not fit in the remaining
bytes of a page, the writer zero-pads and starts it at the next boundary: **10,499 inter-record gaps**,
every one smaller than 4096 B (largest 1,216 B on `winsider`), every one ending exactly on a 4 KiB
boundary, and in 10,498 of 10,499 the record that follows would not have fitted in the gap. A reader
that walks record-to-record by declared length alone will land in padding; skip to the next 4 KiB
boundary instead. For the same reason a partially-filled journal's tail is **not simply zeros** — it can
hold stale content from a previous pass of the ring, so 'the zero tail is skipped' must not be read as
'everything after the last record is empty'. A record's USN is its **byte offset in `$J`**,
so a file's `LastUsn` (`$SI+0x40`) is the offset of that file's most recent record and is found in the
journal **while that record is still inside the live window**; only changes older than the window's oldest
surviving record have been overwritten and are gone.

> **The journal is an in-place ring.** A record whose USN is *X* sits at byte offset *X* **modulo the allocation**, the extents begin at file VCN 0, and old records are overwritten where they lie — the buffer is never trimmed from the front. The practical consequences: the whole allocation must be read; **byte order is not time order**, because after a wrap the newest records sit at the *start* of the buffer and the oldest in the middle; and a highest USN larger than the stream size is normal rather than a sign of damage. On the one corpus volume whose journal has wrapped, the buffer holds two generations side by side — the older one filling offsets 7,352,320–33,554,168 and the newer one 0–7,350,976, with the write head at about 7.35 MB of a 32 MiB window — and every one of its 217,892 records sits exactly at its USN modulo that window.

### Activation detection

| Image state | OID 0x520 row count | Change Journal entry |
|-------------|---------------------|----------------------|
| Fresh (never activated) | 1 (descriptor only) | Absent |
| Active journaling | 3+ | Present (type 0x30, "Change Journal") |
| Deactivated | Varies | May persist with zeroed extents |

### Recreation: a journal that starts at USN 0 on a volume that has been used

`fsutil usn createjournal` does not resize the journal on ReFS and it does not merely reset a counter — it
**discards the existing history**. The size arguments are not honoured: a request for a 1 MiB journal with a
256 KiB allocation delta produced a **32 MiB** journal with delta **0**, the same allocation every volume in
this project's corpus carries. Because the window never filled, nothing was lost to wrapping — and yet no
record of any operation performed before the call survives.

That gives the examiner a signal worth checking early, because it is cheap and it changes what the journal
can be used for:

| What you see | What it means |
|---|---|
| USN range starts at **0** on a volume with substantial prior activity | The journal was **recreated**. Everything before that point is gone; the volume is not young |
| USN range starts at a **non-zero** value, spanning about one allocation | A normal rolling window that has wrapped once or more — the oldest records aged out |
| USN range starts at 0 and the volume is genuinely new | Nothing to conclude |

The middle row is what a busy volume looks like: on one Insider system volume the range runs 40,906,752 →
74,459,840 across a 32 MiB allocation — a span of exactly one window. The first row is what a recreated
journal looks like: range 0 → 3,146,304 in the same 32 MiB, under a tenth of the window used, on a volume
that had already had thousands of files written and deleted.

A recreated journal is not proof of intent — installers and management tools call `createjournal` too — but
it does mean **absence of a record in the journal is not evidence the operation did not happen**, and any
timeline built from it starts at the recreation, not at the volume's birth.

## Tooling

USN Journal parsing is integrated into `forefst.py` (parsing + display).
Available via `forefst.py <image> usn`:

| Mode | Description |
|------|-------------|
| Default | An activity **summary** (record count, reason-code distribution, time span) |
| `--list` (or `-v`) | The on-screen record list with reason codes and file names |
| `--csv [FILE]` | Export as CSV (a file export also prints the summary stats) |
| `--json [FILE]` | Machine-readable JSON output |

Every ReFS journal record is version **3.0** (the 128-bit File ID requires the V3 layout), so the export
carries no version column.

### CSV / JSON columns

The `--csv` and `--json` exports share one field set (17 columns, in this order):

| # | Column | Meaning |
|---|--------|---------|
| 1 | `usn` | The record's own USN (virtual byte offset in the journal) |
| 2 | `timestamp` | Record time (FILETIME rendered as a date) |
| 3 | `reason_hex` | Raw reason bitmask |
| 4 | `reason` | Decoded reason flag names |
| 5 | `filename` | The file or directory name |
| 6 | `entry_type` | `dir` when `file_id == 0` (a directory self-reference), else `file` |
| 7 | `file_ref` | `home_oid:file_id` — the same value as `files.FileRef` |
| 8 | `home_oid` | The containing/creation directory for a file; the object's **own** OID for a directory |
| 9 | `file_id` | The entry ordinal (lower half of the File ID); `0` for a directory |
| 10 | `parent_oid` | The current parent directory's OID |
| 11 | `path` | The record's parent directory resolved **against the volume as it is in this image**, joined with the file name the record carries. **Read the caution below before relying on it.** |
| 12 | `attrs_hex` | Raw file-attribute bitmask |
| 13 | `attrs` | Decoded attribute names |
| 14 | `record_length` | The on-disk record length |
| 15 | `security_id` | Structurally 0 on ReFS (see the layout above) |
| 16 | `source_info` | Structurally 0 on ReFS |
| 17 | `parent_idx` | Structurally 0 on ReFS (a parent is a directory addressed as `OID:0`) |

### Caution: `path` is resolved against the CURRENT volume, not against the moment of the event

The journal is a historical record; the path column is not. It is built by looking the record's
`parent_oid` up in the directory tree **as that tree exists in the image being read**, and joining the
result with the file name stored in the record. Two consequences follow, and both matter when the
column is used as evidence:

- **A parent that no longer exists cannot be resolved.** The column then shows `<oid 0x…>` — an honest
  statement that the directory is gone, not a path. On a real Windows installation this is the majority
  case: measured over 217,892 records on one installation, **118,172 (54.2 %)** name a parent directory
  that has since been deleted, against 99,365 (45.6 %) that still resolve. A freshly built lab volume
  shows 0 %, which is why the effect is invisible unless you look at a system with churn.
- **A parent that was renamed or moved after the event resolves to its CURRENT location.** The row then
  joins a present-day directory path to a historical file name, and the combination was never a real
  path at any moment.

So `path` answers "where would this file be today, given where its parent is today" — not "where was
this file when the event happened". For the latter, use `parent_oid` together with the journal's own
record of directory creates, renames and deletes. Reconstructing the tree as it stood at event time is
the correct way to answer that question and the tool does not do it yet.

Directories **do** get USN records: a directory self-reference has `file_id == 0`, which is why
`entry_type` reads `dir`. The `security_id`, `source_info`, and `parent_idx` columns are placed last
because they are structurally 0 on every ReFS record and are retained only for completeness.

## Cross-references

- [Directory Entries](directory_entries.md) — per-file LastUsn at resident value offset **0x68**; value+0x58 holds FileSize; UsnJournalId at 0x70
- [$STANDARD_INFORMATION](../attributes/STANDARD_INFORMATION.md) — per-file LastUsn at **$SI+0x40**, UsnJournalId at $SI+0x48 ($SI+0x30 is an unpopulated slot)
- [System OIDs](system_oids.md) — OID 0x520 hosts the Change Journal file entry
- [File IDs](../concepts/file_ids.md) — how the 128-bit File ID maps to a B+-tree location

## Evidence

The recreation signal is **MD_USN_RA_009**, measured in the lab: 1 MiB requested, 32 MiB
and delta 0 granted, no wrap, and no pre-call record surviving; contrasted against an Insider system
volume whose range spans exactly one allocation.

The `USN_RECORD_V3` layout, the 128-bit File ID split (upper = the creation/home directory OID, lower =
entry ordinal), and the reason-code catalog are raw-disk decoded across the corpus (RD). That the upper
half is the *creation* directory and is **frozen across rename and move** — while the Parent file ID at
0x18 tracks the current parent — is disk-proven on 1,858 cross-directory `RENAME_OLD_NAME`/`RENAME_NEW_NAME`
pairs across nine v3.14 volumes (File ID unchanged in every case) and corroborated in the driver
(`RefsMoveFile` migrates only the FileId-resolution index, never the stored reference). The record length range and the
`pad8` rule are measured corpus-wide (driver minimum 80 (0x50), observed 80–312 B, 8-byte aligned). The
USN ↔ `$SI+0x40` LastUsn link is both decompiled (E2) and disk-proven — every sampled file's LastUsn
resolved to a `$J` record naming that file. Journal activation, the OID 0x520 Change Journal entry,
and the type-0xF0 `$Max` attribute are corroborated in the driver
(`RefsSetupUsnJournal`, `RefsWriteFcbUsnRecordToJournal`) and verified on disk. The in-place ring is
**observed, not assumed**: across 14 corpus journals all 338,439 records sit at their USN modulo the
allocation, and on the one volume whose journal has wrapped — 2.22 windows' worth of records, every one of
them past the end of the window — the buffer holds two generations cleanly split by position, which
front-trimming cannot produce. The two quantities compared there are independent: the offset comes from the
linear scan position, the USN from the record body. Findings:
**MD_USN_RA_001**, **MD_USN_RA_002**, **MD_USN_RA_003**, **MD_USN_RA_004**, **MD_USN_RA_008**, **AP_CHJN_001/002/004**,
**MD_SI_RA_013**, **MD_SI_RA_015**, **FS_OTBL_005**. See
[how this was verified](../methodology.md) to trace these to the exact images and measurements in
`analysis/`.

The remaining field-level statements on this page are registered as **AP_CHJN_002**, **AP_CHJN_004**, **GN_ARCH_RA_002**, **MD_EFS_RA_001**, **MD_EFS_RA_002**, **MD_LK_RA_003**, **MD_LK_RA_004**, **MD_SF_RA_002**, **MD_USN_RA_007** — each with its own evidence tier and witness in the claim register.
