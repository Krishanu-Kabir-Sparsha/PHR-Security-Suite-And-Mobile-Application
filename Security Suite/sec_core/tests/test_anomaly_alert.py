# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for the shared anomaly alert primitive."""

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAnomalyAlert(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Alert = cls.env["anomaly.alert"]
        cls.Mixin = cls.env["sec.anomaly.mixin"]

    def test_raise_anomaly_creates_alert(self):
        alert = self.Mixin._raise_anomaly(
            alert_type="missing_documentation",
            name="Test alert",
            reason="Because this is a test.",
            severity="high",
        )
        self.assertTrue(alert)
        self.assertEqual(alert.alert_type, "missing_documentation")
        self.assertEqual(alert.severity, "high")
        self.assertEqual(alert.state, "new")
        self.assertEqual(alert.user_id, self.env.user)
        self.assertTrue(alert.raised_at)

    def test_raise_anomaly_records_target_record(self):
        partner = self.env["res.partner"].create({"name": "Target"})
        alert = self.Mixin._raise_anomaly(
            alert_type="other",
            name="Targeted alert",
            reason="Has a target.",
            record=partner,
        )
        self.assertEqual(alert.res_model, "res.partner")
        self.assertEqual(alert.res_id, partner.id)

    def test_raise_anomaly_never_raises_on_bad_input(self):
        """Alerting must never break the security decision that triggered it."""
        alert = self.Mixin._raise_anomaly(
            alert_type="not_a_valid_selection_value",
            name="Bad type",
            reason="Should be swallowed.",
        )
        self.assertFalse(alert)

    def test_mark_reviewed_requires_a_note(self):
        alert = self.Mixin._raise_anomaly(
            alert_type="other", name="Needs review", reason="Reason."
        )
        with self.assertRaises(UserError):
            alert.action_mark_reviewed()
        alert.review_note = "Investigated; benign."
        alert.action_mark_reviewed()
        self.assertEqual(alert.state, "reviewed")
        self.assertEqual(alert.reviewed_by_id, self.env.user)
        self.assertTrue(alert.reviewed_at)

    def test_alerts_are_ordered_most_recent_first(self):
        first = self.Mixin._raise_anomaly(
            alert_type="other", name="First", reason="r"
        )
        second = self.Mixin._raise_anomaly(
            alert_type="other", name="Second", reason="r"
        )
        found = self.Alert.search([("id", "in", (first | second).ids)])
        self.assertEqual(found[0], second)
