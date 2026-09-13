# Driver builds analysed

Every structural claim on this site is checked against the `refs.sys` driver as well as against disks. This
page records **which builds of that driver have been read**, and what changed from one to the next.

It matters for two reasons. A feature visible on disk has a code path that created it, so knowing which
builds were examined tells you how far the evidence reaches. And when Microsoft services the driver, the
question an examiner actually needs answered is narrow: *did anything change that alters how a volume is
written or read?* The short answer for every build below is no — the changes are servicing work, and the
on-disk format is untouched.

## The builds

| Windows | ReFS format | Driver version | Notable |
|---|---|---|---|
| Windows 10 1803 | 3.4 | `10.0.17134.1` | The v3.4 baseline. No inline storage, no backing records. |
| Windows 11 24H2 | 3.14 | `10.0.26100.8115` | The v3.14 reference used throughout this site. |
| Windows 11 24H2 | 3.14 | `10.0.26100.8521` | A fix found by fuzzing; two feature flags graduated. |
| Windows 11 24H2 | 3.14 | `10.0.26100.8972` | The largest servicing change in this range. |
| Windows 11 24H2 | 3.14 | `10.0.26100.9444` | A security fix in the memory-mapped read path. |
| Windows Insider | 3.14+ | `10.0.29574.1000` | Subsystems absent from production 24H2. |

Each was read with full symbols, so the functions named below are the driver's own names, not inferred
labels.

## What changed, build to build

### 26100.8115 to 26100.8521

Small. An access-violation fix arrived behind a flag named for fuzzing, and two earlier feature flags were
**graduated** — the flag was removed and the behaviour became unconditional. The two functions that changed
most are the ones that find a starting node in a tree and the one that deallocates ranges.

### 26100.8521 to 26100.8972

The substantial one: 69 functions changed size, against 6 in the previous step. Almost all of it is
internal tidying, and two changes are worth stating precisely because a casual reading gets them backwards.

**`RefsUpgradeVolume` did not disappear — it was folded into the function that called it.** It had exactly
one caller; in the newer build that caller absorbed it and grew by roughly 250 lines. Volume upgrade works
exactly as before. A diff that only lists added and removed names reports this as a removed capability,
which would be wrong.

**A predicate was renamed, and the new name is more accurate.** What the older build called
"does this stream have checksums" the newer one calls "does this stream use copy-on-write". The code is
identical — same field, same callers — so nothing about behaviour changed; Microsoft corrected the name.
The field it reads means *uses copy-on-write*.

Three other renames follow the same pattern, including one that replaces a DES-era key comparison with its
AES equivalent. Two flags covering trash-table work graduated.

### 26100.8972 to 26100.9444

Small, with one item of substance: a **security fix in the memory-mapped read path**. A new range check
validates that an offset is non-negative, does not run past the end, and that offset plus length lands
exactly on the end. It is reached from one function and sits behind a servicing flag. Separately, several
encryption functions grew; that work is unrelated to the fix.

## A driver's version is not a volume's format

These two numbers are different things, and confusing them is an easy mistake to make:

- **The volume's format** — what the filesystem on the disk actually is; the newest format any released
  Windows writes is **3.14**.
- **The driver's version** — which build of `refs.sys` is doing the reading. A preview driver reports a
  *maximum supported version* of **3.15**, meaning that is the newest format it would be capable of writing.

A driver also records itself on the volume: `$VOLUME_INFORMATION` keeps the highest driver build that has
ever mounted it, separately from the volume's own format. So a 3.14 volume mounted once by a preview build
carries format 3.14 and driver 3.15 — which is a useful forensic signal that a preview build touched it, and
says nothing about the format.

**Nothing on this site is verified on a 3.15 volume, because no volume is formatted 3.15.** See
[Volume Information](../structures/volume_info.md) for the two fields and
[Format Support](../format_support.md) for what has been measured on what.

## What this means for reading a volume

Nothing on disk changed across these builds. Every structure this site documents — how a record is framed,
where a directory's flag lives, the limit on storing a file's bytes inside its record, the checksum
algorithm, the journal's dispatch table, the way containers translate addresses, and the tree search that
walks into an embedded sub-tree — is identical in all of them.

That is the useful conclusion: **a volume written by any of these builds is read the same way**, and an
examiner does not need to know which servicing update wrote a volume in order to interpret it.

## Cross-references

- [Driver Interface](driver_architecture.md) — what the imports, embedded codecs and class tables reveal
  about which features a build can produce
- [Driver Transitions](driver_transitions.md) — which driver function changes a file's placement or its
  data residency, per build
- [Format Support](../format_support.md) — which ReFS format versions the tool reads
