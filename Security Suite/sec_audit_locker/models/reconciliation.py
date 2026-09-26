# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Daily reconciliation of the Locker against its replicas (P4-2, US-4.2).

US-4.2: "A reconciliation job runs at least daily, comparing primary log
counts/hashes to the external replica and alerting on mismatch."

Replication (P4-1) writes the evidence somewhere else. Reconciliation is what
makes that useful, because an unread replica proves nothing — it is a backup
that has never been restored.

**The comparison that matters most is the one nobody thinks of first.** The
obvious checks are "is anything missing from the replica" (shipping lag or
failure) and "do the hashes differ" (something was altered somewhere). But the
strongest signal of the threat this whole suite was built for is the third case:
**entries present in the replica and absent from the primary.**

That is precisely the shape of a database administrator deleting rows. It cannot
be a lag, it cannot be a network fault, and it cannot happen through the
application — ``audit.locker.entry.unlink()`` refuses for every role. So it is
reported separately, at critical severity, in the plainest language the module
uses anywhere.

**Unverifiable is not the same as verified.** An append-only file can be read
back and compared. An HTTPS target cannot, unless whoever holds it exposes a
retrieval endpoint. A target with no way to read it back is reported as
``unverifiable`` — never as passing. A reconciliation report that says "no
mismatches found" about a replica it could not read would be worse than no
report at all.
"""

import hashlib
import hmac
import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ReplicaTargetReconciliation(models.Model):
    _inherit = "audit.replica.target"

    verify_url = fields.Char(
        string="Verification URL",
        help="For an HTTPS target: an endpoint returning the replica's "
        "{sequence: entry_hash} map, so the copy can be compared without "
        "trusting this system. Without it the target cannot be reconciled and "
        "is reported as unverifiable.",
    )
    readable = fields.Boolean(
        string="Can Be Read Back",
        compute="_compute_readable",
        help="Whether reconciliation can actually compare this target.",
    )
    last_reconciled_at = fields.Datetime(
        string="Last Reconciled", readonly=True
    )

    @api.depends("target_type", "file_path", "verify_url")
    def _compute_readable(self):
        for target in self:
            if target.target_type == "append_file":
                target.readable = bool(target.file_path)
            elif target.target_type == "http":
                target.readable = bool(target.verify_url)
            else:
                target.readable = False

    # ------------------------------------------------------------------
    # Reading the replica back
    # ------------------------------------------------------------------
    def _read_replica_hashes(self):
        """Return {sequence: entry_hash} as held by the replica.

        Raises if the target cannot be read; the caller turns that into
        'unverifiable' rather than into a pass.
        """
        self.ensure_one()
        if self.target_type == "append_file":
            return self._read_append_file()
        if self.target_type == "http":
            return self._read_http()
        raise UserError(_("This target type cannot be read back."))

    def _read_append_file(self):
        hashes = {}
        duplicates = 0
        with open(self.file_path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    # A corrupt line is itself a finding, but one bad line must
                    # not abort the whole comparison.
                    _logger.warning(
                        "Unparseable line in replica %s", self.file_path
                    )
                    continue
                sequence = record.get("sequence")
                if sequence in (None, 0):
                    continue  # connectivity probes carry sequence 0
                if sequence in hashes:
                    duplicates += 1
                # Retries can ship the same entry twice. The last copy wins;
                # duplicates are counted, not treated as a mismatch.
                hashes[int(sequence)] = record.get("entry_hash")
        if duplicates:
            _logger.info(
                "%s duplicate entry(ies) in replica %s (retry artefacts)",
                duplicates,
                self.file_path,
            )
        return hashes

    def _read_http(self):
        import requests

        signature_body = b""
        signature = hmac.new(
            (self.shared_secret or "").encode("utf-8"),
            signature_body,
            hashlib.sha256,
        ).hexdigest()
        response = requests.get(
            self.verify_url,
            headers={"X-Locker-Signature": "sha256=%s" % signature},
            timeout=self.timeout_seconds or 10,
        )
        response.raise_for_status()
        payload = response.json()
        raw = payload.get("hashes", payload)
        return {int(key): value for key, value in raw.items()}


class ReconciliationRun(models.Model):
    """One reconciliation of one target. Append-only."""

    _name = "audit.reconciliation.run"
    _description = "Audit Locker Reconciliation Run"
    _order = "run_at desc, id desc"

    target_id = fields.Many2one(
        comodel_name="audit.replica.target",
        string="Target",
        required=True,
        ondelete="restrict",
        index=True,
    )
    run_at = fields.Datetime(
        string="Run At (UTC)", required=True, default=fields.Datetime.now
    )
    run_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Run By",
        default=lambda self: self.env.user,
        ondelete="restrict",
    )
    verdict = fields.Selection(
        selection=[
            ("match", "Match"),
            ("lag", "Behind - entries not yet shipped"),
            ("mismatch", "MISMATCH - investigate"),
            ("primary_missing", "PRIMARY MISSING ENTRIES - incident"),
            ("unverifiable", "Unverifiable - replica cannot be read"),
            ("error", "Error"),
        ],
        string="Verdict",
        required=True,
    )
    primary_count = fields.Integer(string="Primary Entries", readonly=True)
    replica_count = fields.Integer(string="Replica Entries", readonly=True)
    missing_in_replica = fields.Integer(
        string="Missing in Replica",
        readonly=True,
        help="Shipped nothing yet, or shipping failed. Usually a lag.",
    )
    hash_mismatches = fields.Integer(
        string="Hash Mismatches",
        readonly=True,
        help="Same sequence, different content hash. Something was altered on "
        "one side or the other.",
    )
    missing_in_primary = fields.Integer(
        string="Missing in PRIMARY",
        readonly=True,
        help="Entries the replica holds and the primary does not. This cannot "
        "happen through the application and is the signature of rows being "
        "deleted directly from the database.",
    )
    detail = fields.Text(string="Detail", readonly=True)

    def write(self, vals):
        raise UserError(
            _("Reconciliation results cannot be edited. Run a new one.")
        )

    def unlink(self):
        raise UserError(_("Reconciliation results cannot be deleted."))


class LockerReconciliation(models.Model):
    _inherit = "audit.locker.entry"

    @api.model
    def reconcile_target(self, target):
        """Compare the primary against one replica. Returns the run record."""
        Run = self.env["audit.reconciliation.run"].sudo()
        primary = {
            entry.sequence: entry.entry_hash
            for entry in self.sudo().search([], order="sequence asc")
        }

        if not target.readable:
            return Run.create(
                {
                    "target_id": target.id,
                    "verdict": "unverifiable",
                    "primary_count": len(primary),
                    "detail": _(
                        "This target cannot be read back, so its contents were "
                        "not compared. Nothing about it has been verified — do "
                        "not read this run as a pass. For an HTTPS target, ask "
                        "the custodian to expose a verification endpoint and "
                        "set it on the target."
                    ),
                }
            )

        try:
            replica = target._read_replica_hashes()
        except Exception as exc:  # noqa: BLE001 - recorded as a run, not lost
            _logger.exception("Could not read replica %s", target.name)
            return Run.create(
                {
                    "target_id": target.id,
                    "verdict": "error",
                    "primary_count": len(primary),
                    "detail": _(
                        "The replica could not be read: %(error)s. This is not "
                        "a pass; the copy is currently unverified.",
                        error=exc,
                    ),
                }
            )

        primary_sequences = set(primary)
        replica_sequences = set(replica)

        missing_in_replica = sorted(primary_sequences - replica_sequences)
        missing_in_primary = sorted(replica_sequences - primary_sequences)
        mismatched = sorted(
            sequence
            for sequence in primary_sequences & replica_sequences
            if primary[sequence] != replica[sequence]
        )

        if missing_in_primary:
            verdict = "primary_missing"
        elif mismatched:
            verdict = "mismatch"
        elif missing_in_replica:
            verdict = "lag"
        else:
            verdict = "match"

        detail_lines = []
        if missing_in_primary:
            detail_lines.append(
                _(
                    "ENTRIES DELETED FROM THE PRIMARY: sequences %(seqs)s exist "
                    "in the replica and not in the database. This cannot happen "
                    "through the application — deletion of Locker entries is "
                    "refused for every role — so it indicates rows removed "
                    "directly from the database. Treat as a security incident "
                    "and preserve the replica before anything else.",
                    seqs=_summarise(missing_in_primary),
                )
            )
        if mismatched:
            detail_lines.append(
                _(
                    "Content hash differs at sequences %(seqs)s. One side was "
                    "altered after the entry was written.",
                    seqs=_summarise(mismatched),
                )
            )
        if missing_in_replica:
            detail_lines.append(
                _(
                    "Not yet in the replica: sequences %(seqs)s. Usually "
                    "shipping lag; persistent across runs means replication is "
                    "failing.",
                    seqs=_summarise(missing_in_replica),
                )
            )
        if verdict == "match":
            detail_lines.append(
                _("Every one of %s primary entries matches the replica.",
                  len(primary))
            )

        run = Run.create(
            {
                "target_id": target.id,
                "verdict": verdict,
                "primary_count": len(primary),
                "replica_count": len(replica),
                "missing_in_replica": len(missing_in_replica),
                "hash_mismatches": len(mismatched),
                "missing_in_primary": len(missing_in_primary),
                "detail": "\n\n".join(detail_lines),
            }
        )
        target.sudo().write({"last_reconciled_at": fields.Datetime.now()})
        run._raise_alert_if_needed()
        return run

    @api.model
    def reconcile_all(self):
        """Reconcile every active target. Returns the run records."""
        targets = self.env["audit.replica.target"].sudo().search(
            [("active", "=", True)]
        )
        if not targets:
            self.env["sec.anomaly.mixin"]._raise_anomaly(
                alert_type="frozen_record_write_attempt",
                name=_("Audit log reconciliation impossible"),
                reason=_(
                    "No replication target is configured, so there is nothing "
                    "to reconcile the audit trail against. The Locker's "
                    "integrity currently rests entirely on its own hash chain "
                    "inside the database it is stored in."
                ),
                severity="critical",
            )
            return self.env["audit.reconciliation.run"]
        runs = self.env["audit.reconciliation.run"]
        for target in targets:
            runs |= self.reconcile_target(target)
        return runs

    @api.model
    def cron_reconcile(self):
        """Daily reconciliation (US-4.2)."""
        return self.reconcile_all()

    @api.model
    def reconciliation_status(self):
        """Latest verdict per target, for the forensic report."""
        targets = self.env["audit.replica.target"].sudo().search(
            [("active", "=", True)]
        )
        Run = self.env["audit.reconciliation.run"].sudo()
        results = []
        for target in targets:
            latest = Run.search(
                [("target_id", "=", target.id)], order="run_at desc", limit=1
            )
            results.append(
                {
                    "target": target.name,
                    "custodian": target.independent_custodian or "",
                    "verdict": latest.verdict if latest else "never_run",
                    "run_at": str(latest.run_at) if latest else "",
                    "missing_in_primary": latest.missing_in_primary if latest else 0,
                }
            )
        never_run = [r for r in results if r["verdict"] == "never_run"]
        bad = [
            r
            for r in results
            if r["verdict"] in ("mismatch", "primary_missing", "error", "unverifiable")
        ]
        return {
            "configured": bool(targets),
            # "Clean" requires that a comparison actually happened. Never-run
            # and unverifiable both count against it.
            "clean": bool(targets) and not bad and not never_run,
            "targets": results,
            "message": _("No replication target configured.")
            if not targets
            else _("%s target(s) reconciled; %s with findings.",
                   len(results), len(bad) + len(never_run)),
        }


class ReconciliationAlerting(models.Model):
    _inherit = "audit.reconciliation.run"

    def _raise_alert_if_needed(self):
        self.ensure_one()
        if self.verdict == "match":
            return False
        severity = {
            "primary_missing": "critical",
            "mismatch": "critical",
            "error": "high",
            "unverifiable": "high",
            "lag": "low",
        }.get(self.verdict, "medium")
        self.env["sec.anomaly.mixin"]._raise_anomaly(
            alert_type="frozen_record_write_attempt",
            name=_(
                "Locker reconciliation: %s",
                dict(self._fields["verdict"].selection).get(self.verdict),
            ),
            reason=self.detail or _("See the reconciliation run."),
            severity=severity,
            record=self,
        )
        if severity == "critical":
            _logger.critical(
                "Locker reconciliation %s against %s: %s",
                self.verdict,
                self.target_id.name,
                self.detail,
            )
        return True


def _summarise(sequences, limit=20):
    """Render a sequence list without producing an unreadable wall of numbers."""
    if len(sequences) <= limit:
        return ", ".join(str(s) for s in sequences)
    head = ", ".join(str(s) for s in sequences[:limit])
    return _("%(head)s ... and %(rest)s more", head=head, rest=len(sequences) - limit)
