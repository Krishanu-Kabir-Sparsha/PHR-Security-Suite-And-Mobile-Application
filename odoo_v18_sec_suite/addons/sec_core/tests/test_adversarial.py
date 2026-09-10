# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Adversarial tests for the anomaly trail (P4-4)."""

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAnomalyAdversarial(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Alert = cls.env["anomaly.alert"]

    def _alert(self):
        return self.Alert.sudo().create(
            {
                "alert_type": "other",
                "name": "Inconvenient finding",
                "reason": "Something worth investigating.",
                "severity": "critical",
            }
        )

    # --- FINDING 3 (P4-4): closing an alert without recording why ----------
    def test_cannot_mark_reviewed_by_writing_the_state(self):
        """This worked before the adversarial review.

        The review trail was mandatory only if you used the button.
        """
        alert = self._alert()
        with self.assertRaises(UserError):
            alert.write({"state": "reviewed"})
        self.assertEqual(alert.state, "new")
        self.assertFalse(alert.review_ids)

    def test_cannot_backdate_the_reviewer(self):
        alert = self._alert()
        with self.assertRaises(UserError):
            alert.write({"reviewed_by_id": self.env.user.id})

    def test_cannot_delete_an_alert(self):
        alert = self._alert()
        with self.assertRaises(UserError):
            alert.unlink()

    def test_cannot_delete_an_alert_by_sudo(self):
        alert = self._alert()
        with self.assertRaises(UserError):
            alert.sudo().unlink()

    def test_the_supported_route_still_works_and_logs(self):
        alert = self._alert()
        alert.action_mark_reviewed(
            outcome="explained", note="Checked with the actor; expected."
        )
        self.assertEqual(alert.state, "reviewed")
        self.assertEqual(len(alert.review_ids), 1)

    def test_non_triage_fields_remain_writable(self):
        """The guard must not freeze the whole record."""
        alert = self._alert()
        alert.write({"review_note": "Working note before deciding."})
        self.assertIn("Working note", alert.review_note)
