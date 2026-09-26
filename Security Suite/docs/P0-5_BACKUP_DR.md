# P0-5 — Backup & Disaster Recovery

**Status: SPECIFIED, NOT IMPLEMENTED. Infrastructure work outside the module
boundary.**

BRD Section 9, risk 3: no backup/DR requirement was specified in the original
concept, and "an immutable log is not useful if the underlying system cannot be
restored."

## The tension that has to be resolved deliberately

Backups and immutability pull against each other, and the resolution should be
an explicit decision rather than an accident of tooling:

- A restore from backup **rewinds the Locker**. Any audit entry written after
  the backup point vanishes. An attacker with restore rights therefore has a log
  deletion primitive that never touches the log tables.
- Therefore: the external replica (P4-1) must be **append-only and outside the
  restore blast radius**. Restoring the application database must not, and must
  be technically unable to, roll back the replica.
- Therefore: after any production restore, a **reconciliation run (P4-2) is
  mandatory**, and any primary-vs-replica gap it finds is a reportable event,
  not a nuisance to be silenced. This is the single most likely way a real
  tampering attempt would show up.

## Minimum requirements

1. Automated daily full backup plus continuous WAL archiving, with a stated RPO
   and RTO agreed with the CEO/Owner.
2. Backups encrypted at rest, stored off-host, with access separate from the
   application DBA.
3. **Restore tested on a schedule**, not just configured. An untested backup is
   a belief, not a control. Record each test date and result.
4. Filestore (`/var/lib/odoo/filestore`) included. The Written/Oral instruction
   attachments required by FR-1.3 live there; losing them destroys the evidence
   the override workflow exists to capture.
5. Retention aligned with the Locker retention period — which PRD Section 12
   lists as an unanswered question and which Legal/Compliance still owe us.
6. Post-restore runbook that includes the reconciliation step above.

## Evidence required to close this task

- Backup schedule configuration and where backups are written.
- Date and outcome of the most recent successful restore test.
- Written confirmation that the external log replica is outside the restore
  path.
- Agreed RPO/RTO figures.

None of the above exists yet, so the task remains open in `PROGRESS.md`.
