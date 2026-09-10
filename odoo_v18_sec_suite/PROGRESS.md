# Build Progress Log

Odoo CE V18 — Advanced Security, Access Control & Immutable Audit System

> **Read this file and `BUILD_STATE.json` in full before writing any code.**
> They are the source of truth for what is done, not the phase list in the
> master build prompt, which only describes the target end state.

## Current Status

- **Phase:** ALL 22 BUILD TASKS ADDRESSED — the build is code-complete
- **Last completed task:** P4-5
- **In-progress task:** none
- **Next task:** none in the task list. **The project is not finished.** See
  "What remains" below: no test has ever been executed, and four Phase 0
  infrastructure items are still open.
- **Last updated:** 05 September 2026, session 24

> **Phases 1, 2 and 3 are code-complete. All nine modules exist.** 407 tests
> written, **0 executed**. Everything stated about this system's behaviour is a
> claim about code, not a demonstrated property. Running the suites against a
> real Odoo 18 database remains the single highest-value outstanding action.

> **Phases 1 and 2 are code-complete.** The BRD's central claim is implemented
> end to end: a confirmed record cannot be changed except through three
> independent WebAuthn-authenticated approvals, and then only in the exact way
> approved. **294 tests exist and none has ever been executed.** Until they run
> against a real Odoo 18 database, this is a claim about code, not a
> demonstrated property of your system.

> **Phase 1 is code-complete but not verified.** All seven tasks are written;
> none has been executed. 143 tests exist, 0 have run. Do not describe Phase 1
> as delivered to the business on this basis.

### Blocking caveat that applies to every "done" below

The build environment has **no Odoo runtime and no PostgreSQL** (verified in
session 1 — see `docs/VERIFICATION_STATUS.md`). Test suites have been written
but **never executed**. Tasks below are therefore marked `code-complete
(untested)` rather than `done`, per the master build prompt's rule against
marking work done speculatively. Promote them to `done` only after running:

```bash
odoo -d <db> -i sec_plaza_rbac --test-enable --test-tags /sec_plaza_rbac --stop-after-init
```

## Task Checklist

### Phase 0 — Foundations

- [ ] **P0-1 — open (infrastructure, not module work)** — specification written
  at `docs/P0-1_DEPLOYMENT_PIPELINE.md`, including the evidence needed to close
  it. Nothing has been implemented; the module team cannot close this. Blocks
  go-live, not Phase 1 engineering (recommendation documented, needs owner
  sign-off — see Open Questions).
- [x] **P0-2 — code-complete (untested)** — `sec_plaza_rbac` built:
  `role.plaza_model` + `role.plaza_model.access`, 15 seeded roles with backing
  groups and access matrices, bounded-catalog constraints, catalog readiness
  check, non-standard grant guard. *Verified by:* `tools/validate_addons.py`
  clean (syntax, XML, manifest, ACL coverage, Odoo 18 view syntax) plus a static
  self-check of the seed catalog (15 roles in the 10–20 band, unique codes, all
  three approval tiers present, exactly one Nuclear Key, no intra-role SoD
  breach). *Not verified:* anything requiring a database.
- [x] **P0-3 — code-complete (untested)** — `plaza.sod.scan` / `plaza.sod.conflict`
  cross-role segregation-of-duties checker, with accept-as-residual-risk
  requiring a written note and a named approver, plus `latest_scan_summary()`
  for the monthly forensic report to consume. Views, menu and server action in
  place. 10 tests written in `tests/test_sod_checker.py`. *Not verified:* not
  executed.
- [ ] **P0-5 — open (infrastructure, not module work)** — specification written
  at `docs/P0-5_BACKUP_DR.md`, including the backup-vs-immutability tension and
  the mandatory post-restore reconciliation. Not implemented.
- [x] **P0-4 — done** — OCA `auditlog` (`18.0.2.0.9`, `OCA/server-tools@18.0`)
  and `base_tier_validation` (`18.0.3.4.1`, `OCA/server-ux@18.0`) both confirmed
  ported and released for V18 by direct inspection of the upstream branches.
  API surface captured for Phase 2 in `docs/OCA_V18_COMPATIBILITY.md`. This one
  *is* fully verified, because the claim it makes ("these modules exist and
  declare V18") is exactly what was checked. Runtime compatibility against our
  database is a separate, still-open question, stated as such in the doc.

### Phase 1 — Core Enforcement (MVP)

- [x] **P1-1 — code-complete (untested)** — `sec_declaration_gateway`:
  `declaration.version` (SHA-256 text hash, single-published-version constraint,
  legal-approval gate on publish, text locked once accepted),
  `declaration.signoff` (append-only: write and unlink both raise), and the
  blocking gate in `ir.http._dispatch`. Ships an unpublished placeholder
  containing no legal wording, so install locks nobody out. 18 tests written.
- [x] **P1-2 — code-complete (untested)** — `sec.instruction.mixin` +
  `sec.edit.request`: mandatory Written/Oral classification, attachment required
  for both types, instructing supervisor required for oral, server-side
  re-validation on submit. The mixin exists so P2-5's `override.request`
  inherits the same rules rather than reimplementing them. 11 tests written.
- [x] **P1-3 — code-complete (untested)** — blocked submissions raise a
  `missing_documentation` anomaly at `high` severity, written **on a separate
  cursor** so it survives the rollback of the blocked transaction. Alert model
  and raising mixin live in the new `sec_core` module.
- [x] **P1-4 — code-complete (untested)** — `sec_record_freeze`:
  `sec.freeze.rule` configuration model with field-existence validation,
  `sec.record.freeze.mixin` overriding `write()`/`unlink()`, attached to
  `sale.order`, `purchase.order`, `account.move` **and their line models**.
  Blocked attempts raise a critical anomaly on a separate cursor. `sudo()` and
  `uid=1` are both covered by tests as non-bypasses. 20 tests written.
- [x] **P1-5 — code-complete (untested)** — PL/pgSQL guard function plus a
  per-table trigger generated from the rule configuration. Refuses UPDATE of
  protected columns and DELETE of frozen rows, resolves line-table state from
  the parent document, and permits no-op writes via IS DISTINCT FROM. Installed
  by post-init hook and by a versioned migration; dropped by the uninstall hook.
  `verify_triggers()` raises a critical anomaly on any missing trigger, for the
  P4-2 reconciliation job to call. 15 tests written, all going at the tables
  with raw SQL. Rendered SQL saved for DBA review at
  `migrations/18.0.1.1.0/reference_guard_function.sql`.
- [x] **P1-6 — code-complete (untested)** — `sec.stream.lock`: independent
  Sales / Purchase / Accounting lockdown toggles, Super Admin only, mandatory
  written reason captured in a confirmation wizard, append-only toggle log with
  actor / timestamp / before-after / source IP, critical anomaly on every
  toggle. Enforced in the freeze mixin's `create`, `write` and `unlink`, so a
  lockdown covers draft records too. The `locked` field cannot be written
  directly. 18 tests written.
  **WebAuthn gap, deliberate:** US-3.2 requires WebAuthn confirmation. It does
  not exist until P2-2, so each log entry carries `strongly_authenticated`
  (currently False) rather than asserting a confirmation that did not happen.
  Flip `sec_record_freeze.allow_toggle_without_webauthn` to False when
  `sec_webauthn_auth` deploys.
- [x] **P1-7 — code-complete (untested)** — `sec_audit_locker` on OCA
  `auditlog` 18.0.2.0.9. Adds the three things upstream lacks: **source IP**
  (OCA captures none, despite FR-4.1 requiring it), **immutability** (`write`
  and `unlink` raise on both `audit.locker.entry` and `auditlog.log`), and
  **tamper evidence** via a SHA-256 hash chain with a serialised chain head.
  Daily verification cron; a break raises a critical anomaly. Audit scope is
  selective per BRD risk 6: read logging off everywhere, `fast` on business
  models, `full` on control-configuration models. 25 tests written, including
  raw-SQL tampering and deletion detection.

### Phase 2 — Authorization & Identity

- [x] **P2-1 — code-complete (untested)** — `sec_webauthn_auth`:
  `sec.webauthn.credential` (public key only, immutable crypto material,
  revoke-never-delete), `sec.webauthn.challenge` (single-use, 5-minute TTL,
  purpose-bound), `sec.webauthn.config` enforcing a set RP ID and an HTTPS
  origin, enrolment page with the browser ceremony, revocation, and
  `check_enrolment_sufficient` implementing FR-6.5 (two authenticators for the
  Nuclear Key holder). 25 tests written.
  **Enrolment deliberately cannot complete until P2-2:**
  `/webauthn/register/verify` refuses to store a credential while
  `_verification_ready()` is False. Storing an unverified public key would mean
  trusting whatever the browser sent, for the credential that will authorise the
  CEO/Owner's final approvals.
- [x] **P2-2 — code-complete (untested)** — registration and authentication
  ceremony verification via `py_webauthn` 3.0.0, API read from the installed
  library rather than recalled. Enrolment now stores credentials; approvals can
  be confirmed. `user_verification` is `required` on both ceremonies. Sign
  counter is writable only by the verification path. A `18.0.1.1.0` migration
  withdraws the P1-6 weak-toggle exemption automatically. 20 tests written.
  **Assertions are bound to one action:** every challenge carries a
  `context_ref`, verification refuses a mismatched context, and the success
  marker lives on the HTTP request rather than the session. Without this, one
  confirmation would authorise anything else in the same session.
- [x] **P2-3 — code-complete (untested)** — cloned-authenticator detection.
  A validly-signed assertion with a regressed counter revokes the credential,
  blocks the approval, raises a critical alert and notifies the owner directly.
  14 tests written.
  **The non-obvious part:** py_webauthn checks the counter *before* verifying
  the signature, so a forged low-counter response reaches the regression path
  without the attacker possessing the key. Naive revoke-on-regression would let
  anyone remotely disable an approver's authenticator — a denial-of-service on
  the Nuclear Key. Suspected regressions are re-verified with the counter check
  neutralised; only a valid signature means a clone. A forgery is alerted and
  the credential is left alone.
  **Second finding:** synced passkeys report a constant zero counter, so clone
  detection is impossible for them. Flagged as `counter_supported = False` and
  reported rather than hidden — a real argument for a hardware key as the
  CEO/Owner's second authenticator.
- [x] **P2-4 — code-complete (untested)** — break-glass recovery.
  `sec.webauthn.recovery.request` with append-only approvals: two distinct
  approvers, neither the requester, each WebAuthn-confirmed, opening a
  single-use 24-hour enrolment window. 19 tests written.
  **Enrolment now takes one of three routes**, decided in
  `_check_enrolment_permitted`: first enrolment is self-service; adding a device
  while one still works requires confirming with the existing key (stronger and
  lighter than convening approvers, and FR-6.5 needs it usable); replacing when
  nothing works requires the grant.
  **Interim rule, flagged for revisit:** approvals live here rather than in the
  override engine because of the P2-5 circular dependency the master prompt
  warns about.
- [x] **P2-5 — code-complete (untested)** — `sec_override_engine` on OCA
  `base_tier_validation` 18.0.3.4.1. `override.request` inheriting
  `tier.validation` and `sec.instruction.mixin`, six seeded policy exception
  categories, three tier definitions wired to Plaza role groups, submission
  gated on a frozen target, a live category, complete documentation and a
  category-level attachment rule. Justification and proposed changes lock once
  under review so Tier 3 approves what Tier 1 saw. 20 tests written.
- [x] **P2-6 — code-complete (untested)** — WebAuthn-gated sequential approval.
  `validate_tier` refuses any tier without an assertion bound to that specific
  request, verified in the same HTTP round trip; if verification is unavailable
  the approval is refused rather than downgraded. `override.approval` records
  the PRD approval entity with the authentication evidence, append-only. Mobile
  approval page at `/override/approve/<id>` per PRD Section 9. Rejection is
  deliberately not gated. 18 tests written.
- [x] **P2-7 — code-complete (untested)** — collusion prevention. Blocks the
  requester approving, one user satisfying two tiers, and two logins sharing a
  `res.partner`. Flags (does not block) two tiers approved from one address.
  `_assert_executable()` re-derives three distinct, WebAuthn-confirmed, per-tier
  approvals from stored records rather than trusting `state`. Every blocked
  attempt raises a critical anomaly. 16 tests written.
- [x] **P2-8 — code-complete (untested)** — execution. `override.change`
  carries structured field/value pairs (approving prose alone would mean the
  signatures attest to something nobody checked). `sec.freeze.unlock.ticket`
  is single-use and scoped to one record and one field set, so an approval for
  a price correction cannot be spent on the counterparty, and never authorises
  deletion. Execution tells both enforcement layers separately: the ORM check
  reads the ticket, and `SET LOCAL sec.freeze_unlock` lets the P1-5 trigger
  through for that transaction only, reset in a `finally`. Re-freezing is
  ticket consumption, not a state change, so there is no window to forget to
  close. A Locker entry records the whole chain. 19 tests written, including
  the end-to-end claim.

### Phase 3 — Oversight & Reporting

- [x] **P3-1 — code-complete (untested)** — `sec_surveillance_dashboard`.
  Adds the one US-7.1 anomaly class nothing raised before (**out-of-hours
  edits**), evidence links from each alert to its Locker entries and override
  request, and kanban/list/graph/pivot triage views. 24 tests written.
  Two decisions that determine whether the dashboard survives contact with
  users: detection converts UTC to a **configured local timezone** (comparing
  UTC hours directly would flag an entire Bangladeshi workday), and out-of-hours
  alerts are **low** severity (a dashboard where routine evening work shows as
  high severity teaches its reader to ignore high severity).
- [x] **P3-2 — code-complete (untested)** — `sec.value.threshold`: per
  model/field thresholds with three comparison modes (delta, absolute,
  increase), configurable severity and a named tuning owner. Rejects thresholds
  on non-numeric or non-existent fields at configuration time. **Ships with no
  default thresholds** — PRD Section 12 leaves the figures to the business, and
  an invented number would look like a decision nobody made. `coverage_report()`
  and the configuration checker say plainly when none is configured, so an empty
  dashboard section cannot be mistaken for coverage. 24 tests written.
- [x] **P3-3 — code-complete (untested)** — triage is now auditable.
  `anomaly.review` is an append-only record of every decision: who, when,
  outcome from a bounded list, mandatory note, state before/after, and whether
  it was part of a batch. Mirrored to the Locker. Escalation and reopening are
  logged the same way. The Phase 1 `action_mark_reviewed`, which required a note
  but recorded nothing about who concluded what, has been replaced.
  Bulk review exists but is deliberately awkward: every row marked `bulk`, and
  high/critical alerts refused in a batch. 25 tests written.
- [x] **P3-4 — code-complete (untested)** — `sec_forensic_reporting`.
  Assembles the report methods each module has carried since it was built,
  rather than re-querying their tables: two implementations of the same
  judgement would eventually disagree, and a discrepancy would be invisible.
  Covers the override log with Written/Oral instruction source (FR-4.4),
  declaration reconciliation including hash mismatches, anomaly summary with
  triage activity, SoD status, and control health. On-demand and monthly cron;
  a second report for a period is a new version. 20 tests written.
  **Findings lead the report, and an unconfigured control counts as one.** An
  empty section otherwise reads the same whether nothing happened or the
  control was never switched on. A section that cannot be gathered becomes a
  finding rather than a blank.
- [x] **P3-5 — code-complete (untested)** — reports immutable and versioned.
  `write()`/`unlink()` refuse once generated, including under `sudo()`, with two
  narrow exceptions genuinely learned afterwards (PDF rendering, supersession).
  Payload hashed at generation, re-checked on read and by a daily cron, with a
  critical anomaly on mismatch. PDF rendered once and stored, so a later
  template change cannot alter what a historical report said. New versions
  supersede rather than overwrite, linked in both directions. 20 tests written.
  **Before this task, generated reports were fully editable** — only
  regeneration over an existing record was blocked. Found while completing
  P3-4.

### Phase 4 — Hardening & External Compliance

- [x] **P4-1 — code-complete (untested)** — external Locker replication.
  `audit.replica.target` with two implementations: append-only file (`O_APPEND`,
  fsynced) and HMAC-signed HTTPS endpoint. Entries ship **with both hashes**, so
  the replica holder can verify the chain without trusting the primary. Queued
  and shipped by a five-minute cron, never inline — replication must not be able
  to fail a business transaction. A batch reaching no target leaves entries
  pending rather than silently marking them shipped. 20 tests written.
  **The absence of a target is reported as a failure**, not as an empty backlog:
  "nothing pending" is technically true and dangerously misleading when
  replication was never configured.
  **Not solvable in code:** BRD Section 8.2 requires the replica to be
  administered by someone other than the application DBA. Each target records a
  named custodian; the separation itself is organisational.
- [x] **P4-2 — code-complete (untested)** — daily reconciliation.
  Compares primary against every readable replica on three axes, and treats them
  very differently: missing-in-replica is lag (low), differing hashes is a
  mismatch (critical), and **entries present in the replica but missing from the
  primary is `primary_missing` (critical)** — that cannot happen through the
  application and is the signature of rows deleted straight from the database.
  Results are append-only. 23 tests written.
  **`unverifiable` and `never_run` both count against a clean status.** A target
  with no read-back path is not a passing target, and a report saying "no
  mismatches" about a replica it could not read would be worse than none.
- [x] **P4-3 — done (document)** — `docs/SOC2_ISO27001_CONTROL_MAPPING.md`.
  Maps the suite against SOC 2 Trust Services Criteria and ISO/IEC 27001:2022
  Annex A, with status per control and the gap named where there is one.
  This one is genuinely *done* rather than code-complete-untested, because the
  deliverable is an assessment and the assessment has been made. Its central
  finding is that **four of the five things an assessor will ask about first are
  not code problems**: no executed tests, P0-1 open, no replication target
  configured, no incident response runbook, no tested backup. Also records that
  SOC 2 Type II and ISO both require *operating effectiveness over a period*,
  which a newly deployed system cannot have — the audit window needs planning
  rather than discovering during scoping.
  **Caveat recorded in the document:** control identifiers were written without
  access to the standard texts and should be confirmed by the assessor. The
  descriptions are authoritative; the numbers are a starting point.
- [x] **P4-4 — done (review), fixes code-complete (untested)** —
  `docs/P4-4_ADVERSARIAL_REVIEW.md`. **Three real bypasses found and fixed**, 24
  adversarial tests written:
  - **F-1 critical:** a line could be *added* to a frozen document. `write()`
    resolved a child's state from its parent; `create()` never did. The
    PL/pgSQL trigger had the identical blind spot (`BEFORE UPDATE OR DELETE`,
    no INSERT) — the second layer inherited the first layer's gap because it
    was written by mirroring it.
  - **F-2 critical:** approved values were rewritable before execution.
    `override.change` shipped with full rights and no guard, so three
    WebAuthn-authenticated approvals could be obtained for one change and a
    different one executed. This does not defeat the approval workflow, it
    recruits it.
  - **F-3 high:** an alert could be closed by writing `state` directly, with no
    review row, note or reviewer — the P3-3 trail was mandatory only for people
    who used the button.
  Fifteen previously-claimed defences were re-attacked and held. Residual risks
  documented and accepted.
- [x] **P4-5 — partially done; cannot be completed from here** —
  `docs/P4-5_PERFORMANCE.md` and `tools/benchmark_nfr.py`.
  **Measured for real:** Locker canonicalisation + SHA-256 is 7.3 µs per entry,
  0.01% of the 100 ms budget. The cryptography is settled and should not be
  weakened for performance.
  **Found and fixed:** every write to an in-scope model issued three SELECTs on
  configuration tables that change once a year. Now `ormcache`d on ids and
  scalars only, cleared on any rule or lock change so a lockdown still bites
  immediately.
  **Unresolved:** the Locker serialises every append on one chain-head row.
  Correct for chain integrity, and the one genuine scaling risk in the design.
  It appears only under concurrency, as a cliff. Per-model chains are the
  prepared mitigation — **do not build speculatively, measure first.**
  **Not attempted:** end-to-end screen latency and concurrent load, which need a
  running server. The harness is written for the real instance.

## What remains before this is a working system

1. **Run the test suites.** 474 tests, 0 executed. Nothing else on this list
   changes as much.
2. **P0-1** — remove standing production database access. Open since Phase 0;
   weakens several controls simultaneously and is the first thing an assessor
   asks about.
3. **P0-5** — tested backup and DR, including post-restore reconciliation.
4. **Configure external replication** and name an independent custodian, or
   FR-4.3 stays unmet.
5. **Incident response runbook** (BRD risk 7) — detection without response is
   half a control.
6. **Legal supplies the declaration text**; the gateway is dormant until then.
7. **Set high-value thresholds** and their tuning owners.
8. **Fix the WebAuthn Relying Party domain and serve over HTTPS** before anyone
   enrols.
9. **Run the concurrency benchmark** before trusting the NFR position.
10. **Commission an independent security review.** P4-4 found three real
    bypasses in one pass of self-review; that rate implies more remain.

## Open Questions Log

1. **Verification environment** — raised session 1 — *unresolved.* Where do the
   test suites actually run? Nothing in this repository can be honestly marked
   `done` until there is an Odoo 18 + PostgreSQL environment. This is the single
   highest-priority blocker; it outranks writing more features.
2. **Should the access matrix generate `ir.model.access` / `ir.rule` records?**
   — raised session 1 — *unresolved.* Today the matrix declares intent and the
   live ACLs are maintained separately, so they can drift. Auto-generation is
   the right end state but is security-critical and deserves its own task.
   Proposed as a new task **P0-6**.
3. **P0-1 sequencing** (PRD Open Question 5) — raised session 1 — *recommendation
   made, awaiting owner sign-off.* Proposal: Phase 1 engineering proceeds in
   parallel, but go-live and the Unified Declaration rollout are blocked until
   direct production DB access is removed. Rationale in
   `docs/P0-1_DEPLOYMENT_PIPELINE.md`.
4. **Does `base_tier_validation` prevent one user satisfying two tiers?** —
   raised session 1 — *unresolved, provisional answer: no.* Nothing in the
   upstream model suggests identity-distinctness across tiers. Plan on writing
   it ourselves in P2-7 rather than inheriting it. Confirm by test in Phase 2.
5. **Locker data-retention period** (PRD Open Question 1) — outstanding with
   Legal/Compliance. Blocks P0-5 retention configuration and P4-1 storage sizing.
6. **Transaction-class taxonomy** — raised session 1 — *needs business review.*
   The SoD checker groups by the eight transaction classes in
   `TRANSACTION_TYPES` (`models/plaza_role.py`). If the business thinks in
   different categories, the checker's findings will be subtly wrong. Worth 20
   minutes with the Compliance Lead before Phase 2.

## Known Deviations From Spec

1. **Catalog minimum enforced as a readiness gate, not a save-time constraint.**
   PRD US-2.1 says "min 10". A write-time minimum makes the first role
   impossible to create. Maximum (20) is a hard constraint; minimum is
   `check_catalog_readiness()`. Rationale in `docs/DESIGN_NOTES_plaza_rbac.md`.
2. **Non-standard grants are refused, not merely logged.** US-2.1's third
   criterion reads as permitting the grant with logging after the fact. Given
   the BRD threat model (an administrator acting on informal instruction), the
   implementation blocks the grant unless a pre-approved, justified, unexpired
   exception exists. This is *stricter* than specified — flagging it for the
   product owner to confirm rather than assuming stricter is automatically
   welcome.
3. **PRD entity `role.plaza_model` implemented with that exact technical name**,
   which is unusual for Odoo (mixed dot/underscore). Kept for traceability to
   the PRD data-entity table rather than renamed to `plaza.role`.
4. **`group_security_super_admin` defined in `sec_plaza_rbac`**, not in
   `sec_record_freeze` where US-3.2 uses it, to avoid a two-record `sec_base`
   module. Noted so Phase 1 knows where to find it.
5. **New module `sec_core`, not in the master build prompt's module map.**
   Holds `anomaly.alert` and `sec.anomaly.mixin`. P1-3 requires alerts to be
   raised in Phase 1 while the dashboard that consumes them is Phase 3. Without
   a shared home, `sec_record_freeze` and `sec_audit_locker` would each have had
   to depend on `sec_declaration_gateway` to reach the model.
   `sec_surveillance_dashboard` must extend this model, not redefine it.
6. **The declaration gate is a server-side dispatch check, not a modal.**
   PRD US-1.1 says "full-screen modal". A modal rendered by the web client can
   be dismissed from the browser console. Implemented in `ir.http._dispatch`
   instead, which satisfies the actual criterion ("no dashboard route is
   reachable before acceptance") more strictly. Stricter than specified —
   flagged for product owner confirmation.
7. **Administrators are not exempt from the declaration gate.** Only
   `base.user_root` is, and only because cron and module installation need it.
8. **Written instructions also require an attachment.** BRD FR-1.3 only
   mandates documentation for *oral* instructions. A written instruction with no
   written document attached is a contradiction, so both types require one.
   Stricter than specified; confirm with the product owner.
9. **Freezing is field-selective, not total.** PRD US-3.1 reads as blocking
   `write()` outright once confirmed. Implemented as blocking writes to a
   configured list of business-material fields per model. A blanket block
   breaks delivery, invoicing and reconciliation on confirmed documents — the
   module would be uninstalled within a week of go-live. The consequence, which
   the product owner must accept explicitly: a field omitted from a protected
   list is editable on a confirmed record. The six shipped lists need business
   review, especially against any custom fields.
10. **Line models freeze from their parent's state.** Not stated in the PRD, but
   without it the freeze is theatre: blocked from editing an order total, a user
   edits the order line and the total recomputes.
11. **Freeze triggers are generated, not written as static SQL.** The master
   build prompt says PostgreSQL work must live in versioned migration scripts.
   The *invocation* does; the generation logic lives in `models/freeze_sql.py`
   so it can be tested and so it stays in step with the rule configuration. A
   static .sql file would drift the moment anyone edited a protected field
   list, which for a security control is worse than no file. A rendered
   reference copy is committed for DBA review.
12. **Stream lock blocks automated jobs as well as users.** No exemption for
   `base.user_root` or for `sudo()`. A lockdown that scheduled actions can write
   through is not a lockdown. The operational consequence is surfaced in the UI
   and README rather than quietly engineered around.
13. **Toggles are recorded as weakly authenticated rather than asserted as
   strong.** See P1-6 above. The alternative — returning True from the
   confirmation hook — would write a false claim of cryptographic confirmation
   into the evidence record.
14. **The Locker claims tamper-EVIDENCE, not tamper-proofing.** FR-4.2 asks
   for entries uneditable by any role including administrators. Delivered at
   the application layer, but a PostgreSQL superuser bypasses permission checks
   by design (BRD Section 8.2 concedes this). The hash chain changes the claim
   to one that is actually true: alteration is possible but not concealable.
   The CEO/Owner should be told it this way, not the original way.
15. **No automatic log purge.** OCA's autovacuum cron is held inactive and
   `unlink()` raises. FR-4.2 forbids deletion and the retention period is still
   unanswered by Legal. An unattended nightly purge is the mechanism an insider
   would rely on.
16. **WebAuthn preconditions are enforced in code, not assumed.** The two
   unanswered questions (canonical RP domain, HTTPS) were turned into
   preconditions that refuse enrolment with a specific, actionable error rather
   than into a reason to stall the build. `rp_id` ships empty because there is
   no safe default.
17. **An assertion authorises one action, not a session.** Not stated in the
   PRD, which only requires WebAuthn on approvals. Without action binding, a
   user tricked into confirming a trivial action would have authorised any
   other privileged action in the same session — which would defeat the point
   of requiring confirmation per approval in US-5.2.
18. **Clone response is revocation, not just refusal.** US-6.2 says a
   regression "blocks the approval". Implemented as blocking *and* revoking,
   because a genuine regression means two copies of the key exist and every
   future assertion from it is equally suspect.
19. **Recovery approval is two distinct approvers, not the three-tier ladder.**
   US-6.3 says "the other two tiers". Implemented as any two approval-tier role
   holders other than the requester. The literal reading is unsatisfiable in the
   commonest real case: the CEO/Owner loses their phone, and Tier 3 is the
   CEO/Owner. Also an interim measure pending P2-5. Needs product owner
   confirmation on both counts.
20. **Adding a second authenticator does not require multi-party approval**,
   only proof of control of an existing one. Stronger than a committee for that
   case, and FR-6.5's two-device requirement for the CEO/Owner would otherwise
   be painful enough that people would avoid it.
21. **Overrides may only target a record that is actually frozen.** Not stated
   in US-5.1. Without it the engine degrades into a general-purpose approval
   workflow and the approval evidence stops implying that a frozen record was
   changed.
22. **Justification and proposed changes are locked once under review.** Not
   stated in the PRD, but without it Tier 3 could approve wording Tier 1 never
   saw, which would make sequential approval meaningless.
23. **Rejections are not WebAuthn-gated, approvals are.** FR-5.3 requires
   strong authentication for approvals. A rejection cannot change a frozen
   record, and friction on "no" would discourage the safe answer. Still recorded
   with actor, time and IP.
24. **Approval is refused, not downgraded, when WebAuthn is unavailable.** An
   approval recorded as "unconfirmed" would still complete the override, so a
   flag would be worse than a refusal here.
25. **Collusion is mitigated, not prevented.** FR-5.2 says "prevent collusion
   scenarios". What is technically enforceable is that three *distinct
   identities* sign, each on their own hardware, in sequence. Three real people
   who agree beforehand cannot be detected by software. The README states this
   plainly; the claim made to the CEO/Owner should match it.
26. **Same-source-IP approvals are flagged, not blocked.** A single-office
   company would hit this constantly, and a control that fires on everyday
   behaviour gets disabled.
27. **Approved changes must be structured, not free text.** US-5.1 asks only
   for a justification. Executing against prose would mean the three signatures
   attest to a description while the requester types whatever they like into the
   record. `change_ids` is what execution applies, and the unlock is scoped to
   exactly those fields.
28. **An unlock ticket never authorises deletion.** Deleting a confirmed
   document is not a correction; it is removal of the thing being corrected.
29. **Out-of-hours alerts are low severity and watch only in-scope business
   models.** US-7.1 lists out-of-hours edits alongside genuine violations.
   Treating "someone worked late" with the same weight as "someone tried to
   edit a frozen record" would make the dashboard unreadable, and an unreadable
   dashboard is an unused one.
30. **The shipped timezone parameter is empty deliberately.** Any hard-coded
   default is a guarantee of wrong answers in some deployment; the code falls
   back to the company timezone.
31. **No default high-value thresholds are shipped.** US-7.1 requires the
   capability; PRD Section 12 leaves the figures open. Too low buries the
   dashboard, too high is a control that never fires, and either way an invented
   figure carries the appearance of a business decision nobody made. The absence
   is reported rather than left silent.
32. **Multi-currency values are not converted before comparison.** Documented
   rather than half-solved: a wrong conversion would be worse than a stated
   limitation.
33. **`anomaly.review` lives in `sec_core`, not the dashboard module.** If it
   sat in the dashboard, an installation without the dashboard could mark alerts
   reviewed silently and untraceably. The log belongs wherever the alerts are.
34. **Bulk review is permitted but constrained.** US-7.1 does not mention it.
   Refusing it outright would push a monitor facing sixty routine alerts into
   ignoring the dashboard; permitting it unmarked would let a serious finding be
   swept up with routine ones. Hence: allowed, marked, and refused for
   high/critical.
35. **The forensic report treats an unconfigured control as a finding.** BRD
   FR-8 lists the contents but not this. A report that says nothing about a
   control that was never enabled reads as assurance, which is the most
   dangerous sentence a compliance document can contain.
36. **The report PDF is rendered once and stored, not on demand.** US-8.1 asks
   only for PDF export. Re-rendering months later runs today's template over
   today's code, so the document could differ from the one signed off with
   nothing to show for it.
37. **Replication ships hashes alongside content.** FR-4.3 says replicate the
   records. Replicating content alone would let an attacker who rewrote history
   replicate the rewritten version unchallenged, so the chain hashes travel too.
38. **Replication is queued, not inline.** Near-real-time in FR-4.3 is honoured
   as a five-minute cron with reported lag, because an audit control able to
   fail a sales order would be switched off within a week.
39. **Reconciliation distinguishes three failure modes, not one.** US-4.2 says
   "alerting on mismatch". Treating lag, alteration and primary-side deletion
   identically would either bury the serious case in routine noise or make
   ordinary shipping lag look like an incident.
40. **An unreadable or never-reconciled target is a finding.** Reporting silence
   as success is the failure mode this whole suite exists to prevent.
41. **Direct SQL INSERT into parent document tables is still permitted.**
   Blocking it would break data import, and Odoo creates documents in draft
   before confirming, so there is no security gain. Child rows under a frozen
   parent are blocked at both layers.
42. **15 roles seeded, not a full 20.** The band permits 10–20; 15 covers the
   personas in PRD Section 4 plus normal operational splits without inventing
   roles the organisation has not asked for. Expect the business to tune this.

## Session History

### Session 24 (05 September 2026) — final build session

**Started:** read continuity files; next task P4-5, last in the list.

Measured what could honestly be measured here and refused to estimate the rest.
The hashing figure is worth keeping: **7.3 µs per Locker entry, 0.01% of the
100 ms budget.** If anyone later proposes weakening the chain for performance,
that number is the answer.

**Found and fixed one real inefficiency:** three configuration SELECTs on every
write to an in-scope model. Invisible on a local database, meaningful across a
network to a separate database host — exactly the shape of "the system got
slower after the security module went in". Cached with `ormcache`, ids and
scalars only, cleared on any configuration change so a stream lock still takes
effect immediately.

**The honest gap:** the Locker serialises every audit append on one chain-head
row. That was the right call in P1-7 — concurrent appends would fork the chain,
and a fork is indistinguishable from tampering — but it means every audited
write in the system queues behind one lock. It cannot be seen single-threaded
and it fails as a cliff, not a slope. Per-model chains are the prepared
mitigation, deliberately **not** built: measure first, because the added
complexity is only worth buying if the numbers demand it.

**The build task list is now complete. The system is not.** Ten items remain
before this is something the CEO/Owner can rely on, and only the first is mine
to do. They are listed at the top of this file under "What remains".

### Session 23 (05 September 2026)

**Started:** read continuity files; next task P4-4.

Ran the review by forming specific attack hypotheses and checking each against
the source, rather than re-reading the modules for correctness. **Three of the
first three hypotheses were real bypasses.** That hit rate is worth recording:
re-reading code you wrote tends to confirm it, while asking "how would I get
round this" does not.

The most instructive finding was **F-1**, because both enforcement layers shared
one blind spot. The trigger was written by mirroring the ORM override, so it
inherited the ORM's assumption that changing a record means UPDATE. Defence in
depth only works when the layers are reasoned about independently; a second
layer derived from the first is one layer with extra steps.

**F-2** is the one to remember for the P4-5 review and for any future change to
the override engine: an attack that *uses* the control rather than evading it.
Three valid signatures attesting to a change nobody approved would have survived
any amount of testing that only asked "does approval work".

Also recorded honestly in the document: I wrote the code I reviewed, three
findings in one pass suggests an independent reviewer would find more, and
budget should exist for one.

**Still not done:** no runtime verification. 474 tests written, 0 executed.

**Next session should:** perform **P4-5**, load and performance testing against
the PRD NFR targets — audit logging under 100ms overhead per save, alerting
within 60 seconds, approval screens under 2 seconds. Note in advance that the
Locker's single chain-head row lock (flagged in P1-7) serialises all audit
appends and is the most likely thing to fail this task; per-model chains are the
prepared mitigation.

### Session 22 (05 September 2026)

**Started:** read continuity files; next task P4-3.

Completed **P4-3**. The pressure on this task was toward an optimistic mapping —
nine modules of real controls make it tempting to write "Implemented" down the
column. Resisted, on the grounds that a certification assessor tests claims and
an inflated mapping costs more credibility than an honest gap costs time.

Three things the document says that the business may not want to hear, and
should:

- **Nothing has been executed.** Every "Implemented" means code exists that is
  intended to do this. That is design intent, not control state.
- **Certification needs operating evidence over a period**, typically 3–12
  months. A system deployed next month has none by definition. The realistic
  near-term position is Type I-shaped.
- **Four of the five questions an assessor asks first are not code problems** —
  P0-1, replication target, incident response, backup. All have been open since
  Phase 0 and are now the critical path.

Also flagged a limit on my own reliability here: the SOC 2 and ISO control
identifiers were written without access to the standard texts. The descriptions
are sound; the numbers need confirming by whoever runs the assessment. Better
said plainly in the document than discovered in a submission.

**Still not done:** no runtime verification. 450 tests written, 0 executed.

**Next session should:** perform **P4-4**, the adversarial review — re-verify
every "no bypass" claim in the suite by trying to break it, rather than by
re-reading the code that makes the claim. Specific targets: superuser and
`sudo()` paths on the freeze engine, the unlock-ticket scope check, the
declaration gate allowlist, the WebAuthn assertion context binding, the
distinct-approver rule, and Locker/report immutability. Expect to find at least
one hole; the sessions so far have averaged roughly one real defect each.

### Session 21 (05 September 2026)

**Started:** read continuity files; next task P4-2.

Completed **P4-2**. The design insight was that "mismatch" is three different
events wearing one word, and conflating them would have wasted the control:

- **missing in replica** — almost always shipping lag. Low severity, or the
  dashboard cries wolf every five minutes.
- **hash differs** — something was altered on one side. Critical.
- **missing in the PRIMARY** — present in the replica, gone from the database.
  This is the one the BRD was written about. It cannot be lag, cannot be a
  network fault, and cannot happen through the application, because Locker
  deletion is refused for every role. Critical, reported separately, and the
  detail text tells the reader to preserve the replica first.

Second decision: **unverifiable is not a pass.** An HTTPS target with no
read-back endpoint gets verdict `unverifiable`, and both that and `never_run`
count against a clean status. Reporting silence as success is precisely the
failure this suite exists to prevent, and it would have been easy to let an
unreadable target quietly return "no mismatches found".

**Still not done:** no runtime verification. 450 tests written, 0 executed.

**Next session should:** build **P4-3** — SOC 2 / ISO 27001 control mapping
against what is actually implemented. This one is a document, not code, and the
temptation will be to map optimistically. It should record the honest state:
several controls are partially met, and P0-1 and P0-5 remain unimplemented
infrastructure work that a certification auditor would ask about first.

### Session 20 (05 September 2026)

**Started:** read continuity files; next task P4-1, first of Phase 4.

Completed **P4-1**. This is the task that changes what the Locker can honestly
claim: the chain makes tampering detectable, replication makes the evidence
survive deletion.

Three decisions worth carrying to the P4-4 review:

- **Hashes ship with the content.** Replicating the records alone would let
  someone who rewrote history replicate the rewrite; the external holder needs
  to be able to verify the chain without trusting the primary.
- **No target configured is a failure state, not a clean one.** `pending: 0` is
  true when nothing was ever set up, and reads as healthy. `replication_status`
  returns `configured: False, healthy: False` with an explicit message.
- **A failed batch stays pending.** The tempting shortcut — mark them shipped
  and move on — would lose those entries permanently and silently.

**Also fixed a test I had just written** that patched `_ship_append_file` at
class level to simulate one failing target among two. Since both instances share
the class, it would have broken the "good" target too and the assertion would
have passed for the wrong reason. Now the failing target is made to fail by
configuration.

**Still not done:** no runtime verification. 427 tests written, 0 executed.

**Open question for the business, now blocking real value from this task:** PRD
Section 12 asks what the external storage target is and who administers it
independently of the application DBA. Until that is answered and configured,
this module reports FR-4.3 as unmet — correctly.

**Next session should:** build **P4-2**, the daily reconciliation job comparing
primary Locker counts and hashes against the external replica. Note the
append-only file target can be read back for comparison; the HTTP target cannot
without a retrieval endpoint, so P4-2 needs to define one or restrict
reconciliation to readable targets and say so.

### Session 19 (05 September 2026)

**Started:** read continuity files; next task P3-5, last of Phase 3.

Completed **P3-5**, which closes a real hole rather than adding polish:
generated reports were fully editable until this session. `PROGRESS.md` had
recorded that at the end of session 18, which is the only reason it was fixed
rather than shipped.

Split the requirement into three properties, because "immutable" alone would
have delivered only the first:

1. refuse edits after generation (including `sudo()`);
2. hash the payload so an alteration below the application layer is
   **detectable** — the same honest downgrade as the Locker, since an
   application refusal binds everyone except the person with a database prompt;
3. pin the PDF to the data by rendering once and storing, so a template change
   cannot retroactively alter what a historical report said.

**Also fixed a defect in session 18's own tests.** One asserted the override
section used a key `entries`; the collector actually returns `rows`. It would
have failed on first execution and looked like a code defect rather than a test
defect. Worth noting as a hazard of writing tests that have never run: they
carry the same assumption errors as the code, without the compiler catching the
mismatch.

**Phase 3 is code-complete. All nine modules exist.** 407 tests written, 0
executed.

**Next session should:** begin Phase 4 with **P4-1**, external audit log
replication (US-4.2). This is the task that converts the Locker's claim from
tamper-evident to genuinely durable against a coerced DBA, and it depends on an
unanswered business question — PRD Section 12 asks what the external target is
and who administers it independently. Build the replication interface with a
pluggable target and at least a filesystem/append-only implementation, and make
the unanswered target an enforced precondition rather than a silent no-op.

### Session 18 (05 September 2026)

**Started:** read continuity files; next task P3-4.

**Found a half-finished `sec_forensic_reporting` on disk.** It was untracked in
git, absent from the previous session's validator run (which reported 8
modules), and its file timestamps sat minutes after session 17's — so it was
work from the tail of that session that was never completed or recorded. Its
`tests/__init__.py` imported a test module that did not exist, and there was no
README; `PROGRESS.md` still said P3-4 not started.

This is precisely the state Section 8.2 warns against, and it is worth recording
why it mattered: had the next session trusted `PROGRESS.md`, it would have
rebuilt the module from scratch and quietly discarded working code — or worse,
half-rebuilt it and left two overlapping implementations.

Action taken: reviewed the existing code rather than overwriting it (manifest,
model surface, XML well-formedness, ACLs, generation and notification logic all
sound), then completed it — wrote the missing 20 tests and the README.

One test was written and then rewritten in the same session: it asserted
malformed-JSON handling by writing to a *generated* report, which P3-5 will make
immutable. Left alone it would have become a knowingly-failing test next
session. It now uses a draft record.

**Still not done:** no runtime verification. 387 tests written, 0 executed.

**Next session should:** build **P3-5** — reports immutable once generated, with
versioning rather than overwrite. Note that `write()`/`unlink()` on
`forensic.report` are currently unguarded; only regeneration over an existing
report is blocked. P3-5 closes that, and should also render the PDF, since
US-8.1 requires PDF export at minimum and `report/` currently holds the QWeb
template and action but nothing pins the rendered output to the payload.

### Session 17 (03 September 2026)

**Started:** read continuity files; next task P3-3.

Completed **P3-3**. The mandatory note existed from Phase 1; the "itself logged"
half did not, and it is the half that matters. Dismissing an alert is a
security-relevant act, and the System Monitor is precisely the person positioned
to make an inconvenient finding disappear. Until this session, doing so left
nothing behind but a status field that could itself be edited.

Worth stating for the P4-4 review: this is not a distrust of the monitor. A
monitoring function nobody audits is the same single-point-of-trust problem the
BRD set out to remove, moved one step sideways.

Two design decisions:

- **The review model went in `sec_core`, not the dashboard.** In the dashboard
  it would have been bypassable by simply not installing the dashboard.
- **Bulk review is allowed but deliberately awkward.** Refusing it outright
  pushes a monitor facing sixty routine out-of-hours alerts into ignoring the
  dashboard; allowing it unmarked lets a serious finding be swept up with
  routine ones. So: each row marked `bulk`, and high/critical refused in a
  batch.

**Still not done:** no runtime verification. 367 tests written, 0 executed.

**Next session should:** build **P3-4**, `sec_forensic_reporting` (US-8.1). Most
inputs already exist as report methods written along the way, and they should be
consumed rather than reimplemented: `plaza.sod.scan.latest_scan_summary`,
`role.plaza_model.check_catalog_readiness`, `override.request.
approvals_without_strong_auth` and `independence_report`, `sec.webauthn.
credential.clone_detection_report`, `res.users.webauthn_enrolment_report`,
`sec.value.threshold.coverage_report`, `anomaly.alert.review_activity_report`,
`audit.locker.entry.verify_chain`, `sec.freeze.rule.verify_triggers`.

### Session 16 (03 September 2026)

**Started:** read continuity files; next task P3-2.

Completed **P3-2**. The judgement call was whether to ship default thresholds.
Decided not to: PRD Section 12 explicitly lists the figures and their owner as
unresolved, and a number invented here would be indistinguishable, six months
later, from one the business had chosen. What is shipped instead is the
mechanism plus loud reporting of the gap, because an empty "high value" section
on the dashboard otherwise reads identically whether nothing crossed a threshold
or no threshold exists.

Two smaller decisions worth recording:

- **Delta is the default comparison mode**, not absolute. A large correction to
  an existing figure is usually the more interesting event: 1,000,000 to
  1,001,000 is a trivial delta on a big number, while 1,000 to 100,000 is a
  small number that grew alarmingly. Absolute-only would flag the first and miss
  the second.
- **Thresholds on non-numeric fields are rejected at configuration time.** The
  failure mode otherwise is a rule that looks configured and silently never
  fires, which is the worst possible shape for a control.

**Still not done:** no runtime verification. 342 tests written, 0 executed.

**Next session should:** build **P3-3** — the mark-reviewed workflow with a
mandatory note, itself logged. `anomaly.alert.action_mark_reviewed` already
requires a note (from `sec_core`); P3-3 adds the "itself logged" half, which is
not yet done: reviewing an alert currently leaves no audit trail of who
dismissed what and why.

### Session 15 (03 September 2026)

**Started:** read continuity files; next task P3-1, first of Phase 3.

Completed **P3-1**. Less new machinery than expected, because `anomaly.alert`
has been collecting events since P1-3 — missing documentation, frozen-write
attempts, enforcement being switched off, stream lock toggles, credential and
clone events, recovery, override requests, collusion attempts and executions.
The genuinely new piece was out-of-hours detection.

The interesting problems were both about whether anyone will actually use the
result rather than about correctness:

- **Timezone.** Locker timestamps are UTC. Comparing a UTC hour against
  09:00-18:00 would have flagged an entire Bangladeshi working day, and the
  dashboard would have been dismissed as noisy within a week. There is a test
  asserting that 06:00 UTC is in-hours in `Asia/Dhaka` and out-of-hours in UTC.
- **Severity inflation.** Out-of-hours is raised at `low`. If working late
  produced the same colour as an attempted edit to a frozen record, the reader
  learns to ignore the colour.

Also worth flagging for go-live: `working_days` ships Monday-Friday. An
organisation on a Sunday-Thursday week that leaves it alone gets two normal
working days flagged and two weekend days cleared. There is a configuration
checker in the menu that reports the effective settings.

**Still not done:** no runtime verification. 318 tests written, 0 executed.

**Next session should:** build **P3-2** — configurable high-value field
thresholds (PRD Section 12 lists the actual figures as an open question for the
owner, so build the mechanism and ship no opinionated defaults). The natural
hook is the same `audit.locker.entry.append` path used for out-of-hours, reading
the field diff already stored on the entry.

### Session 14 (03 September 2026)

**Started:** read continuity files; next task P2-8, last of Phase 2.

Completed **P2-8**, which closes the loop and makes Phases 1 and 2
code-complete.

Design points worth carrying into Phase 3 and the P4-4 security review:

- **Two enforcement layers, two separate mechanisms.** The ORM check reads the
  unlock ticket; the PL/pgSQL trigger from P1-5 knows nothing about tickets and
  needs `SET LOCAL sec.freeze_unlock`. Anyone changing execution must remember
  both. This is written into the module README because a half-failure here is
  exactly the sort of thing someone "fixes" by turning a control off.
- **`_freeze_unlock_authorised` was a deliberate stub returning False since
  P1-4.** It is now implemented, and the context key only *selects* which
  ticket to check — the ticket must exist, be unspent, unexpired, name that
  record, and cover every protected field being written. A fabricated ticket id
  authorises nothing, and there is a test for that.
- **Re-freezing is ticket consumption, not a state transition.** There is no
  moment when the record is generally unlocked, so there is nothing to forget
  to re-lock if execution fails midway.

**Still not done:** no runtime verification. 294 tests written, 0 executed. This
gap now matters more than at any previous point: Phase 2 code decides whether a
confirmed financial record can be altered.

**Next session should:** begin Phase 3 with **P3-1**,
`sec_surveillance_dashboard` (US-7.1). Most of the data already exists —
`anomaly.alert` from `sec_core` has been collecting out-of-hours, missing-doc,
frozen-write, credential and override events throughout. P3-1 is largely a
live feed and triage UI over it, plus the out-of-hours detection rule, which
nothing currently raises.

### Session 13 (03 September 2026)

**Started:** read continuity files; next task P2-7.

Completed **P2-7**, which closes the gap confirmed in session 11 by reading the
upstream source: `base_tier_validation` will let one person in two reviewer
groups satisfy two tiers.

The design question was where to draw the line between blocking and flagging.
Blocking on same-source-IP would fire constantly in a single-office company, and
a control that fires on everyday behaviour is a control somebody disables. So:
block what is provably one identity (requester, same account, same
`res.partner`), flag what is merely suspicious.

**Bug fixed from P2-6.** `_record_approval` ran *before* `super().validate_tier()`.
Since `override.approval` is append-only, a failure inside `super()` would have
left a permanent, undeletable record claiming a tier was approved when it was
not — false evidence in the exact table an auditor would rely on. Reordered so
the evidence is written only after upstream validation succeeds.

**Wording that needs to reach the CEO/Owner:** FR-5.2 asks to "prevent
collusion". Software can enforce that three distinct identities sign on distinct
hardware in sequence. It cannot detect three real people agreeing beforehand in
a corridor. The README says so; the claim made to the business should match.

**Still not done:** no runtime verification. 275 tests written, 0 executed.

**Next session should:** build **P2-8** — call `_assert_executable()`, apply the
proposed change to the frozen record under a validated unlock, re-freeze
immediately, write the Locker entry for the whole chain, and mark the request
executed. Note that `sec.record.freeze.mixin._freeze_unlock_authorised()` still
returns False by design and must now be implemented against a real unlock
ticket; the SQL trigger also needs `SET LOCAL sec.freeze_unlock = 'granted'` for
the duration of that one transaction.

### Session 12 (03 September 2026)

**Started:** read continuity files; next task P2-6.

Completed **P2-6**. The design constraint that shaped it was not cryptographic
but architectural: `_verify_pending_assertion` reads a marker on the HTTP
request object, so a verify call followed by a separate approve call loses it.

The tempting fix is to move the marker to the session — and that is precisely
the thing not to do, because one confirmation would then authorise every
subsequent approval in the same browser session, which is the session-fixation
shape of the very problem WebAuthn is here to solve. The controller verifies and
records in a single call and clears the marker in a `finally` block.

Second decision worth recording: when WebAuthn verification is unavailable, the
approval is **refused**, not recorded with `strongly_authenticated = False`. The
P1-6 stream-lock toggle takes the opposite approach and records the weakness,
which is right there because the alternative was an unusable control. Here it is
wrong, because an approval recorded as unconfirmed still completes the override.
Same pattern, opposite answer, for a reason.

**Still not done:** no runtime verification. 259 tests written, 0 executed.

**Next session should:** build **P2-7** — collusion and duplicate-identity
prevention (US-5.3, FR-5.1/FR-5.2). Enforce that no user satisfies two tiers on
one request, that the requester cannot approve any tier, and that the unlock
action is technically incapable of running on fewer than three validated
approvals. Any attempt raises a high-priority anomaly.

### Session 11 (03 September 2026)

**Started:** read continuity files; next task P2-5.

Re-read `base_tier_validation`'s source before integrating, and it confirmed the
P0-4 suspicion: `validate_tier` filters reviews by the sequences the acting user
may approve, with no check that tiers are satisfied by *different people*. A
user in two reviewer groups can approve twice. FR-5.1 forbids that and nothing
upstream prevents it, so P2-7 is not optional polish — it is the requirement.

Completed **P2-5**.

**Two defects caught in my own code before they shipped:**

- I used the `states={...}` field attribute, removed in Odoo 17. It loads
  without error but the conditional readonly silently does nothing — on a
  security model, that means a field the user was supposed to be unable to edit
  after submission. The validator now detects `states=` in python files, proven
  with a canary module.
- A duplicated freeze-rule lookup in `_target_is_frozen` with a nonsense first
  domain. Harmless but wrong; removed.

**Still not done:** no runtime verification. 241 tests written, 0 executed.

**Next session should:** build **P2-6** — three-tier sequential approval with
WebAuthn gating. Override `validate_tier` to require a verified assertion bound
to `override.request,<id>` before any tier is recorded, using
`_verify_pending_assertion(context_ref)` from P2-2. Password-only approval must
be rejected outright (FR-5.3).

### Session 10 (03 September 2026)

**Started:** read continuity files; next task P2-4.

Completed **P2-4**. The substantive design question was not the approval
mechanics but *when* an enrolment needs approval at all. Requiring multi-party
approval for every enrolment would make onboarding and the FR-6.5 second-device
requirement painful enough that people work around them; requiring it for none
leaves the account takeover path wide open. Hence the three routes.

Two things surfaced worth recording beyond the code:

- **Tying recovery approval to "the other two tiers" literally is
  unsatisfiable** in the commonest real scenario. The CEO/Owner losing a phone
  is precisely when Tier 3 cannot approve, because Tier 3 is the person locked
  out. Implemented as any two eligible approvers instead; flagged for the
  product owner.
- **An approver with no working authenticator cannot give a confirmed
  approval**, so they are not eligible. That means a deployment where only one
  approver has enrolled has an unsatisfiable recovery path. The request raises
  a critical alert in that case rather than failing quietly — better to discover
  it during setup than during an incident.

**Still not done:** no runtime verification. 221 tests written, 0 executed.

**Next session should:** build **P2-5**, `sec_override_engine` on OCA
`base_tier_validation` 18.0.3.4.1 — the override request form with reason
category and justification (US-5.1). Carry in from P0-4: set
`approve_sequence` True and `approve_sequence_bypass` False on every tier
definition, or approvals become parallel and US-5.2's sequential requirement is
silently lost. Reuse `sec.instruction.mixin` from P1-2 rather than
reimplementing Written/Oral.

### Session 9 (03 September 2026)

**Started:** read continuity files; next task P2-3.

Read py_webauthn's sign-count branch before designing the response, and the
ordering turned out to decide the whole design: the counter check runs *before*
signature verification. That means the regression path is reachable by anyone
who knows a credential ID, without possessing the key. Revoking on regression
alone would have shipped a remote denial-of-service against the Nuclear Key
holder's authenticator, dressed as a security feature.

Completed **P2-3** with the two-stage classification described in the checklist
above.

Also worth recording: the passkey case. Constant-zero counters mean clone
detection simply does not apply to most phone credentials. There is no clever
way around that — it is a property of the authenticator, not of our code — so it
is surfaced in `clone_detection_report()` for the monthly report rather than
quietly ignored.

**Still not done:** no runtime verification. 202 tests written, 0 executed.

**Next session should:** build **P2-4**, break-glass re-enrolment (US-6.3). The
master build prompt flags a circular dependency with P2-5 (the override engine
that would normally carry the approvals). Plan: implement a self-contained
two-approver interim rule inside `sec_webauthn_auth`, with the approvers
required to be distinct from the requester and from each other, and log it for
revisit once P2-5 exists.

### Session 8 (03 September 2026)

**Started:** read continuity files; next task P2-2.

Installed `py_webauthn` 3.0.0 and introspected its real signatures and result
dataclasses before writing anything. Worth the two minutes: the 3.x API is
keyword-only and the verified-result field names (`credential_public_key`,
`sign_count`, `credential_backed_up`) are not what one would guess.

Completed **P2-2**. Points worth carrying:

- Challenges are looked up **by the value carried in clientDataJSON**, not by
  "this user's most recent challenge". With two browser tabs open the most
  recent is not necessarily the one being answered, and picking wrong would
  either fail valid ceremonies or consume a challenge still outstanding
  elsewhere.
- `verify_authentication` raises on every failure path and never returns a
  falsy value for the caller to interpret. That shape is what caused the P1-6
  defect found in session 7.
- The sign counter is writable only under an explicit context. Otherwise
  someone who cloned a key could raise the stored counter and erase the
  evidence of the regression before P2-3 notices it.

**Two P2-1 tests were updated, not deleted.** They asserted
`_verification_ready()` is False and that the stream lock falls back to policy —
both correct then, both wrong now. Rewritten to assert the property that has
not changed: the system never claims verification it cannot perform.

**Manual verification still owed:** no automated test can prove a real
attestation verifies, because producing one means reimplementing an
authenticator, and mocking the library into returning success proves only that
the mock works. End-to-end enrolment with a real device on real HTTPS is a
manual test and is listed as such here, not counted as automated coverage.

**Still not done:** no runtime verification of anything. 188 tests written,
0 executed.

**Next session should:** build **P2-3** — sign-counter regression detection.
Note the design question to settle: on a regression, refuse the one assertion,
or revoke the credential outright? A regression means the key has plausibly been
cloned, so every future assertion from it is suspect, which argues for
revocation plus a critical alert.

### Session 7 (03 September 2026)

**Started:** read continuity files; next task P2-1. The two open items against
it (RP domain, HTTPS) are user decisions, so rather than stall, they were built
as enforced preconditions — enrolment refuses with a specific error naming what
is missing.

Completed **P2-1**. Also confirmed `py_webauthn` 3.0.0 downloads from PyPI, so
P2-2 has no library blocker.

**Defect found and fixed in P1-6 while building this.** `_confirm_strong_auth`
called `_verify_pending_assertion()` and, on a False return, proceeded with the
toggle recorded as weakly authenticated. That is correct while verification does
not exist, but once P2-2 lands it would mean **a failed or absent assertion
silently downgrades to an unverified toggle on the strongest control in the
system**. Now gated on `_verification_ready()`: if verification exists and the
assertion fails, the toggle is refused; if it does not exist yet, the policy
parameter decides. Covered by
`test_stream_lock_falls_back_to_policy_while_unverified`.

This is worth noting as a pattern: capability stubs that return a falsy value
are safe only while the caller knows the capability is absent. The distinction
between "denied" and "not implemented" has to be explicit at the seam.

**Still not done:** no runtime verification. 168 tests written, 0 executed.

**Next session should:** build **P2-2** — registration and authentication
ceremony verification with `py_webauthn` 3.0.0. Decode clientDataJSON, match the
stored challenge, check type/origin/rpIdHash, verify the attestation, extract
the COSE key and sign counter. Then set `_verification_ready()` to True and flip
`sec_record_freeze.allow_toggle_without_webauthn` to False.

### Session 6 (03 September 2026)

**Started:** read continuity files; next task P1-7, last of Phase 1.

Re-read the OCA `auditlog` source before writing anything rather than working
from the P0-4 notes. That paid for itself: **OCA auditlog records no client IP
at all** — `auditlog.http.request` holds path, root URL, user and context and
nothing else. FR-4.1 requires source IP, so the Locker captures it directly.
Had this been assumed rather than checked, the gap would have surfaced at audit.

Completed **P1-7**. Design points worth carrying forward:

- Built *on* auditlog rather than replacing it: field diffing is fiddly,
  well-tested upstream, and not where our risk lies. Our layer adds IP,
  immutability and the chain.
- A singleton chain-head row is locked `FOR UPDATE` during append. Without it,
  concurrent writes chain onto the same predecessor and the fork is
  indistinguishable from tampering during verification. The cost is that
  Locker appends serialise — first thing to measure in P4-5.
- `external_replica_ref` and `replicated_at` are deliberately outside the
  hashed payload: they are learned after the entry is written, and hashing
  them would make the hash unstable by design.

**Phase 1 is code-complete.** 143 tests written across five modules, 0 executed.

**Next session should:** begin Phase 2 with **P2-1**, `sec_webauthn_auth`
credential enrolment (US-6.1). Two prerequisites are the user's, not the build's,
and both have lead time: the canonical Relying Party domain must be fixed
permanently before any enrolment, and WebAuthn requires HTTPS with a certificate
the client browsers trust — it will not run over http on an IP address.

### Session 5 (03 September 2026)

**Started:** read continuity files; next task P1-6.

Completed **P1-6**. Notable points:

- The stream lock is enforced in `create` as well as `write`/`unlink`, because a
  lockdown that still permits new records is not a lockdown.
- Stream lookup deliberately ignores `enforcement_active`: switching the
  confirm-state freeze off must not also disable the lockdown, they are separate
  controls.
- Caught during the build: the `write()` guard that forbids setting `locked`
  directly would also have blocked the action methods' own write. Routed those
  through an explicit internal context.

**Still not done:** no runtime verification. 118 tests written, 0 executed.

**Stopped at:** natural boundary, P1-6 complete. Phase 1 has one task left.

**Next session should:** build **P1-7** — `sec_audit_locker` on OCA `auditlog`
18.0.2.0.9, capturing user, UTC timestamp, source IP, model, record id and
field-level before/after for all in-scope actions (US-4.1). Two things to carry
in: BRD Section 9 risk 6 and PRD risk 5 both warn that logging every field at
production volume degrades write latency, so scope selectively from the start;
and US-3.2 requires stream lock toggles to reach the Locker, so wire
`sec.stream.lock` into the captured models.

### Session 4 (03 September 2026)

**Started:** read continuity files; next task P1-5.

Completed **P1-5**. Notable points:

- The trigger takes its frozen states, protected columns and parent-table join
  as trigger arguments, so one shared guard function serves all six tables.
- Protected fields are filtered to real stored columns at install time. The
  rule lists include one2many fields (`order_line`, `line_ids`) which are not
  columns; guarding them at SQL level is impossible and pretending otherwise
  would leave a control that looks configured and enforces nothing.
- Structural check run on the rendered PL/pgSQL (dollar-quoting balanced, no
  unsubstituted placeholders, all four trigger args consumed, every branch
  returns a row). This is not a substitute for executing it.

**Still not done:** no runtime verification. 100 tests written, 0 executed. The
P1-5 tests are the ones most likely to surface real defects, because they are
the first that cannot be reasoned about purely from Python — PL/pgSQL either
compiles against the live schema or it does not.

**Stopped at:** natural boundary, P1-5 complete.

**Next session should:** build **P1-6** — independent Sales and Purchase lock
toggles for the Super Admin, gated on `group_security_super_admin`, each toggle
change written to the audit trail with actor, timestamp and before/after state.
Note that WebAuthn confirmation on the toggle (US-3.2) cannot be wired until
P2-2 exists; build the hook and leave it unsatisfied, flagged.

### Session 3 (03 September 2026)

**Started:** read continuity files; Phase 1 at P1-3, next P1-4.

Completed:

- **P1-4** — new module `sec_record_freeze`: 3 model files, config views, six
  default freeze rules, README, 20 tests.
- Validator hardened twice. First, it was producing false positives on model
  extensions (`sale.order` etc.), so `declared_models` now distinguishes models
  a module *originates* from ones it extends. Then a deliberate canary module
  showed the loosened check had a real gap — a module shipping **no** ACL file
  at all skipped the check entirely. Both now caught; canary retained as the
  method for verifying the validator itself still bites.

**Still not done:** no runtime verification. 85 tests now written, 0 executed.
Open Question 1 remains the top blocker and is now materially more important:
P1-4 overrides `write()` on `sale.order`, `purchase.order` and `account.move`,
so a defect here disrupts order-to-cash, not just a settings screen.

**Stopped at:** natural boundary, P1-4 complete.

**Next session should:** build **P1-5** — PostgreSQL-level constraints. Mirror
the protected-column lists from `sec.freeze.rule`; a row-level block would break
Odoo for the reasons documented under deviation 9.

### Session 2 (03 September 2026)

**Started:** read `PROGRESS.md` and `BUILD_STATE.json`; Phase 0 complete, Phase 1
untouched. Followed the master build prompt's task order, which begins Phase 1 at
P1-1 (a previous session summary had loosely suggested P1-4 first; corrected).

Completed:

- New module **`sec_core`**: `anomaly.alert` + `sec.anomaly.mixin`, 5 tests.
- New module **`sec_declaration_gateway`**: **P1-1**, **P1-2**, **P1-3** —
  4 model files, 1 controller, 3 view/template files, ACLs, unpublished
  placeholder declaration, 29 tests.
- Validator extended to skip abstract models when checking ACL coverage
  (it was producing false positives on mixins). All 3 modules validate clean.

**Not done:** still no runtime verification. Open Question 1 remains the top
blocker; the user has an existing on-prem V18 instance and install/test output
has not yet come back.

**Stopped at:** natural boundary. P1-1/P1-2/P1-3 complete, P1-4 not begun.

**Next session should:** build **P1-4** — `sec_record_freeze`, ORM
`write()`/`unlink()` overrides on `sale.order`, `purchase.order`, `account.move`
for confirmed/done/posted states (US-3.1). Then P1-5 (PostgreSQL-level
constraints) and P1-6 (lock toggles).

### Session 1 (03 September 2026)

**Started:** repository did not exist; no `PROGRESS.md` or `BUILD_STATE.json`.

Completed:

- Repository scaffold, git init, `.gitignore`, root `README.md`.
- `tools/validate_addons.py` — static validator that runs without Odoo: python
  syntax, XML well-formedness, manifest/data-file consistency, ACL model
  coverage, and detection of Odoo-17-and-earlier view syntax (`<tree>`,
  `attrs=`, `states=`) that V18 rejects. Currently clean.
- **P0-4** fully verified against upstream OCA `18.0` branches; API surface for
  `base_tier_validation` captured for Phase 2.
- **P0-2** and **P0-3** code-complete: the whole of `sec_plaza_rbac` — 3 model
  files, 4 view files, security groups, ACL CSV, 15-role seed catalog, README,
  and 3 test modules (31 tests written).
- **P0-1** and **P0-5** specified as infrastructure documents with explicit
  "evidence required to close" sections, since neither can be closed by module
  code.

Discovered and recorded: no Odoo/PostgreSQL in the build environment, so nothing
here has been runtime-tested. This is documented prominently rather than papered
over.

**Stopped at:** natural boundary — Phase 0 module work complete, Phase 1 not
begun. Nothing is half-written.

**Next session should:** (1) resolve Open Question 1 (where tests run) if
possible; (2) run the `sec_plaza_rbac` suite and promote P0-2/P0-3 to `done` or
fix what it finds; (3) begin **P1-4**, the `sec_record_freeze` ORM
`write()`/`unlink()` overrides, which has no unmet dependencies.
