# Design notes — sec_plaza_rbac

Decisions taken in session 1 that a reviewer might otherwise query, recorded
here rather than being buried in commit messages.

## 1. Catalog lower bound is a readiness gate, not a write constraint

PRD US-2.1 says the catalog is "bounded (min 10, max 20 active roles)". A
write-time constraint on the minimum is self-defeating: the first role created
would violate it, and so would any transitional state during a legitimate
re-organisation of the catalog.

Implemented instead as:
- **Maximum (20): hard constraint.** Exceeding it is always a policy breach.
- **Minimum (10): `check_catalog_readiness()`**, a go-live gate that also feeds
  the monthly forensic report.

The shipped catalog contains 15 roles, comfortably inside the band.

## 2. Role-backing groups are uncategorised

Odoo renders `res.groups` sharing a `category_id` as a single-choice selection
on the user form. Putting the 15 Plaza role groups in one category would make it
impossible for a user to hold two roles — which would technically eliminate all
cross-role SoD conflicts by making them unrepresentable, while doing nothing
about the real-world combinations the BRD is worried about. The groups are
therefore left uncategorised so they render as independent checkboxes.

## 3. Intra-role conflicts are blocked; cross-role conflicts are detected

BRD FR-2.4 asks for an SoD check. Two different mechanisms are appropriate:

- A single role granting both create and approve on one transaction class is
  never legitimate, so `capability = "create_approve"` raises on save. The
  violation cannot be authored.
- A *combination* of individually-valid roles held by one person can be
  legitimate temporarily (holiday cover, small teams). Blocking it at write time
  would be wrong. It is detected by `plaza.sod.scan`, reported, and either
  remediated or accepted as residual risk **with a mandatory written note and a
  named accepting user**.

## 4. Non-standard grants are refused by default, not merely logged

US-2.1's third criterion says such a grant "requires a logged justification and
is itself flagged for the monthly audit". Read literally, that permits the grant
to happen and be logged afterwards. Given the BRD's threat model is an
administrator acting under informal instruction, after-the-fact logging is the
weaker reading. Implemented as: the grant **fails** unless an approved,
unexpired `plaza.grant.exception` already exists. Logging still happens.

Recorded in `PROGRESS.md` under Known Deviations as a strengthening of the
stated criterion, for the product owner to confirm.

## 5. The access matrix does not yet generate ACLs

`role.plaza_model.access` currently *declares* intended access; live enforcement
still comes from hand-written `ir.model.access.csv` and `ir.rule` records. Making
the matrix the single source of truth that generates those records is the right
end state and is logged as an open question, because auto-generating ACLs is a
security-critical code path that deserves its own task rather than being
smuggled into P0-2.

## 6. `group_security_super_admin` lives here

`sec_plaza_rbac` is the foundation module everything else depends on, so the
suite-wide Super Administrator group is defined here rather than in
`sec_record_freeze`, which needs it for the US-3.2 lock toggles. The alternative
was a separate `sec_base` module for two XML records, which did not seem worth
the dependency.
