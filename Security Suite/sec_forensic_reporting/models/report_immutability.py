# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Immutable, versioned forensic reports (P3-5, US-8.1 final criterion).

"Report is exportable (PDF at minimum) and itself immutable once generated
(subsequent edits create a new version, not an overwrite)."

Three separate properties are needed, and only the first is obvious.

**1. No edits after generation.** ``write()`` and ``unlink()`` refuse once the
report is generated. Until this task they were entirely unguarded — only
regeneration over an existing record was blocked — so a generated report was
editable, which would have made the whole document worthless as evidence.

**2. Tamper evidence, not just refusal.** The same argument as the Locker
(BRD Section 8.2): an application-layer refusal binds everyone except the person
with a database prompt. So the payload is hashed at generation and the hash can
be re-checked later. The claim becomes "an altered report is detectable", which
is true, rather than "a report cannot be altered", which is not.

**3. The document must be pinned to the data.** A PDF re-rendered on demand
months later runs today's template over today's code. If either changed, the
document differs from the one the CEO/Owner signed off, with nothing to show
for it. The rendered PDF is therefore generated once, stored, and hashed;
subsequent downloads return the stored bytes.

Versioning: a new report for the same period is a new version, and the previous
one is marked superseded and linked, so the chain of what was reported when
stays readable rather than being replaced.
"""

import hashlib
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Fields the generation flow itself must be able to set, and the narrow set of
# post-generation metadata that is legitimately learned afterwards.
GENERATION_FIELDS = {
    "state", "generated_at", "generated_by_id", "payload_json", "payload_hash",
    "override_count", "override_oral_count", "anomaly_count",
    "anomaly_open_high", "sod_conflict_count", "declaration_outstanding",
    "chain_intact", "finding_count", "findings_text",
}
POST_GENERATION_FIELDS = {
    "pdf_file", "pdf_filename", "pdf_hash", "pdf_rendered_at",
    "superseded_by_id", "state",
}


class ForensicReportImmutability(models.Model):
    _inherit = "forensic.report"

    payload_hash = fields.Char(
        string="Payload Hash (SHA-256)",
        readonly=True,
        help="Hash of the collected data at generation. Re-checkable later, so "
        "an alteration below the application layer is detectable.",
    )
    pdf_file = fields.Binary(
        string="Report PDF", readonly=True, attachment=True,
        help="Rendered once and stored. Later downloads return these bytes, so "
        "the document cannot silently change with the template.",
    )
    pdf_filename = fields.Char(string="PDF Filename", readonly=True)
    pdf_hash = fields.Char(string="PDF Hash (SHA-256)", readonly=True)
    pdf_rendered_at = fields.Datetime(string="PDF Rendered At", readonly=True)
    superseded_by_id = fields.Many2one(
        comodel_name="forensic.report",
        string="Superseded By",
        readonly=True,
        ondelete="restrict",
        help="The later version of this period's report, if one exists.",
    )
    supersedes_id = fields.Many2one(
        comodel_name="forensic.report",
        string="Supersedes",
        readonly=True,
        ondelete="restrict",
    )
    is_current = fields.Boolean(
        string="Current Version",
        compute="_compute_is_current",
        store=True,
        help="False once a later version exists for the same period.",
    )
    integrity_ok = fields.Boolean(
        string="Integrity Verified",
        compute="_compute_integrity",
        help="Recomputes the payload hash on read. False means the stored data "
        "no longer matches what was hashed at generation.",
    )

    @api.depends("superseded_by_id")
    def _compute_is_current(self):
        for report in self:
            report.is_current = not report.superseded_by_id

    def _compute_integrity(self):
        for report in self:
            if not report.payload_hash:
                report.integrity_ok = True  # pre-P3-5 record, nothing to check
                continue
            report.integrity_ok = (
                report._hash_payload(report.payload_json) == report.payload_hash
            )

    # ------------------------------------------------------------------
    # Hashing
    # ------------------------------------------------------------------
    @staticmethod
    def _hash_payload(payload_json):
        return hashlib.sha256((payload_json or "").encode("utf-8")).hexdigest()

    @staticmethod
    def _hash_bytes(raw):
        return hashlib.sha256(raw or b"").hexdigest()

    # ------------------------------------------------------------------
    # Generation, extended
    # ------------------------------------------------------------------
    def action_generate(self):
        """Hash the payload and supersede the previous version."""
        result = super().action_generate()
        for report in self:
            values = {"payload_hash": report._hash_payload(report.payload_json)}
            previous = self.sudo().search(
                [
                    ("period_start", "=", report.period_start),
                    ("period_end", "=", report.period_end),
                    ("id", "!=", report.id),
                    ("superseded_by_id", "=", False),
                ],
                order="version desc",
                limit=1,
            )
            if previous:
                values["supersedes_id"] = previous.id
                # Written through the internal context, since the guard below
                # otherwise refuses any write to a generated report.
                previous.with_context(forensic_internal=True).sudo().write(
                    {"superseded_by_id": report.id}
                )
            report.with_context(forensic_internal=True).sudo().write(values)
            _logger.info(
                "Forensic report %s sealed (payload hash %s...)",
                report.name,
                values["payload_hash"][:12],
            )
        return result

    # ------------------------------------------------------------------
    # PDF, rendered once
    # ------------------------------------------------------------------
    def action_render_pdf(self):
        """Render and store the PDF. Returns the stored bytes on re-call."""
        self.ensure_one()
        if self.state != "generated":
            raise UserError(
                _("Generate the report before rendering its document.")
            )
        if self.pdf_file:
            return self._download_action()
        report_action = self.env.ref(
            "sec_forensic_reporting.action_report_forensic",
            raise_if_not_found=False,
        )
        if not report_action:
            raise UserError(_("The report action is missing."))
        try:
            pdf_bytes, _content_type = report_action.sudo()._render_qweb_pdf(
                report_action.report_name, res_ids=self.ids
            )
        except Exception as exc:  # noqa: BLE001 - surfaced, not hidden
            _logger.exception("PDF rendering failed for %s", self.name)
            raise UserError(
                _(
                    "The report could not be rendered as PDF: %(error)s\n\n"
                    "This usually means wkhtmltopdf is not installed on the "
                    "server. The report data itself is complete and readable "
                    "on screen; only the document export is affected.",
                    error=exc,
                )
            ) from exc

        import base64

        self.with_context(forensic_internal=True).sudo().write(
            {
                "pdf_file": base64.b64encode(pdf_bytes),
                "pdf_filename": "%s.pdf" % (self.name or "forensic-report").replace(
                    "/", "-"
                ),
                "pdf_hash": self._hash_bytes(pdf_bytes),
                "pdf_rendered_at": fields.Datetime.now(),
            }
        )
        _logger.info("Forensic report %s PDF rendered and sealed", self.name)
        return self._download_action()

    def _download_action(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/forensic.report/%s/pdf_file/%s?download=true"
            % (self.id, self.pdf_filename or "report.pdf"),
            "target": "self",
        }

    # ------------------------------------------------------------------
    # Immutability
    # ------------------------------------------------------------------
    def write(self, vals):
        """Refuse edits to a generated report."""
        if self.env.context.get("forensic_internal"):
            return super().write(vals)
        for report in self:
            if report.state != "generated":
                continue
            attempted = set(vals)
            if attempted.issubset(POST_GENERATION_FIELDS):
                # Rendering the document and recording supersession are the
                # only things legitimately learned after generation.
                continue
            raise UserError(
                _(
                    "Report %(name)s was generated on %(when)s and cannot be "
                    "changed. If the picture has changed, generate a new "
                    "version for the same period — the earlier one stays "
                    "readable and is linked as superseded.",
                    name=report.name,
                    when=report.generated_at,
                )
            )
        return super().write(vals)

    def unlink(self):
        for report in self:
            if report.state == "generated":
                raise UserError(
                    _(
                        "Generated reports cannot be deleted. Retention is a "
                        "policy decision for Legal and Compliance, not a "
                        "button."
                    )
                )
        return super().unlink()

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------
    @api.model
    def verify_all(self, raise_anomaly=True):
        """Re-check every sealed report against its stored hashes.

        Intended for the daily reconciliation alongside the Locker chain check.
        A report whose payload no longer matches its hash was altered below the
        application layer.
        """
        reports = self.sudo().search([("state", "=", "generated")])
        broken = []
        for report in reports:
            if report.payload_hash and report._hash_payload(
                report.payload_json
            ) != report.payload_hash:
                broken.append(report.name)
        if broken and raise_anomaly:
            self.env["sec.anomaly.mixin"]._raise_anomaly(
                alert_type="frozen_record_write_attempt",
                name=_("FORENSIC REPORT ALTERED"),
                reason=_(
                    "The stored data of report(s) %(names)s no longer matches "
                    "the hash recorded at generation. A generated report cannot "
                    "be edited through the application, so this indicates a "
                    "change made below it. Treat as a security incident.",
                    names=", ".join(broken),
                ),
                severity="critical",
            )
            _logger.critical("Forensic report integrity failure: %s", broken)
        return {
            "checked": len(reports),
            "broken": broken,
            "intact": not broken,
        }

    @api.model
    def cron_verify_integrity(self):
        return self.verify_all()
