# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for the triage wizard, especially its friction on bulk (P3-3)."""

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestReviewWizard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Wizard = cls.env["anomaly.review.wizard"]
        cls.Alert = cls.env["anomaly.alert"]

    def _alerts(self, count, severity="low"):
        return self.Alert.sudo().create([
            {
                "alert_type": "out_of_hours_edit",
                "name": "Routine alert %s" % index,
                "reason": "Evening edit.",
                "severity": severity,
            }
            for index in range(count)
        ])

    def test_single_review_is_not_marked_bulk(self):
        alerts = self._alerts(1)
        wizard = self.Wizard.create(
            {"alert_ids": [(6, 0, alerts.ids)], "outcome": "benign",
             "note": "Known late shift."}
        )
        wizard.action_apply()
        self.assertFalse(alerts.review_ids[0].bulk)

    def test_bulk_review_marks_every_row(self):
        alerts = self._alerts(5)
        wizard = self.Wizard.create(
            {"alert_ids": [(6, 0, alerts.ids)], "outcome": "benign",
             "note": "Month-end close; the whole team worked late."}
        )
        wizard.action_apply()
        for alert in alerts:
            self.assertEqual(alert.state, "reviewed")
            self.assertTrue(alert.review_ids[0].bulk)

    def test_each_alert_gets_its_own_review_row(self):
        alerts = self._alerts(4)
        wizard = self.Wizard.create(
            {"alert_ids": [(6, 0, alerts.ids)], "outcome": "benign",
             "note": "Routine."}
        )
        wizard.action_apply()
        self.assertEqual(
            self.env["anomaly.review"].sudo().search_count(
                [("alert_id", "in", alerts.ids)]
            ),
            4,
        )

    def test_high_severity_cannot_be_swept_up_in_a_batch(self):
        """The exact thing a bulk action would be misused for."""
        alerts = self._alerts(3) | self._alerts(1, severity="critical")
        wizard = self.Wizard.create(
            {"alert_ids": [(6, 0, alerts.ids)], "outcome": "benign",
             "note": "All routine."}
        )
        with self.assertRaises(UserError) as caught:
            wizard.action_apply()
        self.assertIn("individually", str(caught.exception).lower())

    def test_single_high_severity_review_is_allowed(self):
        alerts = self._alerts(1, severity="critical")
        wizard = self.Wizard.create(
            {"alert_ids": [(6, 0, alerts.ids)], "outcome": "explained",
             "note": "Confirmed with the CEO directly."}
        )
        wizard.action_apply()
        self.assertEqual(alerts.state, "reviewed")

    def test_note_is_mandatory(self):
        alerts = self._alerts(2)
        with self.assertRaises(Exception):
            self.Wizard.create(
                {"alert_ids": [(6, 0, alerts.ids)], "outcome": "benign"}
            ).action_apply()

    def test_already_reviewed_alerts_are_refused(self):
        alerts = self._alerts(2)
        alerts[0].action_mark_reviewed(note="Done earlier.")
        wizard = self.Wizard.create(
            {"alert_ids": [(6, 0, alerts.ids)], "outcome": "benign",
             "note": "Routine."}
        )
        with self.assertRaises(UserError):
            wizard.action_apply()

    def test_empty_selection_is_refused(self):
        wizard = self.Wizard.create(
            {"alert_ids": [(6, 0, [])], "outcome": "benign", "note": "x"}
        )
        with self.assertRaises(UserError):
            wizard.action_apply()

    def test_contains_severe_is_computed(self):
        alerts = self._alerts(2) | self._alerts(1, severity="high")
        wizard = self.Wizard.create(
            {"alert_ids": [(6, 0, alerts.ids)], "outcome": "benign", "note": "x"}
        )
        self.assertTrue(wizard.contains_severe)
        self.assertEqual(wizard.alert_count, 3)
