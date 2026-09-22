# Object Table

The Object Table (roots #0 and #5, schema 0xe030) is the master OID-to-table mapping. Every persistent **directory and system object** has exactly one entry, so it is the pivot of the namespace. **A file has no Object-Table entry of its own** — it is a set of rows inside its home directory's tree, reached through that directory's OID plus the file's per-directory child ordinal.

## Key Format -- 16 bytes

The on-disk B+-tree leaf-row key is **16 bytes** (the key type is `SmsBigIdentifier`, the 128-bit identifier):

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0x00 | 8 | (zero padding / high half) | Always `00 00 00 00 00 00 00 00` on the Object Table |
| 0x08 | 8 | Object ID (OID) (u64) | Monotonically increasing, never reused — the low half carries the OID (e.g. key `0000000000000000 0700000000000000` = OID 0x7) |

## Value Format -- Compact (v3.10+)

80 bytes (system objects) / 88 bytes (file objects):

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0x00 | 4 | Record format (u32) | `2` on **89,231 of 89,231** rows over 113 volumes. Reading this as a `u64` happens to give 2 only because `u32@+0x04` is 0 on every row, which hides the error |
| 0x04 | 4 | Reserved (u32) | 0 on 89,231/89,231 |
| 0x08 | 4 | Key offset (u32) | `0x18` on 89,231/89,231 |
| 0x0C | 4 | Value offset (u32) | `0x30` on 89,231/89,231 |
| 0x10 | 4 | Payload offset (u32) | 80, 200 or 104 — the field `GetObjectRecordPayload` reads |
| 0x14 | 4 | Trailer length (u32) | 8 or 0 |

There is no 16-byte "record header" at `+0x08`: the format word is at `+0x00`, and `+0x10`/`+0x14` are
the payload offset and trailer length. The `(value_length, payload_offset, trailer)` triples take exactly
six values across the corpus — (88, 80, 8) ×86,707, (80, 80, 0) ×1,052, (248, 200, 8) ×1,044,
(112, 104, 8) ×204, (240, 200, 0) ×179, (104, 104, 0) ×45.
| 0x18 | 4 | **Log sequence number — offset (u32)** | Low half of a 64-bit LSN: the offset within the log segment at which this object was last modified |
| 0x1C | 4 | **Log sequence number — segment (u32)** | High half of the same LSN: the log segment number, which is why the values are small and advance by one per segment. Read together, `u64 @0x18` is the object's last-write position in **log time**, in the same address space as the checkpoint LSN at [CHKP](chkp.md)+0x70 |
| 0x20 | 32 | 4 x u64 LCN slots | Page references for object's own B+-tree root (see [Container Table](container_table.md) for the virtual-to-physical LCN translation) |
| 0x40 | 8 | **Checksum descriptor** | The tail of the page reference: flags (u16), **checksum type at +0x42** (1 = CRC32-C, 2 = CRC64, 4 = SHA-256), digest offset at +0x43, digest length at +0x44. Observed `00 00 02 08 08 00 00 00` on a CRC64 volume — type 2, offset 8, length 8 |
| 0x48 | 8 (32 for SHA-256) | **Digest of the object's root page** | Not an identifier. Recomputing the checksum over the page the LCN slots point at reproduces this value exactly — **34,108 of 34,108 rows** across the corpus (CRC64 and SHA-256 volumes, ReFS 3.4 → Insider). The only 20 mismatches are on one known-damaged volume family, which is what a checksum is for |

## Value Format -- Legacy (pre-v3.10)

A legacy Object-Table row value has three distinct sizes:

1. **B+-tree `value_length`** — the full value-buffer size: **240 bytes** for objects with no 8-byte trailing field (upcase `0x7/0x8`, logfile `0x9/0xa`, trash `0xd`, volume-info `0x500/0x501`, security `0x530`, reparse `0x540/0x541`) and **248 bytes** for the root directory `0x600`, `0x520`, and every file / directory (which carry an 8-byte trailing field).
2. **`value+0x10`** — a payload **offset**, constant for every legacy object: **200 (0xC8)**. **`value+0x14`** — the trailing-payload length, **0 or 8**. Their sum (**200 / 208**) is the driver's copyable payload extent.
3. The driver reads exactly those two fields: `CmsObjectTable::GetObjectRecordPayload` (win11 `@140118c14`) computes `src = value + u32@0x10` and copies `u32@0x14` bytes.

On **compact (v3.10+)** volumes the value shrinks and `value_length` tracks the **checksum** size (independent of cluster size): **80 / 88 bytes** by default, **104 / 112 bytes** under SHA-256. Here `value+0x10` = 80 / 104 flat, so it equals `value_length` only for the no-trailer (system) objects, not for files.

A forensic parser keyed on the B+-tree `value_length` should expect **240 / 248** (legacy), **80 / 88** (compact), or **104 / 112** (compact SHA-256).

**Important**: Upgraded volumes show mixed format. Pre-existing objects retain legacy size; objects created after upgrade use compact size. A forensic parser must handle both sizes within the same Object Table.

## OID Allocation

- 64-bit, monotonically increasing, never reused after deletion
- Counter maintained at `CmsObjectTable+0x18`; atomically incremented (`LOCK` prefix)
- On mount, derived from the rightmost (largest) Object-Table B+-tree key. Win11/Insider use the `_CmsKey::RightMost` sentinel with `CmsTable::FindRow` (present in the decompiled win11 driver, 12 occurrences; Insider 11); the Win10 (v3.4) driver has no such symbol and uses `PinInIndexRightMost` / `MsFindRightmostNodeAvlFull` instead
- **System OIDs**: below 0x700 (except 0x600 which is the root directory)
- **User OIDs**: start at 0x701 (hardcoded via `MsSetMinimumNewObjectId`)
- `RefsIsSystemObjectId` returns true when `OID <= 0x6FF AND OID != 0x600`

See [System OIDs](system_oids.md) for the 13 known system OIDs and their roles.

## Forensic Properties

- **Lower OID = earlier creation** -- reliable chronological indicator
- **Gaps in sequence** = evidence of past deletions
- **Volume activity estimation**: `max_OID - 0x700` = upper bound on total files ever created
- **OID density**: `present_OIDs / (max_OID - min_OID + 1)` -- fresh volumes are 100%; worked volumes show 55-79%

### NTFS vs ReFS Chronology Comparison

| Property | NTFS MFT Record | ReFS OID |
|----------|----------------|----------|
| Size | 48-bit | 64-bit |
| Sequential | Yes | Yes |
| Reused after deletion | Yes | **No** |
| Chronology reliability | Partial (reuse obscures) | **Strong** (no reuse) |
| Scope | Per-MFT | Per-volume |

## Failover

The Object Table has a failover pair: root #0 (table ID 0x02) and root #5 (table ID 0x04). If one copy is corrupted, the driver falls back to the duplicate.

## Driver functions

| Function | Purpose |
|----------|---------|
| `RefsIsSystemObjectId` | Returns true for `OID <= 0x6FF && OID != 0x600`. Guards system object access. |
| `MsSetMinimumNewObjectId` | Sets the floor at 0x701 for user object allocation. |
| `RefsAllocateObjectId` | Atomically increments the OID counter at `CmsObjectTable+0x18`. |
| `RefsGetNextFileIdFromObjectTable` | Reads the current max OID from the rightmost B+-tree key. |
| `UpdateObjectTableWorker` | Persists Object Table modifications during transaction commit. |

## Cross-references

- [Checkpoint (CHKP)](chkp.md) -- roots #0 and #5 point to the Object Table
- [Object IDs](../concepts/object_ids.md) -- what the OID is, why its order is chronological evidence, and why a directory keeps its OID when moved
- [File IDs](../concepts/file_ids.md) -- how a file (which has no OID) is identified; its home half is a directory OID from this table
- [Schema Table](schema_table.md) -- schema 0xe030 defines key comparison for this table
- [Parent-Child Table](parent_child_table.md) -- encodes directory hierarchy relationships
- [System OIDs](system_oids.md) -- the 13 known system OIDs and their roles
- [Container Table](container_table.md) -- needed to translate virtual LCNs in the LCN slots

## Evidence

The key/value layout, the compact-versus-legacy formats, and the failover pair are decompiled from the driver (E2) and decoded on raw disk across the corpus (RD). The record-header decode (`format=2`, key/value offsets, the two LSN halves) and the four-slot LCN tuple are read by `CmsObjectTable::GetObjectRecordOfIdentifier` / `MsGetObjectRecordPayload`. The OID-allocation behaviour (monotonic, never-reused, 0x701 user floor, 0x600 root exception) is proven both statically — `CmsObjectTable::GenerateIdentifier` (atomic increment), `DeleteIdentifier` (never decrements), `MsSetMinimumNewObjectId`, `RefsIsSystemObjectId` — and on disk via the observed no-reuse / gaps-equal-deletions behaviour. > **Where this is checked.** `forefst.py <image> integrity --fullchecksums` crosses the Object Table's leaf
> rows into every object B+-tree and verifies each page against the digest recorded here — so a stale or
> corrupt object root **is** detected, by the command whose job that is. Ordinary commands do **not** verify
> it: doing so would mean re-reading and re-checksumming every object's root page on every run, measured at
> about 40 seconds on a volume with ~27,000 objects. If you need the assurance, run `integrity`.

The LSN at `+0x18` is established on disk. In a controlled three-image experiment on one volume — create three directories, then modify a single file in the first, then a single file in the second, leaving the third untouched throughout — the field advanced for exactly the directory that changed and stayed frozen on the untouched control, **6 of 6 transitions as predicted**. Across **15 volumes** (4K and 64K clusters, ReFS 3.4 through 3.14, 2 GB to 2 TB, including a 4Kn volume) the **maximum** value of `u64 @0x18` equals the active checkpoint's own LSN at `CHKP+0x70` **exactly**, which is what follows from the object table being written last at checkpoint time.

Forensically this is a per-object last-write clock kept by the driver in log time. It orders object modifications independently of the `$SI` timestamps a user can set, and it identifies every object modified after a given checkpoint.

**0x20–0x50 is a complete [page reference](page_references.md)** — the same structure used everywhere else — of which 0x40 is the checksum descriptor and 0x48 the digest of the object's root page. This is raw-disk confirmed rather than inferred: the digest recomputes over the referenced page on **34,108 of 34,108** rows corpus-wide (the 20 exceptions are all on one known-damaged volume family). It follows that a stale or corrupt object root is detectable at no cost, and that the compact 80-byte row (0x20 + 0x30) and the 104-byte SHA-256 row (0x20 + 0x48) are exactly a header plus one page reference. The remaining field-level statements on this page are registered as **FS_OTBL_001**, **FS_OTBL_002**, **FS_OTBL_RA_002**, **FS_OTBL_RA_007**, **FS_OTBL_RA_009**, **FS_OTBL_SA_001**, **FS_OTBL_SA_003**, **FS_OTBL_SA_007**, **MD_ATTR_RA_005** — each with its own evidence tier and witness in the claim register. See [how this was verified](../methodology.md) to trace these to the exact images and measurements in `analysis/`.
