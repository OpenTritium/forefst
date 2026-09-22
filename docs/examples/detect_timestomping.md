# Worked Example: Detecting a Back-Dated (Timestomped) File

**Goal:** take a ReFS image, find the files whose creation time was forged into the
past, and prove the tampering with an independent anchor rather than a single
suspicious timestamp.

## Setup

Image: a ReFS 3.14 volume
formatted **2026-05-23** and then driven through a replay log that issued **75
`SET_TIMESTAMPS` operations** back-dating file creation into 2021–2025. The forged
files are named `xbpt_*`. This is ground truth: we know which files were stomped and
when the volume really existed, so every flag the tool raises can be checked.

## Steps

### Step 1 — Triage with the high-confidence filter

```sh
python3 forefst.py \
 image.raw timestomp --min HIGH
```

Actual output (header + first suspects):

```text
==============================================================================
ReFS Timestamp-Anomaly (Timestomp) Detection
==============================================================================
  Image:           win11refstestmftecmd.raw  (ReFS 3.14)
  Volume created:  2026-05-23 06:04:52
  Volume modified: 2026-05-23 11:15:52
  USN journal:     present (authoritative cross-check ON)
  Files examined:  1507
  Flagged:         194  (HIGH 137 / MEDIUM 0 / LOW 0 / INFO 57 — INFO = ambiguous: a timestamp-preserving copy and a backdated creation produce the same signals; corroborate with USN)
  This flags timestamps that LOOK anomalous — it is investigative INFORMATION, not proof of
  tampering. Weigh the BASIS of each row: a journal/hardlink signal is authoritative; an
  intrinsic ($SI-only) signal is a heuristic that also fires on legitimate timestamp-preserving
  copies/restores. Tiers, exactly as timestomp_verdict() decides them:
    HIGH   — an AUTHORITATIVE corroboration: the change journal, or a disagreement between
             two of the file's own hard-link names. A count of intrinsic signals never reaches HIGH.
    MEDIUM — CHANGE_LATE without PRE_FORMAT (created on THIS volume, metadata altered later),
             or FUTURE (created after the volume's last metadata write).
    INFO   — every signal present is one a timestamp-preserving copy also produces
             (PRE_FORMAT / CHANGE_LATE / CREATE_GT_MODIFY / ROUND_TIMESTAMPS), so a copy and a
             backdate are indistinguishable here however many of them fire.
    LOW    — anything else.
  Conf   Basis         Claimed birth         Last real write       Path
  ------------------------------------------------------------------------------------------------
  HIGH   journal/link  2022-08-02 07:16:28   2026-05-23 07:34:02   test/elvis_dir_record_449015/elvis_dir_lima_252141/elvis_dir_oscar_306778/xbpt_romeo_output_531365.cfg
         signals: PRE_FORMAT, HARDLINK_MACB_MISMATCH
  HIGH   journal/link  2026-05-23 07:33:58   2026-05-23 07:34:01   test/elvis_dir_record_449015/elvis_dir_papa_104235/elvis_dir_sync_718743/elvis_dir_gamma_109016/elvis_dir_zulu_984398/elvis_dir_cache_558805/xbpt_hardlink_audit_219848.cfg
         signals: HARDLINK_MACB_MISMATCH
  HIGH   journal/link  2026-01-01 07:16:17   2026-05-23 07:38:51   test2/elvis_dir_index_149423/elvis_dir_victor_121923/elvis_dir_hotel_670324/elvis_dir_output_358165/xbpt_audit_echo_178867.tmp
         signals: PRE_FORMAT, USN_BASIC_INFO_CHANGE, USN_CREATE_MISMATCH
  HIGH   journal/link  2024-08-03 07:17:33   2026-05-23 07:38:52   test2/elvis_dir_index_149423/elvis_dir_victor_121923/elvis_dir_hotel_670324/elvis_dir_output_358165/xbpt_zulu_india_473528.csv
```

The header pins the **volume creation bound** read from `$VOLUME_INFORMATION +0x90`, and
confirms the USN journal is present so the authoritative cross-check is on.

Read the `Basis` column before the `Conf` column. Every HIGH row says **`journal/link`**: either the
USN journal independently recorded a deliberate edit (`USN_BASIC_INFO_CHANGE`,
`USN_CREATE_MISMATCH`) or two of the file's own hard-link names disagree
(`HARDLINK_MACB_MISMATCH`) — evidence outside the timestamps themselves. That is what earns HIGH —
**a count of intrinsic signals never does**, however many fire.

The other 57 rows are `INFO`, and the distinction matters more than the number. A
timestamp-preserving copy (`robocopy /COPY:T`, a restore, an archive extraction) produces
exactly the same `$SI`-only signals as a deliberate backdate, so on those rows the volume
cannot separate the two. `INFO` means *ambiguous*, not *cleared* — and not *suspicious*.

### Step 2 — Read the full verdict and signal legend

Running the same subcommand without `--min` lists every tier and prints the legend
the analyst needs to read the signals. Actual tail of the output:

```text
  Signal legend  (AUTHORITATIVE = independent evidence · HEURISTIC = suggestive $SI-only):
    [AUTHORITATIVE]
      USN_BASIC_INFO_CHANGE  the USN journal recorded a deliberate basic-info edit (no content change)
      USN_CREATE_MISMATCH    $SI created differs from the FILE_CREATE journal record (true birth known)
      HARDLINK_MACB_MISMATCH one hard-link name's $SI created diverges from another's (ReFS per-name
                             MACB). Nothing routine produces this; which name is authentic is NOT
                             established, and its absence means nothing
    [HEURISTIC — $SI only, corroborate]
      CHANGE_LATE            $SI change-time post-dates created/modified (SetFileTime/PowerShell/.NET
                             can't reach change-time) — defeated by a native-API/raw-disk stomp
      PRE_FORMAT / FUTURE    created before the volume existed / after its last write
      CREATE_GT_MODIFY       created after last write
      ROUND_TIMESTAMPS       created AND modified are whole-second (.0000000) — a tool often sets a
                             date with no sub-second time; LOW only (driver packages / archive
                             extraction also produce whole-second times)
  Note: PRE_FORMAT / CHANGE_LATE / CREATE_GT_MODIFY also fire on a legitimate
  timestamp-preserving copy (robocopy /COPY:T, a restore, an archive extraction) — and
  equally on a deliberately backdated creation. That pair alone is INFO: ambiguous, not
  cleared. The one intrinsic signal that reaches HIGH is HARDLINK_MACB_MISMATCH, which a
  copy cannot produce; corroborate anything below HIGH with the USN journal.
```

`CHANGE_LATE` is the ReFS analogue of NTFS's `$SI`-vs-`$FN` check: ReFS keeps only one
timestamp set, so instead of a second set we use the **not-normally-reachable change
time** (`$SI +0x10`) as the reference. `PRE_FORMAT` looks like a hard physical
impossibility — a file cannot predate its own filesystem — but that reasoning is about
the *file*, not about the *copy*: a timestamp-preserving copy carries a birth from the
volume it came from, which naturally predates this one.

That is why **their agreement is not conclusive**, and why the pair rates `INFO`.
Accumulating heuristic signals does not make them authoritative; it only makes the same
ambiguity fire more often. What lifts a row to HIGH is evidence from outside the
timestamps — the change journal, or a disagreement between a file's own hard-link names.

### Step 3 — Pull a single flagged record

```sh
python3 forefst.py image.raw timestomp --json
```

Actual flagged row (one JSONL object, abridged to the fields that matter):

```json
{
 "parent_path": "test/.../elvis_dir_output_358165",
 "file_name": "xbpt_zulu_india_473528.csv",
 "file_size": 472261,
 "is_directory": false,
 "created": "2024-08-03 07:17:33.0580290",
 "modified": "2024-08-03 07:17:33.0580290",
 "changed": "2026-05-23 07:34:05.8110736",
 "accessed": "2024-08-03 07:17:33.0580290",
 "file_attributes": "Archive",
 "timestomp_flags": "CHANGE_LATE|PRE_FORMAT",
 "refs_version": "3.14"
}
```

This is **not** the HIGH row from Step 1 — it is the *other copy of the same forged file*, and the
difference between them is the whole point. The volume carries `xbpt_zulu_india_473528.csv` twice: this
one under `test/`, flagged **INFO** on `CHANGE_LATE|PRE_FORMAT` alone, and the one under `test2/` that
appears in Step 1 as **HIGH**, carrying the same two intrinsic signals *plus*
`USN_BASIC_INFO_CHANGE` and `USN_CREATE_MISMATCH`. Both were stomped identically; only one left a
journal record, and only that one reaches HIGH. Their forged birth is the same instant
(`2024-08-03 07:17:33`); their real last writes differ (`07:34:05` here, `07:38:52` there). The
signature
of a common-tool stomp is laid bare here: **B = M = A** were all rewritten to the
forged 2024 instant in one `SetFileTime`-style call, while **C** (`changed`) stayed at
the real 2026 write — because the high-level API has no `ChangeTime` parameter to
reach it. The two intrinsic indicators are computed straight from the `$SI` MACB times; the journal, when
present, is what raises the row above INFO.

## What this tells you

- The file `xbpt_zulu_india_473528.csv` was created **2026-05-23** (its real change
 time, and after the volume was formatted) but its creation/modify/access times were
 forged back to **2024-08-03**. That is a deliberate back-date, not a copy artifact.
- The proof is layered: `PRE_FORMAT` is a physical impossibility (created before the
 volume existed), and `CHANGE_LATE` shows the asymmetry common timestomp tools leave
 behind. With the USN journal present, the `BASIC_INFO_CHANGE` records on this image
 would independently confirm the same.
- Method, not single value: a lone old creation date is only a suspicion. The
 `forefst.py timestomp` HIGH tier means **two independent anchors agree**, which
 on this one ground-truth image produced 137 HIGH detections, all true positives (0 false positives on
 the clean control) — a single-image datapoint, not a measured accuracy rate.
- **There is one surface.** `forefst.py timestomp` is where a timestamp anomaly is judged; `files` carries
 no verdict column. Earlier releases had both, and the listing column — which cannot read the journal —
 could only ever report the weaker half of the answer while looking like the answer.

## See also

- [Timestomping detection](../concepts/timestomp_detection.md) — the three anchors,
 the signal table, and the confidence-tier logic
- [Artifact timeline](../concepts/artifact_timeline.md) — every ReFS timestamp source
 and how to cross-validate them
- [$STANDARD_INFORMATION](../attributes/STANDARD_INFORMATION.md) — the MACB FILETIMEs
 at `$SI +0x00/+0x08/+0x10/+0x18` (value region from offset `0x28`)
- [USN journal](../structures/usn_journal.md) — the `BASIC_INFO_CHANGE` and
 `FILE_CREATE` records used as the authoritative anchor
- [$VOLUME_INFORMATION](../attributes/VOLUME_INFORMATION.md) — volume creation time at
 `+0x90`, the `PRE_FORMAT` lower bound
- Master **§C.7** ($STANDARD_INFORMATION timestamps), **§C.13** (USN journal records)
