# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""External replication of the audit Locker (P4-1, US-4.2, BRD FR-4.3).

FR-4.3: "Audit records must additionally be replicated to a storage target
outside the primary application database's administrative control."

This is the task that makes the difference between the Locker being *evidence*
and being *a table the DBA controls*. The hash chain from P1-7 makes alteration
detectable; it does not make it survivable. If the only copy lives in a database
one person administers, a sufficiently determined or sufficiently coerced
administrator can drop the lot and there is nothing left to compare against.

**The part that is not software.** BRD Section 8.2 is explicit and correct: this
control only works if the replica is administered by someone other than the
application DBA. A replica written to a directory on the same host, by the same
service account, protects against a bad UPDATE and against nothing else. The
code below cannot enforce organisational separation and does not pretend to —
what it does is make the *absence* of a configured, reachable target loud, so
"we have external replication" cannot be believed while nothing is running.

**What is replicated.** Each entry goes out with its sequence, its content and
both hashes. That matters: the external copy can independently verify the chain
without trusting anything from the primary. A replica of the data alone would
let an attacker who rewrote history simply replicate the rewritten version.

**Why a queue rather than an inline write.** Replication must never be able to
fail an audited business transaction — an audit control that can block a sales
order will be switched off the first time the network hiccups. Entries are
written locally, then shipped by a frequent cron. The lag is real and is
reported rather than glossed: `replication_status()` gives the backlog and the
age of the oldest unreplicated entry.
"""

import hashlib
import hmac
import json
import logging
import os
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 500
# Beyond this, the backlog is a finding rather than a lag.
BACKLOG_ALERT_MINUTES = 60


class AuditReplicaTarget(models.Model):
    """A destination the Locker is shipped to."""

    _name = "audit.replica.target"
    _description = "Audit Locker Replication Target"
    _order = "sequence, id"

    name = fields.Char(string="Name", required=True)
    sequence = fields.Integer(default=10)
    target_type = fields.Selection(
        selection=[
            ("append_file", "Append-only file"),
            ("http", "HTTPS endpoint (HMAC-signed)"),
        ],
        string="Type",
        required=True,
        default="append_file",
        help="Both write forward only. Object storage with a retention lock is "
        "the strongest option in principle; it is not implemented here because "
        "it needs a vendor SDK and credentials that belong to whoever "
        "administers that storage, not to this module.",
    )
    active = fields.Boolean(default=True)

    # --- append_file ---
    file_path = fields.Char(
        string="File Path",
        help="Absolute path, opened with O_APPEND. Point this at a mount the "
        "application DBA cannot administer — a path on the same host under the "
        "same service account satisfies the letter of FR-4.3 and none of its "
        "intent.",
    )

    # --- http ---
    endpoint_url = fields.Char(
        string="Endpoint URL",
        help="HTTPS endpoint receiving batches. Must be operated by whoever "
        "holds the independent copy.",
    )
    shared_secret = fields.Char(
        string="Shared Secret",
        help="Used to HMAC each batch, so the receiver can tell a genuine "
        "batch from one posted by anyone who found the URL.",
    )
    timeout_seconds = fields.Integer(string="Timeout (s)", default=10)

    # --- health ---
    last_success_at = fields.Datetime(string="Last Success", readonly=True)
    last_error = fields.Text(string="Last Error", readonly=True)
    last_error_at = fields.Datetime(string="Last Error At", readonly=True)
    entries_shipped = fields.Integer(string="Entries Shipped", readonly=True)
    independent_custodian = fields.Char(
        string="Independent Custodian",
        help="Who administers this target, and confirms they are not the "
        "application DBA. Recorded here because BRD Section 8.2 makes that "
        "separation the whole point, and a name in a field is at least "
        "auditable.",
    )

    @api.constrains("target_type", "file_path", "endpoint_url")
    def _check_target_is_usable(self):
        for target in self:
            if not target.active:
                continue
            if target.target_type == "append_file" and not target.file_path:
                raise ValidationError(
                    _("An append-only file target needs a file path.")
                )
            if target.target_type == "http":
                if not target.endpoint_url:
                    raise ValidationError(_("An HTTP target needs a URL."))
                if not target.endpoint_url.startswith("https://"):
                    raise ValidationError(
                        _(
                            "The replication endpoint must be HTTPS. Shipping "
                            "the audit trail in clear text would let anyone on "
                            "the path read or alter it."
                        )
                    )
                if not target.shared_secret:
                    raise ValidationError(
                        _(
                            "An HTTP target needs a shared secret, so the "
                            "receiver can distinguish a genuine batch from one "
                            "posted by anyone who found the URL."
                        )
                    )

    # ------------------------------------------------------------------
    # Shipping
    # ------------------------------------------------------------------
    def _serialise(self, entries):
        """One JSON object per entry, chain hashes included.

        The hashes travel with the data so the holder of the replica can verify
        the chain themselves. Replicating content alone would let someone who
        rewrote history replicate the rewrite unchallenged.
        """
        return [
            {
                "sequence": entry.sequence,
                "timestamp_utc": str(entry.timestamp_utc),
                "user_login": entry.user_login,
                "source_ip": entry.source_ip or "",
                "model_name": entry.model_name,
                "res_id": entry.res_id,
                "record_label": entry.record_label or "",
                "action_type": entry.action_type,
                "field_changes": entry.field_changes or "",
                "prev_hash": entry.prev_hash,
                "entry_hash": entry.entry_hash,
            }
            for entry in entries
        ]

    def _ship_append_file(self, payload):
        path = self.file_path
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        # O_APPEND so concurrent writers cannot overwrite each other, and no
        # mode that would let this process rewrite what is already there.
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o640)
        try:
            body = "".join(
                json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
                for record in payload
            )
            os.write(handle, body.encode("utf-8"))
            os.fsync(handle)
        finally:
            os.close(handle)
        return "file://%s#%s" % (path, payload[-1]["sequence"])

    def _ship_http(self, payload):
        import requests

        body = json.dumps(
            {"entries": payload}, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        signature = hmac.new(
            (self.shared_secret or "").encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        response = requests.post(
            self.endpoint_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Locker-Signature": "sha256=%s" % signature,
                "X-Locker-Count": str(len(payload)),
            },
            timeout=self.timeout_seconds or 10,
        )
        response.raise_for_status()
        return "%s#%s" % (self.endpoint_url, payload[-1]["sequence"])

    def ship(self, entries):
        """Send a batch. Returns a reference string, or raises."""
        self.ensure_one()
        payload = self._serialise(entries)
        if not payload:
            return False
        if self.target_type == "append_file":
            reference = self._ship_append_file(payload)
        elif self.target_type == "http":
            reference = self._ship_http(payload)
        else:
            raise UserError(_("Unknown replication target type."))
        self.sudo().write(
            {
                "last_success_at": fields.Datetime.now(),
                "entries_shipped": self.entries_shipped + len(payload),
                "last_error": False,
            }
        )
        return reference

    def action_test(self):
        """Ship a single synthetic record to prove the target works.

        Deliberately writes a real record to the target rather than only
        checking reachability: a target that accepts a connection but rejects
        the payload is the failure people discover during an incident.
        """
        self.ensure_one()
        probe = [
            {
                "sequence": 0,
                "timestamp_utc": str(fields.Datetime.now()),
                "user_login": self.env.user.login,
                "source_ip": "",
                "model_name": "audit.replica.target",
                "res_id": self.id,
                "record_label": "connectivity probe",
                "action_type": "other",
                "field_changes": "",
                "prev_hash": "",
                "entry_hash": "probe",
            }
        ]
        try:
            if self.target_type == "append_file":
                self._ship_append_file(probe)
            else:
                self._ship_http(probe)
        except Exception as exc:  # noqa: BLE001 - reported to the operator
            self.sudo().write(
                {"last_error": str(exc), "last_error_at": fields.Datetime.now()}
            )
            raise UserError(
                _("Replication target test failed: %s", exc)
            ) from exc
        raise UserError(
            _(
                "Target reachable and a probe record was written. Confirm with "
                "%(custodian)s that it arrived, and that they — not the "
                "application DBA — control it.",
                custodian=self.independent_custodian or _("the custodian"),
            )
        )


class LockerReplication(models.Model):
    _inherit = "audit.locker.entry"

    @api.model
    def _pending_replication(self, limit=DEFAULT_BATCH_SIZE):
        return self.sudo().search(
            [("external_replica_ref", "=", False)],
            order="sequence asc",
            limit=limit,
        )

    @api.model
    def replicate_pending(self, limit=DEFAULT_BATCH_SIZE):
        """Ship everything not yet replicated. Safe to call repeatedly."""
        targets = self.env["audit.replica.target"].sudo().search(
            [("active", "=", True)]
        )
        if not targets:
            return {
                "shipped": 0,
                "targets": 0,
                "message": _("No active replication target is configured."),
            }
        entries = self._pending_replication(limit=limit)
        if not entries:
            return {"shipped": 0, "targets": len(targets), "message": _("Nothing pending.")}

        references = []
        failures = []
        for target in targets:
            try:
                references.append(target.ship(entries))
            except Exception as exc:  # noqa: BLE001 - recorded, then reported
                _logger.exception("Replication to %s failed", target.name)
                target.sudo().write(
                    {"last_error": str(exc), "last_error_at": fields.Datetime.now()}
                )
                failures.append("%s: %s" % (target.name, exc))

        if failures and not references:
            # Nothing got out. Leave the entries pending so the next run
            # retries them; marking them replicated here would quietly lose
            # them forever.
            self.env["sec.anomaly.mixin"]._raise_anomaly(
                alert_type="frozen_record_write_attempt",
                name=_("Audit log replication failing"),
                reason=_(
                    "No replication target accepted the audit trail: "
                    "%(failures)s. Until this is fixed the Locker exists only "
                    "in the primary database, where the application DBA "
                    "controls it.",
                    failures="; ".join(failures),
                ),
                severity="critical",
            )
            return {"shipped": 0, "targets": len(targets), "failures": failures}

        entries.with_context(locker_replication=True).sudo().write(
            {
                "external_replica_ref": " | ".join(references)[:255],
                "replicated_at": fields.Datetime.now(),
            }
        )
        _logger.info(
            "Replicated %s Locker entries to %s target(s)",
            len(entries),
            len(references),
        )
        return {
            "shipped": len(entries),
            "targets": len(references),
            "failures": failures,
        }

    @api.model
    def cron_replicate(self):
        """Frequent shipping. Batched so a backlog drains over several runs."""
        return self.replicate_pending()

    @api.model
    def replication_status(self):
        """Backlog and target health, for the forensic report and P4-2.

        Reports the absence of a target as a failure rather than as zero
        backlog: "nothing is waiting to be replicated" is technically true when
        replication was never configured, and dangerously misleading.
        """
        targets = self.env["audit.replica.target"].sudo().search(
            [("active", "=", True)]
        )
        pending = self.sudo().search(
            [("external_replica_ref", "=", False)], order="sequence asc"
        )
        oldest = pending[:1]
        oldest_age_minutes = 0
        if oldest:
            delta = fields.Datetime.now() - oldest.timestamp_utc
            oldest_age_minutes = int(delta.total_seconds() // 60)

        if not targets:
            return {
                "configured": False,
                "healthy": False,
                "pending": len(pending),
                "message": _(
                    "No replication target is configured. The audit trail "
                    "exists only in the primary database, so BRD FR-4.3 is not "
                    "met and the Locker's evidential value depends entirely on "
                    "the application DBA."
                ),
            }
        stale = oldest_age_minutes > BACKLOG_ALERT_MINUTES
        broken = targets.filtered(lambda t: t.last_error)
        return {
            "configured": True,
            "healthy": not stale and not broken,
            "targets": [
                {
                    "name": t.name,
                    "type": t.target_type,
                    "custodian": t.independent_custodian or "",
                    "last_success": str(t.last_success_at or ""),
                    "last_error": t.last_error or "",
                }
                for t in targets
            ],
            "pending": len(pending),
            "oldest_pending_minutes": oldest_age_minutes,
            "message": _("Replication healthy.")
            if not stale and not broken
            else _(
                "Replication is behind: %(pending)s entry(ies) pending, oldest "
                "%(age)s minutes old.",
                pending=len(pending),
                age=oldest_age_minutes,
            ),
        }

    @api.model
    def cron_check_replication_backlog(self):
        """Raise an alert when the backlog stops being a lag."""
        status = self.replication_status()
        if not status.get("healthy"):
            self.env["sec.anomaly.mixin"]._raise_anomaly(
                alert_type="frozen_record_write_attempt",
                name=_("Audit log replication unhealthy"),
                reason=status.get("message"),
                severity="critical" if not status.get("configured") else "high",
            )
        return status
