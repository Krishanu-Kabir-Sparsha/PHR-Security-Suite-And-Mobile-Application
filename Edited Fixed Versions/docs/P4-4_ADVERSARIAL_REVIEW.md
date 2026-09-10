# P4-4 — Adversarial Security Review

**Date:** 05 September 2026 (session 23)
**Method:** attack the claims, not re-read the code that makes them.
**Caveat that limits everything below:** this was a code-level review. No test
has been executed and no deployed instance was probed. A real adversarial test
happens against a running system, by someone who did not write it.

---

## Findings

Three real bypasses were found. All three are fixed, with tests that fail
against the previous behaviour.

### F-1 — A line could be added to a frozen document · **critical** · fixed

**The claim:** a confirmed Sales Order cannot be changed.

**The attack:** don't edit the order. Create a new `sale.order.line` pointing at
it.

```python
order.write({'amount_total': 1})            # refused
order.order_line = [(0, 0, {...})]          # refused (order_line is protected)
env['sale.order.line'].create({'order_id': order.id, ...})   # WORKED
```

The freeze mixin's `create()` checked only the stream lock. `write()` and
`unlink()` resolved a line's frozen state from its parent; `create()` did not,
because a record being created has no prior state and the check was never
written. The total recomputes either way, so this changed the confirmed value of
the document.

**The same gap existed one layer down.** The PL/pgSQL trigger was declared
`BEFORE UPDATE OR DELETE`, so raw `INSERT` was unguarded too — both defences had
the identical blind spot, which is what happens when the second layer is written
by mirroring the first.

**Fix:** `_freeze_check_create` resolves the parent's state from the submitted
values and refuses, honouring a scoped unlock ticket. Trigger extended to
`BEFORE INSERT`. Direct inserts into *parent* tables are deliberately still
allowed, because Odoo creates documents in draft and blocking there would break
data import for no security gain.

### F-2 — Approved values could be rewritten before execution · **critical** · fixed

**The claim:** three approvals authorise a specific change.

**The attack:** get the change approved, then edit it.

`override.request` locks its justification once under review. But the field
values that execution actually applies live in `override.change`, a child model
which shipped with `1,1,1,1` for `base.group_user` and no guard of its own. A
requester could obtain three WebAuthn-authenticated approvals for "set the
reference to PO-1" and then change the row to "set the counterparty to X" before
pressing Execute.

This is the worst of the three: it does not defeat the approval workflow, it
*recruits* it. The signatures remain valid and attest to something that never
happened.

**Fix:** create, write and unlink on `override.change` refuse once the parent
leaves draft, and raise a critical anomaly. Value capture during submission runs
under an explicit internal context.

### F-3 — An alert could be closed without recording who closed it · **high** · fixed

**The claim (P3-3):** every triage decision is logged.

**The attack:** don't use the button.

`anomaly.alert` had no `write()` guard and Compliance holds write access, so
`alert.write({'state': 'reviewed'})` closed an inconvenient finding with no
`anomaly.review` row, no note and no reviewer recorded. The mandatory note was
mandatory only for people who used the supported route.

**Fix:** writes touching `state`, `reviewed_by_id` or `reviewed_at` are refused
outside the logged actions; `unlink()` refused entirely. Other fields stay
writable so the guard does not freeze the record.

---

## Claims re-attacked and holding

Each now has an explicit adversarial test rather than resting on the test that
was written alongside the feature.

| Claim | Attack attempted | Result |
|---|---|---|
| `sudo()` cannot edit a frozen record | direct `sudo().write()` | refused |
| Superuser cannot edit a frozen record | `with_user(base.user_root)` | refused |
| A context key is not authorisation | fabricated `sec_freeze_unlock_ticket=99999999` | refused |
| An unlock is scoped to its fields | ticket for `client_order_ref`, write `partner_id` alongside | refused |
| An unlock is scoped to its record | ticket for order A, write order B | refused |
| A spent ticket is spent | re-use after execution | refused |
| A ticket never authorises deletion | `unlink()` under a valid ticket | refused |
| Locker entries are append-only | `write`/`unlink`, including `sudo()` | refused |
| Chain alteration is detectable | raw SQL `UPDATE` and `DELETE` | detected |
| Reports are immutable once generated | `write`/`unlink`, including `sudo()` | refused |
| One person cannot satisfy two tiers | user holding two reviewer roles | refused |
| Paired accounts cannot double-approve | two logins, one `res.partner` | refused |
| Approval needs WebAuthn | approve with no assertion | refused |
| An assertion authorises one action | assertion for request A used on request B | refused |
| Declaration gate covers RPC | `/web/dataset/call_kw` while outstanding | gated |

---

## Accepted residual risks

**`/web/image` is reachable before declaration acceptance.** The gate allowlist
permits it so the declaration page itself can render. It can serve binary fields
from arbitrary models, so it is a narrow read path open to a logged-in user who
has not yet accepted. Accepted: the declaration is an acknowledgment control,
not a confidentiality control, and removing the entry breaks the page that
collects the acknowledgment. Worth revisiting if the gate is ever repurposed.

**Anyone with write access can execute an already-approved override.** The
content is fixed by F-2's fix, so the actor cannot change what happens, only
when. Low value to an attacker; noted rather than fixed.

**A PostgreSQL superuser defeats everything.** Unchanged, and correctly so:
triggers can be dropped, tables can be edited. What the suite provides is
detection (chain, reconciliation) and durability (replication), not prevention.
This is the honest limit and P0-1 remains the real mitigation.

---

## What this review could not do

- **Execute anything.** Every finding above was reasoned from source. The fixes
  have tests; the tests have never run.
- **Probe a live system.** Session handling, CSRF, the browser ceremonies and
  the reverse proxy layer are untested by definition here.
- **Be independent.** I wrote the code I reviewed. Three findings in one pass
  suggests the method works, and also that an independent reviewer would
  probably find more. Budget for one.
