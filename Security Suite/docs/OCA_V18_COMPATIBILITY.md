# P0-4 — OCA Module Compatibility with Odoo V18

**Verified:** 03 September 2026, session 1
**Method:** direct inspection of the OCA upstream `18.0` branches over git.
Repositories were cloned with `--depth 1 --filter=blob:none --sparse` and the
manifests read from the checked-out tree. This is evidence of *upstream port
existence and declared version*, not evidence of runtime behaviour on our data.

## Findings

| Module | Repository | Branch | Manifest version | Verdict |
|---|---|---|---|---|
| `auditlog` | `OCA/server-tools` | `18.0` | `18.0.2.0.9` | Ported and released for V18 |
| `base_tier_validation` | `OCA/server-ux` | `18.0` | `18.0.3.4.1` | Ported and released for V18, `development_status: Mature` |

Neither module requires a local patch to *exist* on V18. Both declare
`installable: True` on the 18.0 branch.

Also present on `OCA/server-ux@18.0` and potentially useful later:
`base_tier_validation_confirm_auth` (re-authentication before validating a
tier), `base_tier_validation_forward`, `base_tier_validation_formula`.
`base_tier_validation_confirm_auth` is worth evaluating in Phase 2 as a
starting point for the WebAuthn gate on approvals (P2-6) — it already has the
hook shape we need, though it authenticates with a password, which BRD FR-5.3
explicitly forbids as a sole factor.

## API surface captured for Phase 2

`base_tier_validation` provides an abstract mixin `tier.validation` that a model
inherits, plus `tier.definition` (configuration) and `tier.review` (one row per
tier per record).

Mixin configuration attributes:
`_state_field` (default `state`), `_state_from` (default `["draft"]`),
`_state_to` (default `["confirmed"]`), `_cancel_state` (default `cancel`),
`_tier_validation_state_field_is_computed`.

Mixin fields: `review_ids`, `validated`, `rejected`, `need_validation`,
`validation_status`, `reviewer_ids`, `can_review`, `next_review`.

`tier.definition` fields relevant to the Nuclear Key protocol:
`sequence` (tier order), `approve_sequence` (**forces sequential rather than
parallel approval — required by PRD US-5.2, first criterion**),
`approve_sequence_bypass` (**must be left False**), `reviewer_group_id`,
`reviewer_id`, `has_comment`, `definition_domain`, `notify_on_pending`.

`tier.review` fields: `status`, `sequence`, `done_by`, `requested_by`,
`reviewed_date`, `comment`, `can_review`.

## What this does NOT establish

- That either module installs cleanly **against our database and alongside our
  own modules**. No Odoo runtime or PostgreSQL instance exists in the build
  environment (see `VERIFICATION_STATUS.md`).
- That `auditlog`'s performance is acceptable at our transaction volume. BRD
  Section 9 risk 6 and PRD risk 5 both flag this; it is Phase 4 load testing
  (P4-5), not something this task closes.
- That `base_tier_validation`'s duplicate-approver behaviour meets FR-5.1 out of
  the box. **It does not appear to prevent the same user from satisfying two
  tiers** where that user is in both reviewer groups. Treat identity-distinctness
  as our own logic to write in P2-7, not as inherited behaviour.

## Recommended pinning

Vendor both modules at a known commit rather than tracking branch HEAD, so a
mid-project upstream change cannot alter the enforcement behaviour of a
security control without review. Record the pinned commits here when the
deployment repository is set up (P0-1).
