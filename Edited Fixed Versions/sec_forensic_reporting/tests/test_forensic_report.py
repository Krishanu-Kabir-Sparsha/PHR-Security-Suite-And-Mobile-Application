# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for the monthly forensic report (P3-4, US-8.1, BRD FR-8)."""

import base64
import json
from datetime import date

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestForensicReport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Report = cls.env["forensic.report"]
        cls.start = date(2026, 8, 1)
        cls.end = date(2026, 8, 31)

    def _generate(self, start=None, end=None):
        return self.Report.generate_for_period(start or self.start, end or self.end)

    def _payload(self, report):
        return json.loads(report.payload_json or "{}")

    # --- Generation ---------------------------------------------------------
    def test_report_generates_and_is_marked_generated(self):
        report = self._generate()
        self.assertEqual(report.state, "generated")
        self.assertTrue(report.generated_at)
        self.assertEqual(report.generated_by_id, self.env.user)

    def test_payload_is_valid_json(self):
        report = self._generate()
        payload = self._payload(report)
        self.assertIsInstance(payload, dict)
        self.assertIn("period", payload)

    def test_report_covers_every_required_section(self):
        """US-8.1: overrides, declarations, anomalies, SoD."""
        payload = self._payload(self._generate())
        for section in (
            "overrides",
            "declarations",
            "anomalies",
            "segregation_of_duties",
        ):
            self.assertIn(section, payload, "Missing section: %s" % section)

    def test_report_records_its_period(self):
        report = self._generate()
        self.assertEqual(report.period_start, self.start)
        self.assertEqual(report.period_end, self.end)
        payload = self._payload(report)
        self.assertEqual(payload["period"]["start"], str(self.start))

    # --- Versioning rather than overwriting (leads into P3-5) --------------
    def test_second_report_for_a_period_is_a_new_version(self):
        first = self._generate()
        second = self._generate()
        self.assertEqual(first.version, 1)
        self.assertEqual(second.version, 2)
        self.assertNotEqual(first.id, second.id)

    def test_earlier_version_survives(self):
        first = self._generate()
        self._generate()
        self.assertTrue(first.exists())
        self.assertEqual(first.state, "generated")

    def test_cannot_regenerate_over_an_existing_report(self):
        report = self._generate()
        with self.assertRaises(UserError) as caught:
            report.action_generate()
        self.assertIn("already been generated", str(caught.exception))

    def test_reference_encodes_period_and_version(self):
        report = self._generate()
        self.assertIn("2026-08", report.name)
        self.assertIn("v1", report.name)

    # --- Findings: the part that makes it a compliance report --------------
    def test_findings_are_counted_and_stored(self):
        report = self._generate()
        self.assertEqual(
            report.finding_count,
            len([line for line in (report.findings_text or "").splitlines() if line.strip()]),
        )

    def test_unconfigured_threshold_control_is_a_finding(self):
        """An empty section must not read as a pass."""
        self.env["sec.value.threshold"].search([]).unlink()
        report = self._generate()
        self.assertIn("threshold", (report.findings_text or "").lower())

    def test_missing_sod_scan_is_a_finding(self):
        self.env["plaza.sod.scan"].sudo().search([]).unlink()
        report = self._generate()
        self.assertIn("segregation", (report.findings_text or "").lower())

    def test_unpublished_declaration_is_a_finding(self):
        self.env["declaration.version"].sudo().search(
            [("state", "=", "published")]
        ).write({"state": "superseded"})
        report = self._generate()
        self.assertIn("declaration", (report.findings_text or "").lower())

    def test_a_failing_section_becomes_a_finding_not_a_blank(self):
        """A section that cannot be established must not look clear."""
        findings = []
        result = self.Report._safe(
            "Test section", lambda: 1 / 0, findings
        )
        self.assertFalse(result.get("available"))
        self.assertTrue(findings)
        self.assertIn("not as clear", findings[0])

    def test_one_failing_section_does_not_abort_the_report(self):
        report = self._generate()
        self.assertEqual(report.state, "generated")

    # --- Override log contents (FR-4.4) ------------------------------------
    def test_override_log_records_instruction_source(self):
        partner = self.env["res.partner"].create({"name": "FR Customer"})
        product = self.env["product.product"].create(
            {"name": "FR Product", "list_price": 100.0}
        )
        order = self.env["sale.order"].create(
            {
                "partner_id": partner.id,
                "order_line": [
                    (0, 0, {"product_id": product.id, "product_uom_qty": 1,
                            "price_unit": 5000.0})
                ],
            }
        )
        order.action_confirm()
        attachment = self.env["ir.attachment"].create(
            {"name": "memo.pdf", "datas": base64.b64encode(b"x")}
        )
        self.env["override.request"].create(
            {
                "res_model": "sale.order",
                "res_id": order.id,
                "reason_category_id": self.env.ref(
                    "sec_override_engine.reason_data_entry_error"
                ).id,
                "justification": "Amount keyed wrong.",
                "proposed_changes": "price_unit 5000 -> 500",
                "instruction_type": "oral",
                "instructing_person_id": self.env.user.id,
                "attachment_ids": [(4, attachment.id)],
                "change_ids": [
                    (0, 0, {"field_name": "client_order_ref",
                            "new_value": "FIXED"})
                ],
            }
        )
        today = date.today()
        report = self._generate(
            start=today.replace(day=1), end=today
        )
        payload = self._payload(report)
        overrides = payload["overrides"]
        self.assertTrue(overrides.get("rows"))
        self.assertTrue(
            any(row.get("instruction_type") == "oral" for row in overrides["rows"]),
            "Oral instruction not distinguished in the override log (FR-4.4)",
        )
        self.assertGreaterEqual(overrides.get("oral", 0), 1)

    # --- Headline figures ---------------------------------------------------
    def test_headline_figures_are_stored_not_only_in_the_payload(self):
        report = self._generate()
        for field_name in (
            "override_count",
            "anomaly_count",
            "sod_conflict_count",
            "finding_count",
        ):
            self.assertIn(field_name, report._fields)
            self.assertIsNotNone(report[field_name])

    def test_chain_integrity_is_reported(self):
        report = self._generate()
        self.assertIn("chain_intact", report._fields)

    # --- Scheduling ---------------------------------------------------------
    def test_monthly_cron_is_active(self):
        cron = self.env.ref("sec_forensic_reporting.cron_monthly_forensic_report")
        self.assertTrue(cron.active)

    def test_cron_generates_for_the_previous_month(self):
        report = self.Report.cron_generate_monthly()
        today = date.today()
        self.assertLess(report.period_end, today.replace(day=1))
        self.assertEqual(report.state, "generated")

    def test_payload_helper_parses(self):
        report = self._generate()
        self.assertIsInstance(report.payload(), dict)

    def test_payload_helper_survives_malformed_json(self):
        """Written without touching a generated report, because P3-5 makes
        those immutable and this test must not become a casualty of it."""
        draft = self.Report.sudo().create(
            {
                "name": "FR/TEST/malformed",
                "period_start": self.start,
                "period_end": self.end,
                "payload_json": "not json",
            }
        )
        self.assertEqual(draft.payload(), {})
