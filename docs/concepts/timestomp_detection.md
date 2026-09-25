# Timestomping Detection

> **Experimental / informational.** Timestomp detection here is a corroborative aid, not a verdict. Its strongest intrinsic signal (`CHANGE_LATE`) is defeated by a native-API or raw-disk stomp that also sets the change time; `ROUND_TIMESTAMPS` is a weak, LOW-only signal that ordinary driver packages and archive extraction produce too; and every flag needs confirmation against the USN journal or a file's hard-link siblings before you conclude tampering. Treat the output as leads to verify, not proof.

Timestomping — back-dating a file's timestamps to hide when it was really created or written — is a
standard anti-forensic move, and the technique an analyst reaches for first does not exist on ReFS.
NTFS exposes it by comparing the two timestamp sets every file carries, the
[$STANDARD_INFORMATION](../attributes/STANDARD_INFORMATION.md) set against the `$FILE_NAME` set; when a
tool stomps `$SI` but leaves `$FN` untouched, the mismatch is the tell. ReFS carries **one `$SI`
timestamp set per name**, not a second `$FILE_NAME` copy — so for a **single-named** file there is no
`$SI`-vs-`$FN` twin to compare against and that particular cross-check is unavailable. A **hard-linked**
file differs: each of its names holds an **independent** timestamp copy, and those copies **can** hold
different times — where NTFS's links share one `$SI` and cannot diverge. Divergence between a file's names
is evidence; **agreement is not**, because the file's own record takes the new time for every name at
once and only each name's index entry lags behind — and any read of a sibling catches it up (see
[Hard Links](hard_links.md)). Beyond that, timestomping is detectable
through different anchors: the metadata-change time that common
tools cannot reach, the [USN change journal](../structures/usn_journal.md) that records the tampering
operation itself, and the volume's own creation time as a hard floor. This page explains each anchor,
why it works, and where it fails.

## Three independent anchors

ReFS gives the analyst three things to lean on, in increasing order of strength:

1. **The metadata-change time is left behind.** The high-level Windows APIs that ordinary timestomp tools
   call cannot set the change time, so the filesystem stamps it at the moment of the stomp while the
   forged times sit in the past. This is a heuristic against common tooling, not a guarantee.
2. **The USN journal records the edit.** A deliberate timestamp change is logged as a `BASIC_INFO_CHANGE`
   record at its real time, and a file's genuine creation is logged as a `FILE_CREATE` record. The journal
   is append-only, so these are the stronger, harder-to-forge anchors.
3. **The volume creation time is a floor.** A file cannot have been created before the filesystem it lives
   on existed. Any creation time earlier than the volume's own creation is structurally impossible.

The `forefst.py <image> timestomp` subcommand combines all three and ranks suspects by confidence.

### Two more witnesses, when the journal is gone

The journal is the anchor an anti-forensic step removes first — and `fsutil usn createjournal` discards it
outright while looking like a resize (see [USN journal](../structures/usn_journal.md)). Two other
structures record a time independently, and both survive that:

- **The transaction log.** A `SetFileTime` writes no log record of its own, so the *act* of stomping is not
  there. But the file's **creation** is: an MLog `CREATE` transaction carries an embedded timestamp, and a
  creation time in `$SI` that disagrees with it is a contradiction between two structures. Measured on a
  volume whose journal had been destroyed, this caught every backdated birth present and flagged nothing
  else. It speaks to the **birth time only** — a forged last-write agrees with the `CREATE` record — and
  the log is a rolling buffer, so an old enough creation has aged out of it.
- **A stream snapshot.** A snapshot descriptor timestamps the moment it was taken, not the file
  (see [`$SNAPSHOT`](../attributes/SNAPSHOT.md)). A creation time backdated below a snapshot of the same
  file is impossible.

Both are cross-checks an analyst runs today by reading `mlog --parse` and `snapshots` beside `timestomp`;
folding them into the tool's own corroboration column is planned work, not current behaviour.

## Why the change time is the key intrinsic anchor

A ReFS `$SI` holds four FILETIMEs, all at fixed offsets in the type-0x10 own-row's value (see
[$STANDARD_INFORMATION](../attributes/STANDARD_INFORMATION.md)):

| Offset | Time | Letter |
|--------|------|--------|
| 0x00 | Creation | **B** |
| 0x08 | Modification / last write | **M** |
| 0x10 | Metadata change | **C** |
| 0x18 | Last access | **A** |

The metadata-change time `C` is an ordinary timestamp — nothing about it is cryptographic or
tamper-proof. What makes it useful is an **API asymmetry**: the high-level interfaces a timestomp tool
normally uses expose only three of the four times.

- Win32 `SetFileTime(hFile, &Creation, &LastAccess, &LastWrite)` has **no `ChangeTime` parameter**.
- PowerShell `Set-ItemProperty -Name CreationTime/LastWriteTime/LastAccessTime` and .NET
  `File.SetCreationTime / SetLastWriteTime / SetLastAccessTime` expose the **same three**.

A caller using any of these **cannot reach `C`**, and the filesystem updates `C` to *now* as a side
effect of the metadata write it performs. So after a back-dating stomp, B/M/A point into the past while
`C` is left at the real moment of the operation. The signature is

```text
C >> max(B, M)
```

flagged as **CHANGE_LATE**. For a single-named file it is the closest ReFS analogue of the NTFS
`$SI`-versus-`$FN` comparison — using the not-normally-reachable change time as the reference instead of
a second timestamp set. (When the file is **hard-linked**, a truer analogue is available: the sibling
names' own timestamp copies, discussed below as `HARDLINK_MACB_MISMATCH`.)

**This defeats common tooling, not a determined attacker.** The change time *is* settable through the
native path: `FILE_BASIC_INFORMATION.ChangeTime` passed to `NtSetInformationFile` carries an explicit
change time, and the ReFS driver honours it. The driver tracks, per open handle, which of the four times
the caller supplied explicitly versus which the filesystem should auto-update — a flag per time
(change included) that only exists *because* every one of the four times can be set explicitly. An
attacker who sets all four through the native API, or who edits the raw `$SI` bytes on disk directly,
leaves **no** `CHANGE_LATE` signal. The intrinsic change-time anchor catches PowerShell / `SetFileTime`
/ .NET timestomp tools; it does not catch someone who knows about `ChangeTime`. When the journal is
present, it is the anchor that does not depend on the attacker's tool choice.

## The signals

The tool emits a set of named signals; each is a single comparison, and each has a different strength
and a different way to be wrong.

| Signal | Meaning | Source | Strength |
|--------|---------|--------|----------|
| **CHANGE_LATE** | `$SI` change time (0x10) post-dates Created/Modified by a wide margin — back-dated B/M against the real metadata-write time | intrinsic ($SI only) | strong vs common tools; **defeated** by a native-API or raw-disk stomp that sets `C` too |
| **HARDLINK_MACB_MISMATCH** | two names of one hard-linked file disagree on Created. Nothing routine produces this, so it is a strong lead — but which name holds the true birth is **not** established | intrinsic (per-name `$SI`) | strong; **journal-independent**, and unlike NTFS the copies *can* diverge. Only fires when a file has more than one name, and its **absence means nothing** — see the mechanism below: agreement has two causes, and one of them is that somebody read the file |
| **USN_BASIC_INFO_CHANGE** | the journal holds a **standalone** `BASIC_INFO_CHANGE` (reason 0x8000, with no `FILE_CREATE` or `DATA_*` bits) — a deliberate basic-info / timestamp edit with **no content change**, recorded at its real time | USN journal | authoritative **It is gated**: this signal is only recorded when `CHANGE_LATE`, `PRE_FORMAT` or `CREATE_GT_MODIFY` also fired on the same file, so a standalone journal edit with no intrinsic signal is **not reported at all** — an authoritative signal suppressed by the absence of a heuristic one. Treat a file's silence here as 'not corroborated', never as 'the journal recorded nothing'. **It is not specific to tampering**: on the T21 lab volume 34 records carry reason exactly `0x00008000` across 27 names, and only **12** are the lab's deliberate stomps — the rest are timestamp-preserving operations that legitimately rewrite basic info, such as `robocopy /COPY:DAT` and extracting an archive with stored times. It is authoritative that an edit happened, not that it was a backdate. |
| **USN_CREATE_MISMATCH** | `$SI` Created differs from the file's `FILE_CREATE` journal record (the journal is append-only) | USN journal | authoritative |
| **PRE_FORMAT** | Created precedes the **volume** creation time — impossible for a file genuinely created here | intrinsic + volume | strong\* |
| **FUTURE** | Created after the volume's last metadata write | intrinsic + volume | medium\* |
| **CREATE_GT_MODIFY** | Created after last write | intrinsic | weak\* |
| **ROUND_TIMESTAMPS** | both Created **and** Modified land on a whole second (`.0000000` sub-second) — a set date is one cause, but VirtIO/QEMU driver packages and archive extraction also produce whole-second stamps | intrinsic ($SI only) | **INFO**, not LOW — `ROUND_TIMESTAMPS` is part of the copy signature, so on its own it returns INFO |

\* `PRE_FORMAT`, `FUTURE`, `CREATE_GT_MODIFY` — and `CHANGE_LATE` — also fire on a
**creation-time-preserving copy** (robocopy `/COPY:T`, a backup restore) or a legitimate late rename or
ACL change on an aged file: these keep or set an old creation time while the metadata-write / change time
is recent. Such a file is a genuine *inconsistency*, but whether it is malicious needs analyst context.
The USN journal is what turns a suspicion into a confirmation, because it records the operation that
caused the inconsistency at the time it actually happened.

`HARDLINK_MACB_MISMATCH` is the exception to that dependence: a creation-preserving copy gives every name
the same times, so it does **not** trip on benign copies — it fires only when a file's own names genuinely
disagree on Created, and nothing routine makes them disagree. It needs no journal and no volume-create
floor to stand on.

What it does **not** tell you is *which* name holds the authentic birth. The mechanism below explains
why the copies disagree, but not which side of the disagreement is the original: the stale entry is the
one nobody opened, and that is not the same thing as the one nobody forged. So every name of a diverging
group is flagged rather than a chosen one. Treat it as a strong lead into the
[journal](../structures/usn_journal.md), not as a self-contained verdict.


### Why the copies diverge, and why the signal is perishable

Two layers, and they refresh at different times:

* The **file's own record** takes the new timestamp **immediately**. In that sense a `SetFileTime`
  through one name updates every name at once — the file has one truth.
* Each **name's index entry** is a **lazily refreshed cache** of it. `RefsUpdateFileDupInfo` refreshes
  only the entry of the name that was **opened**; siblings stay stale until each is opened in turn.

So a stomp through one name leaves that name's entry current and every un-opened sibling holding
**pre-stomp** times — which is the divergence this signal detects.

**It follows that agreement clears nothing**, because agreement has two causes: the names never
diverged, *or* they diverged and something opened the sibling. And it follows that the evidence is
**perishable** — any open refreshes that name's entry. An antivirus scan, a search indexer, an
inventory pass, a `Get-FileHash` sweep, or the examiner's own `dir` will erase it for the name it
touches.

Measured on a controlled pair (`labA_image1` / `labA_image2`) differing by exactly one recorded action,
`read-sibling-name-ONLY`: before, one name is HIGH with `HARDLINK_MACB_MISMATCH` and the sibling shows
the pre-stomp birth; after **merely reading** the sibling, the mismatch is gone and the sibling is not
flagged at all.

**Image before anything touches the volume.** A read is not a safe operation for this evidence.

## Confidence tiers

The tool collapses the signal set into one of four verdicts. The dividing line is **corroboration from an
independent source** — the change journal, or a hard-link sibling — not the number of intrinsic signals that
happen to fire together.

| Tier | Reached when | Reading |
|---|---|---|
| **HIGH** | the journal confirms a deliberate edit (`USN_BASIC_INFO_CHANGE` / `USN_CREATE_MISMATCH`), **or** a hard-link sibling preserves a different birth time (`HARDLINK_MACB_MISMATCH`) | an independent source disagrees with `$SI` |
| **MEDIUM** | `CHANGE_LATE` **without** `PRE_FORMAT` — created on *this* volume and altered afterwards — or `FUTURE` | worth investigating; a copy cannot produce it |
| **INFO** | only the copy-signature set fires: `PRE_FORMAT`, `CHANGE_LATE`, `CREATE_GT_MODIFY`, `ROUND_TIMESTAMPS` | **ambiguous**, see below |
| **LOW** | **unreachable** — exhaustive enumeration of all 256 pipeline-constructible inputs (6 signals × `usn_conf` × `hl_conf`) yields HIGH 223, MEDIUM 20, INFO 11, NONE 2 and **LOW 0**. The tier exists in the code and in `--min LOW`, but no input reaches it |

### Why `PRE_FORMAT` + `CHANGE_LATE` is INFO, and what INFO does *not* mean

These two are not independent. A timestamp-preserving copy — `robocopy /COPY:T`, a restore, an archive
extraction — writes the original create/modify (which predate this volume, so `PRE_FORMAT`) and sets the
change time to the moment of the copy (so `CHANGE_LATE`). They are two halves of **one event**, so treating
their co-occurrence as two agreeing signals is wrong: it marked **95.4 %** of the files on a real Windows
installation as tampered, which trains an examiner to ignore the column.

**But the pair does not identify that event as a copy.** Deliberately back-dating a creation time produces
exactly the same two signals — a lab volume whose generator log records **74 `SetCreationTimeUtc` actions**
carries this signature. So INFO means *a copy and a back-dated creation are indistinguishable here*, and the
only thing that separates them is an independent source: the USN journal, or a disagreement between a
file's own hard-link names. **INFO is a lowered tier, not an exoneration.**

### How often each signal fires

Base rates over the full corpus — **102 volumes, 532,959 files**, re-measured in a single pass. Read them
as a floor, not as a typical volume: the corpus is mostly small purpose-built lab images.

| Signal | Base rate | Tier contribution |
|---|---|---|
| `PRE_FORMAT` | 22.17 % | INFO |
| `CHANGE_LATE` | 21.83 % | MEDIUM only *without* `PRE_FORMAT` |
| `CREATE_GT_MODIFY` | 1.69 % | INFO |
| `ROUND_TIMESTAMPS` | 0.04 % | never lifts a tier |
| `HARDLINK_MACB_MISMATCH` | 0.06 % | **HIGH** |
| `FUTURE` | 4 files | MEDIUM |

The split by volume kind is the reason the tiers are shaped this way. On the corpus's one **real Windows
installation** (120,617 files) the copy signature fires on **95.7 %** of files — that is what installing an
operating system looks like — against **1.86 %** across 95 lab-built volumes. Under a tiering that treated
the pair as corroboration, almost every file on that volume was MEDIUM; the reviewable set is now
**383 MEDIUM** beside **1,714 HIGH** — rather than roughly 115,000 rows all claiming the same thing.

`ROUND_TIMESTAMPS` is capped by design. Whole-second Created **and** Modified stamps are *suggestive* of a
deliberately set date but are **not proof**: VirtIO/QEMU driver packages and archive extraction also write
whole-second times, so the signal never lifts another tier's verdict.

The four tiers are assigned in one place, by the `timestomp` command, which
share one function — see the [tool reference](../tools/forefst.md) for the command-line surface and
`--min TIER` filtering. The column reaches a tier no higher than the command, because the listing does not
read the journal.

## What does not work as a substitute

Two tempting shortcuts do not hold up and should not be treated as primary signals:

- **The NextFileId ordinal** (`$SI+0x58` on v3.7–v3.10; `ExternalFileId_1` on v3.4) is a per-directory
  child-creation ordinal — it records each child's position in the directory's creation sequence, written
  by `RefsMoveFile` incrementing the parent directory's counter. A higher ordinal means the child was
  created later in *that directory's* lifecycle, so a gross created-time-versus-ordinal inversion within
  one directory is corroborating. But it is coarse: it is directory-scoped, and it is 0 on native v3.14
  own-rows (the ordinal moved into the object-record payload at v3.11), so it cannot be a general anchor.
- **A zero sub-second fraction** (whole-second times, the low 100 ns part = 0) is sometimes left by
  timestomp tools that write second-granularity values, but it is entirely tool-dependent — a tool that
  copies full-resolution FILETIMEs leaves no such fingerprint, and VirtIO/QEMU driver packages and archive
  extraction produce whole-second stamps on ordinary files. The tool surfaces it as the `ROUND_TIMESTAMPS`
  signal but caps it at **LOW** for exactly this reason: it is a lead to corroborate (with the USN journal or
  a hard-link MACB comparison), never a primary signal on its own.

## How the tool is wired

The detector has two parts, but **one surface**. `timestomp_intrinsic_flags()` computes the `$SI`-intrinsic
signals (`CHANGE_LATE`, `PRE_FORMAT`, `CREATE_GT_MODIFY`, `FUTURE`) without touching the journal, and
`timestomp_verdict()` turns signals into a tier. Both are reached only through
`forefst.py <image> timestomp`, which loads the [USN journal](../structures/usn_journal.md) and adds the
`BASIC_INFO_CHANGE` and create-mismatch signals before deciding:

Earlier releases also attached the intrinsic half to every `files` row as a `TimestompFlags` column. That
column was removed, because a listing cannot read the journal: it could only ever carry the half of the
answer that a timestamp-preserving copy also produces, while sitting in a column that looked like a
verdict. Timestamp-anomaly information now comes from this subcommand alone.

```sh
forefst.py <image> timestomp                # flagged files, ranked by confidence
forefst.py <image> timestomp --min HIGH     # only high-confidence suspects
forefst.py <image> timestomp --json         # machine-readable
forefst.py <image> timestomp --csv out.csv  # per-file CSV: path, storage, confidence, signals, evidence_ref, MACB
forefst.py <image> timestomp --all          # every file with its flags (incl. NONE)
forefst.py <image> timestomp --margin-days N # anomaly margin (default 1 day)
```

The `--margin-days` value is the slack the intrinsic comparisons allow before calling a gap suspicious,
which keeps ordinary clock skew and sub-day operation latency from generating noise.

The two USN-based signals correlate a file to its journal records by **File ID** — the FileRef
`(HomeOid, ordinal)`, not the path. Because the File ID is unchanged by a rename or a cross-directory move,
a file that was renamed or relocated after creation is still matched to its true `FILE_CREATE` record, so
`USN_CREATE_MISMATCH` and `USN_BASIC_INFO_CHANGE` are not defeated by an intervening move — a stomp cannot
be hidden simply by moving the file afterward. See [File IDs](file_ids.md).

## Cross-references

- [$STANDARD_INFORMATION](../attributes/STANDARD_INFORMATION.md) — the per-name timestamp set ReFS carries (B/M/C/A at 0x00/0x08/0x10/0x18) that every intrinsic signal reads
- [File IDs](file_ids.md) — the FileRef that ties a file to its journal records across renames and moves, so a stomp can't be hidden by relocating the file
- [Hard Links](hard_links.md) — why each name of a file carries its own `$SI` copy, so their MACB can diverge under a name-scoped stomp (the `HARDLINK_MACB_MISMATCH` basis)
- [USN Journal](../structures/usn_journal.md) — the append-only record whose `BASIC_INFO_CHANGE` (reason 0x8000) and `FILE_CREATE` entries are the authoritative anchors
- [Artifact Timeline](artifact_timeline.md) — how the MACB times feed a unified event timeline
- [Forensic Analysis Workflow](forensic_analysis_workflow.md) — the tamper check is step seven (`$SI` vs USN vs volume-create) of the standard workflow
- [Copy-on-Write](copy_on_write.md) — why a content-preserving copy can keep an old creation time and trip the intrinsic signals
- [What Survives](what_survives.md) — the format-time immutables that fix the volume creation floor

## Two things that do not help

**SetMace and tools like it do not work on ReFS.** They edit `$MFT` records, and ReFS has no `$MFT`.
A stomp on ReFS goes through the ordinary Windows API, which is why the change time is left behind.

**A write to a named stream moves the parent file's times.** An ADS write updates the host file's
LastWrite *and* LastAccess, so a file whose content never changed can still carry a fresh modification
time. Measured on format 3.14. Before reading a modification time as evidence of a content change,
check whether the file has streams.

## Evidence

The four-FILETIME `$SI` layout, the NextFileId ordinal, and the per-handle "caller supplied this time
explicitly" tracking are confirmed in the driver (E2): `RefsComputeStandardInformationInternalFromFcb`
builds the `$SI` fields from the FCB, `RefsMoveFile` writes the directory child-creation ordinal, and the
driver honours an explicit `FILE_BASIC_INFORMATION.ChangeTime`. The two journal-independent witnesses are
**MD_TS_RA_009** (the MLog `CREATE` embedded timestamp measured against `$SI` on a controlled set whose
journal had been destroyed) and **MD_SNAP_RA_010** (the snapshot descriptor records the snapshot moment,
not a copy of `$SI`). **What the detection was measured against, and what that measurement can and cannot establish.**
It was run on the raw-disk corpus against a controlled ground-truth image built from a replay log of
`SET_TIMESTAMPS` operations that back-date creation by years on a freshly formatted volume. On that set
every HIGH-tier file has a provable basis (created before the volume existed, and/or a
journal-confirmed deliberate edit); the clean baseline and a clean operations image (real renames, ADS,
snapshots, symlinks, hard links) flag nothing; and the same synthetic back-dated files are flagged
identically wherever the test corpus was written.

That is the coverage, and it is narrower than it sounds — which is stated here rather than left for a
reader to discover. **Every file in that set has a unique, freshly created name.** Correlating a journal
record to a file BY NAME and correlating it BY FileRef therefore give the same answer on every one of
them, so the set cannot exhibit — and so cannot rule out — an error in which of the two the tool uses.
A test set that cannot produce the failure it is meant to detect does not establish its absence. The
cases that WOULD separate them (a name reused after deletion, a file renamed after the edit, two live
files sharing a name in different directories) are not present on it. The
journal's standalone `BASIC_INFO_CHANGE` records sit on the timestomp image at the tampering's real time
while `$SI` shows the forged time. The per-name MACB behind `HARDLINK_MACB_MISMATCH` is a documented
correction (RD): `$SI` is stored per name entry (per hard link), not per inode, and the copies were
observed diverging on a two-name file where one name read a back-dated Created and the other the real
creation moment. A later lab measurement found the converse does **not** hold: calling `SetFileTime`
through one name of a two-name file left both rows byte-identical across their whole 84-byte value, so
agreement between names is not evidence of anything, and the mechanism behind the observed divergence
remains undecompiled. Also registered for statements on this page: **MD_TS_RA_007**. The controlled-set calibration — eight files with one known cause each, six flagged and all six at INFO — is **MD_TS_RA_008**; that an ADS write updates the parent's LastWrite and LastAccess is **MD_TS_RA_003**; that `$MFT`-editing tools cannot work here is **MD_MISC_001**. See [how this was verified](../methodology.md) to
trace these to the exact images and measurements in `analysis/`.
