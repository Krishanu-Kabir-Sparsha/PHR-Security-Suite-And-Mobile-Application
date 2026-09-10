# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The Locker: a hash-chained, append-only audit trail.

Implements PRD US-4.1 and BRD FR-4.1 / FR-4.2. External replication (FR-4.3 /
US-4.2) is P4-1 and is not in this module; the ``external_replica_ref`` field is
the seam it will write to.

Why a hash chain rather than only "the ORM refuses to edit these rows":

FR-4.2 asks that log entries be neither editable nor deletable "by any role,
including system administrators". At the application layer we can deliver that,
and this module does. But BRD Section 8.2 already concedes the honest limit — a
PostgreSQL superuser bypasses permission checks by design, so an application
guarantee of immutability is a guarantee against everyone except the person most
worth worrying about.

A chain changes what is being claimed. Each entry's hash covers its own content
plus the previous entry's hash, so altering or removing any historical row
invalidates every hash after it. The claim becomes *tamper-evident* rather than
*tamper-proof*: a determined DBA can still change the data, but cannot do so
without leaving arithmetic that no longer adds up — and, once P4-1 ships,
without also having to alter a replica they do not administer.

That is a weaker claim than the source instructions asked for, and a much more
defensible one in front of an auditor.
"""

import hashlib
import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64


class LockerChain(models.Model):
    """Singleton holding the chain head.

    Exists so that appending an entry can take a row lock and serialise the
    read-modify-write of the previous hash. Without it, two concurrent writes
    read the same previous hash and the chain forks, which would look exactly
    like tampering during verification.

    The cost is honest: appends to the Locker serialise on this row. At the
    transaction volumes described in the BRD that is acceptable, but it is the
    first thing to measure in the P4-5 load test, and per-model chains are the
    obvious mitigation if it bites.
    """

    _name = "audit.locker.chain"
    _description = "Audit Locker Chain Head"

    name = fields.Char(default="main", required=True)
    last_hash = fields.Char(
        string="Last Entry Hash",
        default=GENESIS_HASH,
        required=True,
        help="Hash of the most recent entry; the next entry chains onto it.",
    )
    last_sequence = fields.Integer(
        string="Last Sequence",
        default=0,
        required=True,
        help="Monotonic counter of entries appended.",
    )

    _sql_constraints = [("name_uniq", "unique(name)", "Only one chain head.")]

    @api.model
    def _get_head(self):
        head = self.sudo().search([("name", "=", "main")], limit=1)
        if not head:
            head = self.sudo().create({"name": "main"})
        return head


class LockerEntry(models.Model):
    """One immutable, chained record of one action on one record."""

    _name = "audit.locker.entry"
    _description = "Audit Locker Entry"
    _order = "sequence desc, id desc"

    sequence = fields.Integer(
        string="Sequence",
        required=True,
        index=True,
        readonly=True,
        help="Position in the chain. Gaps are themselves a finding.",
    )
    timestamp_utc = fields.Datetime(
        string="Timestamp (UTC)",
        required=True,
        index=True,
        readonly=True,
        help="Server time in UTC. FR-4.1 requires NTP synchronisation; that is "
        "a host configuration matter and is asserted in the deployment "
        "checklist, not enforceable from here.",
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="User",
        required=True,
        index=True,
        readonly=True,
        ondelete="restrict",
        help="Acting user. Restrict on delete: removing a user must never "
        "destroy the record of what they did.",
    )
    user_login = fields.Char(
        string="User Login",
        required=True,
        readonly=True,
        help="Denormalised login, retained even if the user record changes.",
    )
    source_ip = fields.Char(
        string="Source IP",
        readonly=True,
        index=True,
        help="Client IP. Captured here because OCA auditlog does not record it "
        "and FR-4.1 requires it.",
    )
    model_name = fields.Char(
        string="Model", required=True, index=True, readonly=True
    )
    res_id = fields.Integer(string="Record ID", index=True, readonly=True)
    record_label = fields.Char(
        string="Record",
        readonly=True,
        help="Display name at the time of the action.",
    )
    action_type = fields.Selection(
        selection=[
            ("create", "Create"),
            ("write", "Write"),
            ("unlink", "Delete"),
            ("read", "Read"),
            ("other", "Other"),
        ],
        string="Action",
        required=True,
        index=True,
        readonly=True,
    )
    field_changes = fields.Text(
        string="Field Changes (JSON)",
        readonly=True,
        help="Field-level before/after values as a canonical JSON object. "
        "Part of the hashed payload, so it cannot be edited without "
        "breaking the chain.",
    )
    auditlog_log_id = fields.Many2one(
        comodel_name="auditlog.log",
        string="Source auditlog Entry",
        readonly=True,
        ondelete="restrict",
        help="The OCA auditlog record this entry mirrors.",
    )
    prev_hash = fields.Char(
        string="Previous Hash", required=True, readonly=True
    )
    entry_hash = fields.Char(
        string="Entry Hash", required=True, index=True, readonly=True
    )
    external_replica_ref = fields.Char(
        string="External Replica Reference",
        readonly=True,
        help="Populated by P4-1 once the entry is confirmed written to the "
        "append-only external store. Empty means this entry exists only in a "
        "database the application DBA controls.",
    )
    replicated_at = fields.Datetime(
        string="Replicated At", readonly=True
    )

    # ------------------------------------------------------------------
    # Hashing
    # ------------------------------------------------------------------
    @api.model
    def _canonical_payload(self, vals, prev_hash):
        """Deterministic serialisation of the hashed content.

        sort_keys and a fixed separator matter: a hash over a dict whose key
        order can vary is a hash that fails verification at random and teaches
        everyone to ignore the alarm.
        """
        payload = {
            "sequence": vals["sequence"],
            "timestamp_utc": str(vals["timestamp_utc"]),
            "user_login": vals["user_login"],
            "source_ip": vals.get("source_ip") or "",
            "model_name": vals["model_name"],
            "res_id": vals.get("res_id") or 0,
            "action_type": vals["action_type"],
            "field_changes": vals.get("field_changes") or "",
            "prev_hash": prev_hash,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @api.model
    def _compute_entry_hash(self, vals, prev_hash):
        return hashlib.sha256(
            self._canonical_payload(vals, prev_hash).encode("utf-8")
        ).hexdigest()

    # ------------------------------------------------------------------
    # Appending
    # ------------------------------------------------------------------
    @api.model
    def append(self, vals):
        """Append one entry to the chain. The only supported way to write here."""
        head = self.env["audit.locker.chain"]._get_head()
        # Serialise concurrent appends so two entries cannot chain onto the
        # same predecessor.
        self.env.cr.execute(
            "SELECT last_hash, last_sequence FROM audit_locker_chain "
            "WHERE id = %s FOR UPDATE",
            (head.id,),
        )
        row = self.env.cr.fetchone()
        prev_hash, last_sequence = (row[0], row[1]) if row else (GENESIS_HASH, 0)

        entry_vals = dict(vals)
        entry_vals["sequence"] = last_sequence + 1
        entry_vals.setdefault("timestamp_utc", fields.Datetime.now())
        entry_vals["prev_hash"] = prev_hash
        entry_vals["entry_hash"] = self._compute_entry_hash(entry_vals, prev_hash)

        entry = self.sudo().with_context(locker_append=True).create(entry_vals)
        self.env.cr.execute(
            "UPDATE audit_locker_chain SET last_hash = %s, last_sequence = %s "
            "WHERE id = %s",
            (entry_vals["entry_hash"], entry_vals["sequence"], head.id),
        )
        head.invalidate_recordset()
        return entry

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("locker_append"):
            raise UserError(
                _(
                    "Locker entries may only be created by the audit trail "
                    "itself, through append(). A hand-created entry would "
                    "carry no valid chain position."
                )
            )
        return super().create(vals_list)

    def write(self, vals):
        """Append-only, with one exception the chain does not cover."""
        replication_only = set(vals) <= {"external_replica_ref", "replicated_at"}
        if replication_only and self.env.context.get("locker_replication"):
            # Deliberately outside the hashed payload: replication status is
            # metadata about the entry, learned after it was written, and
            # including it would make the hash unstable by design.
            return super().write(vals)
        raise UserError(
            _(
                "Audit Locker entries cannot be modified. This is the record of "
                "what happened; changing it would defeat its only purpose."
            )
        )

    def unlink(self):
        raise UserError(
            _(
                "Audit Locker entries cannot be deleted. Retention is a policy "
                "decision for Legal and Compliance and is not implemented as a "
                "silent purge."
            )
        )

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------
    @api.model
    def verify_chain(self, limit=None, raise_anomaly=True):
        """Recompute every hash and report the first broken link.

        Intended to run daily (cron below) and to be cited in the monthly
        forensic report. Deliberately reports the *first* break: everything
        after it is unreliable anyway, and pointing at the earliest anomaly
        points at the event itself rather than its consequences.
        """
        domain = []
        entries = self.sudo().search(domain, order="sequence asc", limit=limit)
        prev_hash = GENESIS_HASH
        expected_sequence = 1
        result = {
            "checked": 0,
            "intact": True,
            "first_break_sequence": None,
            "reason": None,
        }
        for entry in entries:
            vals = {
                "sequence": entry.sequence,
                "timestamp_utc": entry.timestamp_utc,
                "user_login": entry.user_login,
                "source_ip": entry.source_ip,
                "model_name": entry.model_name,
                "res_id": entry.res_id,
                "action_type": entry.action_type,
                "field_changes": entry.field_changes,
            }
            if entry.sequence != expected_sequence:
                result.update(
                    intact=False,
                    first_break_sequence=entry.sequence,
                    reason=_(
                        "Sequence gap: expected %(expected)s, found %(found)s. "
                        "Entries appear to have been removed.",
                        expected=expected_sequence,
                        found=entry.sequence,
                    ),
                )
                break
            if entry.prev_hash != prev_hash:
                result.update(
                    intact=False,
                    first_break_sequence=entry.sequence,
                    reason=_("Chain link mismatch at sequence %s.", entry.sequence),
                )
                break
            recomputed = self._compute_entry_hash(vals, prev_hash)
            if recomputed != entry.entry_hash:
                result.update(
                    intact=False,
                    first_break_sequence=entry.sequence,
                    reason=_(
                        "Content hash mismatch at sequence %s: the stored "
                        "entry does not match its recorded hash.",
                        entry.sequence,
                    ),
                )
                break
            prev_hash = entry.entry_hash
            expected_sequence += 1
            result["checked"] += 1

        if not result["intact"] and raise_anomaly:
            self.env["sec.anomaly.mixin"]._raise_anomaly(
                alert_type="frozen_record_write_attempt",
                name=_("AUDIT LOCKER CHAIN BROKEN"),
                reason=_(
                    "Chain verification failed at sequence %(seq)s. %(reason)s "
                    "This indicates the audit trail has been altered below the "
                    "application layer. Treat as a security incident.",
                    seq=result["first_break_sequence"],
                    reason=result["reason"],
                ),
                severity="critical",
            )
            _logger.critical(
                "AUDIT LOCKER CHAIN BROKEN at sequence %s: %s",
                result["first_break_sequence"],
                result["reason"],
            )
        return result

    @api.model
    def cron_verify_chain(self):
        """Daily chain integrity check."""
        return self.verify_chain()


def post_init_hook(env):
    """Create the chain head and subscribe the shipped auditlog rules."""
    env["audit.locker.chain"]._get_head()
    rules = env["auditlog.rule"].sudo().search([("state", "!=", "subscribed")])
    for rule in rules:
        try:
            rule.subscribe()
        except Exception:  # noqa: BLE001 - one bad rule must not abort install
            _logger.exception("Could not subscribe auditlog rule %s", rule.name)
