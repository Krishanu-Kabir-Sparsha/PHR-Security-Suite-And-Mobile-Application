# P4-3 — SOC 2 and ISO/IEC 27001 Control Mapping

**Status of this document:** engineering assessment, not an audit opinion.
**Date:** 05 September 2026 (session 22)
**Scope:** the nine `sec_*` modules in this repository, as code. Not the
deployed environment, which does not yet exist.

---

## 0. Read this before the table

Three caveats, all of which materially change what the mapping below is worth.

**Nothing here has been executed.** 450 automated tests exist across the suite
and **none has ever run**. Every "Implemented" below means *code exists that is
intended to do this*. An auditor does not accept that, and neither should the
business. Until the suite runs green against a real Odoo 18 database, the
correct reading of this document is "design intent", not "control state".

**Certification needs operating evidence, not just controls.** SOC 2 Type II and
ISO 27001 both assess whether controls *operated effectively over a period* —
typically 3–12 months. A system deployed next month has, by definition, no such
evidence. The most that can be claimed at go-live is Type I-shaped: the controls
are designed and in place at a point in time. Plan the audit window accordingly
rather than discovering this during scoping.

**Control numbering should be verified against the standard text.** I do not
have access to the SOC 2 Trust Services Criteria or ISO/IEC 27001:2022 Annex A
while writing this, so the identifiers below are from memory and may be
imprecise or renumbered. **Treat the descriptions as authoritative and the
numbers as a starting point for your assessor to confirm.** Getting a control
reference wrong in a submitted document is an avoidable credibility cost.

---

## 1. Overall readiness

| Question | Answer |
|---|---|
| Are the controls designed? | Largely yes, for the in-scope risk. |
| Are they implemented? | In code. Not deployed, not executed, not verified. |
| Are they operating? | No. No production deployment exists. |
| Could an audit start today? | No. See blockers below. |

### Blockers to any credible assessment

1. **No test has been executed** (all phases). The single highest-value action
   outstanding.
2. **P0-1 — direct production database access not removed.** This is the one an
   assessor will find first, and it undermines several controls below
   simultaneously. BRD Section 9 already calls it the highest-leverage fix.
3. **P0-5 — no tested backup and disaster recovery.** ISO A.8.13 fails outright;
   SOC 2 availability criteria cannot be evidenced.
4. **FR-4.3 unmet in practice.** External replication is implemented but no
   target is configured and no independent custodian is named, so the audit
   trail currently lives only where the application DBA controls it.
5. **No incident response runbook** (BRD Section 9, risk 7). Detection without a
   documented response is a partial control everywhere it appears.
6. **Declaration text not supplied by Legal**, so the gateway is dormant.
7. **No high-value thresholds configured**, so that detection is inactive.

---

## 2. SOC 2 — Trust Services Criteria

Status key: **I** implemented in code (untested) · **P** partial · **N** not met
· **O** outside this suite's scope.

### CC1 — Control environment

| Ref | Criterion (paraphrased) | Status | Where / gap |
|---|---|---|---|
| CC1.1 | Commitment to integrity and ethical values | P | The Unified Declaration gateway (`sec_declaration_gateway`) captures acknowledgment per user, versioned and hashed. **Dormant until Legal supplies text.** |
| CC1.3 | Structures, reporting lines, authorities | I | Plaza Model catalog: 15 roles, each with an explicit access matrix and a named approval tier. |
| CC1.4 | Competence | O | Training and hiring. Not a software control. |
| CC1.5 | Accountability | I | Every privileged act is attributed: overrides, approvals, lock toggles, triage decisions, report generation. |

### CC2 — Communication and information

| Ref | Criterion | Status | Where / gap |
|---|---|---|---|
| CC2.1 | Quality information for internal control | I | Monthly forensic report; findings lead, and an unconfigured control counts as a finding. |
| CC2.2 | Internal communication of responsibilities | P | Role descriptions are mandatory in the catalog; the declaration carries the rest but is dormant. |
| CC2.3 | External communication | O | Not addressed by this suite. |

### CC3 / CC4 — Risk assessment and monitoring

| Ref | Criterion | Status | Where / gap |
|---|---|---|---|
| CC3.2 | Risk identification and analysis | P | The BRD risk register exists and is being tracked in `PROGRESS.md`. Not a recurring organisational process yet. |
| CC4.1 | Ongoing evaluations | I | Daily Locker chain verification, daily replica reconciliation, hourly replication backlog check, monthly report. |
| CC4.2 | Deficiencies communicated | I | Critical anomalies raise alerts; the monthly report is delivered to Super Administrators with the finding count in the subject. |

### CC5 — Control activities

| Ref | Criterion | Status | Where / gap |
|---|---|---|---|
| CC5.1 | Controls to mitigate risk | I | Record freeze, three-tier override, WebAuthn, hash-chained log. |
| CC5.2 | Technology general controls | P | Application controls are strong; **the deployment pipeline is not** (P0-1). |
| CC5.3 | Policies and procedures deployed | P | Enforced in code; the corresponding written policies are the organisation's to produce. |

### CC6 — Logical and physical access ← *the core of this suite*

| Ref | Criterion | Status | Where / gap |
|---|---|---|---|
| CC6.1 | Logical access security | I | Plaza RBAC; grants outside the catalog are refused without an approved, justified exception. |
| CC6.2 | Registration and authorisation of users | I | Non-standard grant guard; enrolment routing in `sec_webauthn_auth`. |
| CC6.3 | Access modified/removed on change | P | Grant exceptions carry expiry; **no automated joiner-mover-leaver process** — a departing user's access is still a manual action. |
| CC6.6 | Boundary protection | O | Reverse proxy / WAF layer. BRD Section 8.4 correctly puts IP geofencing here, not in Odoo. |
| CC6.7 | Restriction of information movement | P | Field-level restrictions are declared in the access matrix; export controls are not addressed. |
| CC6.8 | Prevention of unauthorised software | O | Infrastructure. |

### CC7 — System operations

| Ref | Criterion | Status | Where / gap |
|---|---|---|---|
| CC7.1 | Detection of configuration changes | I | Changes to freeze rules, role catalog, stream locks and declaration versions are all audited; disabling freeze enforcement raises a **critical** alert. |
| CC7.2 | Monitoring for anomalies | I | `sec_surveillance_dashboard`: out-of-hours edits, missing documentation, high-value changes (**inactive until thresholds are set**), frozen-write attempts, incomplete overrides, credential anomalies. |
| CC7.3 | Evaluation of security events | I | Triage is mandatory-note and append-only logged; bulk dismissal is marked and refused for high/critical. |
| CC7.4 | Incident response | **N** | Detection exists; **no documented response process**. BRD risk 7. |
| CC7.5 | Recovery from incidents | **N** | P0-5 outstanding. |

### CC8 — Change management

| Ref | Criterion | Status | Where / gap |
|---|---|---|---|
| CC8.1 | Authorised changes only | P | Changes to *business records* are tightly controlled. Changes to *the system* depend on P0-1, which is not done. |

### CC9 — Risk mitigation

| Ref | Criterion | Status | Where / gap |
|---|---|---|---|
| CC9.1 | Business disruption mitigation | **N** | P0-5. |
| CC9.2 | Vendor and partner risk | O | Includes the custodian of the external replica once appointed. |

### Processing integrity (if in scope)

| Ref | Criterion | Status | Where / gap |
|---|---|---|---|
| PI1.4 | Processing is complete, accurate, timely, authorised | I | Freeze plus three-tier override means a confirmed record changes only through an authorised, evidenced path. |
| PI1.5 | Stored outputs are complete and accurate | P | Hash-chained Locker and immutable reports; **the replica making that durable is not configured**. |

---

## 3. ISO/IEC 27001:2022 — Annex A

| Ref | Control | Status | Where / gap |
|---|---|---|---|
| A.5.3 | Segregation of duties | I | Intra-role conflicts impossible to author; cross-role conflicts detected by `plaza.sod.scan`, with accepted risk requiring a named approver and note. |
| A.5.15 | Access control | I | Plaza Model catalog and access matrix. |
| A.5.16 | Identity management | I | One identity per user; paired accounts sharing a `res.partner` are blocked from double-approving. |
| A.5.17 | Authentication information | I | WebAuthn: only public keys stored, private keys and biometrics never leave the device. |
| A.5.18 | Access rights | P | Provisioning and exception handling are strong; periodic access review is a monthly report input, not an enforced cycle. |
| A.5.24–5.26 | Incident management planning and response | **N** | See CC7.4. |
| A.5.28 | Collection of evidence | I | Hash-chained Locker, append-only approvals, immutable versioned reports. Strongest area of the suite. |
| A.5.33 | Protection of records | P | Application-layer immutability plus tamper evidence. **Durability depends on the unconfigured replica.** |
| A.5.34 | Privacy and PII protection | P | WebAuthn keeps biometrics off the server entirely (BRD Section 10). Broader PII handling is out of scope here. |
| A.8.2 | Privileged access rights | I | Super Administrator is a named group; its privileged acts (lock toggles, freeze rule changes) are audited and alerted. |
| A.8.3 | Information access restriction | I | ACLs plus declared field-level restrictions. |
| A.8.5 | Secure authentication | I | FIDO2/WebAuthn with user verification required, single-use time-limited challenges, and assertions bound to one action. |
| A.8.8 | Management of technical vulnerabilities | O | Patching process; not addressed here. |
| A.8.12 | Data leakage prevention | **N** | Not addressed. |
| A.8.13 | Information backup | **N** | P0-5. Note the tension documented there: a restore rewinds the Locker, so the replica must sit outside the restore blast radius and post-restore reconciliation is mandatory. |
| A.8.15 | Logging | I | Every in-scope create/write/unlink with actor, UTC timestamp, source IP, and field-level before/after. Source IP is captured by this suite because OCA `auditlog` records none. |
| A.8.16 | Monitoring activities | I | Surveillance dashboard and alerting. |
| A.8.17 | Clock synchronisation | P | Timestamps are UTC throughout; **NTP synchronisation is asserted in the deployment checklist and not enforceable from the application.** An assessor will ask for host evidence. |
| A.8.31 | Separation of environments | **N** | Tied to P0-1. |
| A.8.32 | Change management | P | See CC8.1. |
| A.8.34 | Protection during audit testing | O | Procedural. |

---

## 4. The five things an assessor will ask first

Ordered by how quickly they will surface, not by severity.

1. **"Show me the test results."** There are none. Everything above is design
   intent until the suites run.
2. **"Who can access the production database directly?"** Currently developers
   can. This single answer weakens CC5.2, CC6.1, CC8.1, A.8.31 and the
   credibility of the freeze engine at once.
3. **"Where is the independent copy of the audit log?"** Not configured. The
   code is ready; the target and its custodian are a business decision.
4. **"What happens when an alert fires at 02:00?"** No documented incident
   response. Detection without response is half a control.
5. **"When did you last restore from backup?"** Never, because there is no
   tested backup process.

None of these are code problems. Four of the five are organisational decisions
that have been outstanding since Phase 0.

---

## 5. What this suite genuinely does well

Stated plainly, because an honest mapping should not read as only a list of
gaps:

- **Evidence quality (A.5.28, CC1.5).** A hash-chained log, append-only approval
  records with cryptographic authentication evidence, immutable versioned
  reports, and an append-only trail of the monitoring function's own decisions.
  Few systems of this size audit their own auditors.
- **Authorisation strength (A.8.5, CC6.1).** Three distinct identities, each on
  their own hardware, in sequence, with the assertion bound to one specific
  action. That is materially stronger than most enterprise change controls.
- **Honest failure reporting.** Throughout, an unconfigured or unverifiable
  control reports as a finding rather than as a pass. That property is worth
  more at audit than any single control, because it means the system's own
  account of itself can be trusted.

---

## 6. Recommended sequence to certification readiness

1. Run the test suites. Fix what they find. *(Nothing else is worth doing first.)*
2. Close P0-1 — remove standing production database access.
3. Configure the replication target and name its independent custodian.
4. Implement and test backup/DR (P0-5), including post-restore reconciliation.
5. Write the incident response runbook.
6. Obtain the declaration text from Legal and publish it.
7. Set high-value thresholds and their tuning owners.
8. Run for a full audit period, then seek assessment against operating
   effectiveness.

Steps 2, 4 and 5 are infrastructure and process, not module work. They have been
on the list since Phase 0 and are now the critical path.
