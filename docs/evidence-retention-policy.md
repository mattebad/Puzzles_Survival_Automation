# Evidence retention policy

This policy keeps the repository useful for deterministic replay while preventing raw live-session
captures from silently becoming Git history. It applies only to the checked-out repository and its
external evidence archive; `.local-reference/` is always excluded and remains read-only.

## Storage classes

- Tracked canonical evidence contains concise session records, manifests, promoted fixtures, Bliss
  runtime templates, and the minimum decisive source/immediate-before/postcondition proof for a
  passed consequential action.
- Local untracked evidence contains raw session captures, temporary worker/transfer copies, raw
  annotations, and diagnostic frames while a session is active. It is not automatically deleted.
- External archive storage is content-addressed at `blobs/<sha256>`, with operation manifests at
  `manifests/<operation>.json` and an original-path mapping in `path-index.json`.
- Audit JSON and plans live under `artifacts/`, outside `evidence/`, so an audit never inventories
  its own output.

## Minimum retention

Ordinary navigation retains the source frame, the immediate-before frame, the dispatched result,
the bounded successor/post frames, the navigation journal, and a concise session record. Diagnostic
frames may be compacted only when they are exact duplicates, transfer copies, or reproducible
derivatives and the canonical source remains available.

Every consequential action retains its source, immediate-before, postcondition proof, action
journal, and failure/ambiguity evidence. Decisive evidence is never removed merely because a later
attempt succeeded. An unresolved consequential action retains all associated frames, metadata,
immutable source journal, and reconciliation material until positive manual reconciliation or a
verified no-effect cancellation is recorded.

SQLite source journals, SQLite WAL/SHM sidecars, and reconciled journal copies are protected by
default. They may be externally archived only through the verified archive workflow and are never
deleted by a dry-run or by a deletion-only command.

Fixtures used by deterministic tests are promoted to tracked portable fixtures. Bliss-native
runtime templates and their provenance remain tracked. A concise manifest or session summary must
name every promoted artifact, profile, source hash, and purpose.

## Classification and compaction

`python3 scripts/evidence_hygiene.py audit` is the authoritative dry-run inventory. It records each
file's path, size, streaming SHA-256, Git state, session, file type, text/journal references,
duplicate group, retention class, proposed action, and recoverable bytes. `plan` prints only the
dry-run candidate set.

Automatic compaction is limited to byte-identical duplicates, repeated identical frames, retained
transfer/worker copies, and reproducible generated annotations when the raw frame and annotation
metadata remain. Untracked zero-input navigation attempts and superseded raw sessions require a
retained summary, hashes, and a verified external archive. `UNKNOWN_REVIEW_REQUIRED` is never
compacted automatically. Tracked paths remain in Git unless a separate focused review updates every
reference and provides an archive-backed rollback.

The archive command is dry-run by default:

```text
python3 scripts/evidence_hygiene.py plan
python3 scripts/evidence_hygiene.py archive --archive-root ../Puzzles_Survival_Automation_evidence_archive
python3 scripts/evidence_hygiene.py archive --archive-root ../Puzzles_Survival_Automation_evidence_archive --execute
python3 scripts/evidence_hygiene.py verify --archive-root ../Puzzles_Survival_Automation_evidence_archive
```

`--execute` is the only removal-capable mode. It rechecks the source hash, copies the blob, verifies
the copied blob, writes the path index and operation manifest, rechecks the source, and only then
removes an eligible untracked or ignored duplicate. Operations are restartable: an already verified
blob and `source_removed` manifest entry are accepted on a later run. A missing or changed source,
symlink, manifest mismatch, or failed verification stops the operation.

## Session lifecycle and naming

Use `evidence/sessions/<YYYYMMDD>-<task-or-purpose>/<attempt-or-state>/` for session material. Keep
raw captures in a future `raw/` subtree, worker/transfer copies in explicitly named subtrees, and
promoted fixtures/templates in a stable `assets/` subtree with a manifest. A completed session must
have a concise `record.md` or `summary.json` stating status, hashes, retained canonical paths,
unresolved state, and whether an external archive operation was verified.

At session completion, reconcile or explicitly preserve every journal boundary, generate an audit,
review duplicate candidates, archive before any local removal, verify the archive, and record before
and after bytes. No credentials, private keys, or login/tutorial/CAPTCHA material may be retained.

## History boundary

This policy does not rewrite Git history. The audit reports active-checkout savings separately from
reachable historical evidence blobs and the upper bound of history-only blobs. Any future history
rewrite would require a separately approved, reviewed migration and is not part of routine hygiene.
