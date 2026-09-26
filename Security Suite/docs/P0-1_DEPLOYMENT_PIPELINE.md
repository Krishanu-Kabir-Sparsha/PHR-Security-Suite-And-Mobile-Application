# P0-1 — Deployment Pipeline & Removal of Direct Production DB Access

**Status: SPECIFIED, NOT IMPLEMENTED. This is infrastructure work outside the
Odoo module boundary and cannot be completed by writing addon code.**

BRD Section 9, risk 1 calls this "the single highest-leverage fix" and says it
"should precede or accompany this initiative". PRD Section 11, dependency 1 goes
further: it "blocks the credibility of Phase 1 freeze guarantees if not done
first".

That framing is correct and worth restating plainly: **a developer with a psql
prompt on production defeats every control in this suite.** The ORM overrides in
`sec_record_freeze` are application-layer. The PostgreSQL triggers planned for
P1-5 are stronger, but a superuser drops triggers. The Locker is only tamper-
*evident*, and only once P4-1 replication is live. Until direct production
access is gone, this system raises the effort required to make an undocumented
edit; it does not make one infeasible. Do not let the project describe itself
otherwise to the CEO/Owner.

## Required target state

1. **No standing human access to the production database.** Developer accounts
   hold no production credentials. `postgres` superuser credentials live in a
   secrets manager with checkout logging, not in anyone's `.pgpass`.
2. **All schema and data changes arrive through version control.** Odoo module
   upgrades and `migrations/` scripts are the only mechanism; nothing is applied
   by hand. This is already mandated for this repository in the master build
   prompt, Section 4.
3. **A CI/CD pipeline** that lints, runs the test suites against a throwaway
   database, builds, and deploys. Deployment credentials belong to the pipeline
   service account, not to people.
4. **Break-glass production access** exists, but is: time-boxed, requested with
   a stated reason, approved by someone other than the requester, session-
   recorded, and alerted on. The surveillance dashboard (P3-1) should ingest
   these events, since a break-glass session is exactly the circumstance under
   which the Locker most needs corroboration.
5. **Organisational separation** between the application DBA and whoever holds
   infrastructure superuser rights, per BRD Section 8.2. Without two different
   people, external log replication protects against accident but not against a
   coerced or malicious administrator, which is the stated threat.

## Recommended sequencing decision

PRD Open Question 5 asks whether P0-1 must block the start of Phase 1
engineering. Recommendation: **no for engineering, yes for go-live.** Phase 1
code can be written and tested in parallel. But the freeze engine must not be
presented to the business as delivering its guarantee, and the Unified
Declaration should not be put in front of staff asserting personal liability,
until direct production access is closed. Asking someone to accept personal
liability for a system that a colleague can silently edit around is not a
defensible position.

## Owner

Infrastructure / DevOps, with the Executive Sponsor. Not the module development
team. This document is the module team's specification of what it needs; it is
not evidence that it happened.

## Evidence required to close this task

- Named pipeline (repository URL, CI configuration file).
- Confirmation that developer production DB credentials have been revoked, with
  a date and who verified it.
- Break-glass procedure document plus one tested dry run.
- Named holders of the application-DBA and infrastructure-superuser roles,
  confirming they are different people.

None of the above exists yet, so the task remains open in `PROGRESS.md`.
