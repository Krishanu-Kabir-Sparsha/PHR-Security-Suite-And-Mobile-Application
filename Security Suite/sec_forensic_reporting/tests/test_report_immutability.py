# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for report immutability and versioning (P3-5, US-8.1)."""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestReportImmutability(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Report = cls.env["forensic.report"]
        cls.start = date(2026, 7, 1)
        cls.end = date(2026, 7, 31)

    def _generate(self):
        return self.Report.generate_for_period(self.start, self.end)

    # --- No edits after generation -----------------------------------------
    def test_generated_report_cannot_be_edited(self):
        report = self._generate()
        with self.assertRaises(UserError) as caught:
            report.write({"findings_text": "Nothing to see here."})
        self.assertIn("cannot be changed", str(caught.exception))

    def test_generated_report_cannot_be_edited_by_sudo(self):
        report = self._generate()
        with self.assertRaises(UserError):
            report.sudo().write({"payload_json": "{}"})

    def test_generated_report_cannot_be_deleted(self):
        report = self._generate()
        with self.assertRaises(UserError):
            report.unlink()

    def test_headline_figures_cannot_be_quietly_adjusted(self):
        """The specific thing someone would want to change."""
        report = self._generate()
        with self.assertRaises(UserError):
            report.write({"finding_count": 0})

    def test_draft_report_is_still_editable(self):
        draft = self.Report.sudo().create(
            {
                "name": "FR/DRAFT/edit",
                "period_start": self.start,
                "period_end": self.end,
            }
        )
        draft.write({"name": "FR/DRAFT/renamed"})
        self.assertEqual(draft.name, "FR/DRAFT/renamed")

    def test_draft_report_can_be_deleted(self):
        draft = self.Report.sudo().create(
            {
                "name": "FR/DRAFT/removable",
                "period_start": self.start,
                "period_end": self.end,
            }
        )
        draft.unlink()

    # --- Tamper evidence ----------------------------------------------------
    def test_payload_is_hashed_at_generation(self):
        report = self._generate()
        self.assertTrue(report.payload_hash)
        self.assertEqual(len(report.payload_hash), 64)

    def test_intact_report_verifies(self):
        report = self._generate()
        self.assertTrue(report.integrity_ok)
        self.assertTrue(self.Report.verify_all(raise_anomaly=False)["intact"])

    def test_alteration_below_the_application_is_detected(self):
        """A generated report cannot be edited through the ORM, so this is the
        only way it could change: straight at the table."""
        report = self._generate()
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE forensic_report SET findings_text = %s, payload_json = %s "
            "WHERE id = %s",
            ("No findings.", '{"tampered": true}', report.id),
        )
        self.env.invalidate_all()
        self.assertFalse(report.integrity_ok)
        result = self.Report.verify_all(raise_anomaly=False)
        self.assertFalse(result["intact"])
        self.assertIn(report.name, result["broken"])

    def test_detected_alteration_raises_a_critical_anomaly(self):
        report = self._generate()
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE forensic_report SET payload_json = %s WHERE id = %s",
            ('{"tampered": true}', report.id),
        )
        self.env.invalidate_all()
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        self.Report.verify_all()
        self.assertGreater(Alert.search_count([]), before)
        self.assertEqual(
            Alert.search([], order="id desc", limit=1).severity, "critical"
        )

    def test_integrity_cron_is_active(self):
        cron = self.env.ref("sec_forensic_reporting.cron_verify_report_integrity")
        self.assertTrue(cron.active)

    # --- Versioning rather than overwrite -----------------------------------
    def test_new_version_supersedes_the_previous(self):
        first = self._generate()
        second = self._generate()
        first.invalidate_recordset()
        self.assertEqual(first.superseded_by_id, second)
        self.assertEqual(second.supersedes_id, first)

    def test_superseded_report_stays_readable(self):
        first = self._generate()
        self._generate()
        first.invalidate_recordset()
        self.assertTrue(first.exists())
        self.assertTrue(first.payload_json)
        self.assertTrue(first.integrity_ok)

    def test_is_current_tracks_supersession(self):
        first = self._generate()
        self.assertTrue(first.is_current)
        second = self._generate()
        first.invalidate_recordset()
        self.assertFalse(first.is_current)
        self.assertTrue(second.is_current)

    def test_version_number_increments(self):
        first = self._generate()
        second = self._generate()
        third = self._generate()
        self.assertEqual(
            [first.version, second.version, third.version], [1, 2, 3]
        )

    def test_supersession_does_not_break_the_earlier_hash(self):
        """Marking a report superseded must not invalidate its own integrity."""
        first = self._generate()
        original_hash = first.payload_hash
        self._generate()
        first.invalidate_recordset()
        self.assertEqual(first.payload_hash, original_hash)
        self.assertTrue(first.integrity_ok)

    # --- PDF pinned to the data ---------------------------------------------
    def test_pdf_cannot_be_rendered_before_generation(self):
        draft = self.Report.sudo().create(
            {
                "name": "FR/DRAFT/pdf",
                "period_start": self.start,
                "period_end": self.end,
            }
        )
        with self.assertRaises(UserError):
            draft.action_render_pdf()

    def test_pdf_render_stores_and_hashes_or_explains_why_not(self):
        """wkhtmltopdf may be absent; either outcome must be intelligible."""
        report = self._generate()
        try:
            report.action_render_pdf()
        except UserError as exc:
            self.assertIn("wkhtmltopdf", str(exc))
            return
        self.assertTrue(report.pdf_file)
        self.assertTrue(report.pdf_hash)
        self.assertEqual(len(report.pdf_hash), 64)
        self.assertTrue(report.pdf_rendered_at)

    def test_second_render_returns_the_stored_document(self):
        report = self._generate()
        try:
            report.action_render_pdf()
        except UserError:
            self.skipTest("wkhtmltopdf not available in this environment")
        first_hash = report.pdf_hash
        rendered_at = report.pdf_rendered_at
        report.action_render_pdf()
        self.assertEqual(report.pdf_hash, first_hash)
        self.assertEqual(report.pdf_rendered_at, rendered_at)
