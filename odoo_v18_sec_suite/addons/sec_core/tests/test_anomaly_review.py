# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for the anomaly triage trail (P3-3, US-7.1 third criterion)."""

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAnomalyReview(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Alert = cls.env["anomaly.alert"]
        cls.Review = cls.env["anomaly.review"]

    def _alert(self, severity="medium"):
        return self.Alert.sudo().create(
            {
                "alert_type": "other",
                "name": "Test alert",
                "reason": "Testing triage.",
                "severity": severity,
            }
        )

    # --- Note remains mandatory --------------------------------------------
    def test_review_without_a_note_is_refused(self):
        alert = self._alert()
        with self.assertRaises(UserError):
            alert.action_mark_reviewed(note="   ")

    def test_review_with_a_note_succeeds(self):
        alert = self._alert()
        alert.action_mark_reviewed(note="Checked with the user; expected work.")
        self.assertEqual(alert.state, "reviewed")

    # --- The half that was missing: the review is logged -------------------
    def test_review_writes_an_append_only_record(self):
        alert = self._alert()
        alert.action_mark_reviewed(
            outcome="explained", note="Spoke to the accounts clerk."
        )
        self.assertEqual(len(alert.review_ids), 1)
        review = alert.review_ids[0]
        self.assertEqual(review.reviewer_id, self.env.user)
        self.assertEqual(review.outcome, "explained")
        self.assertEqual(review.state_before, "new")
        self.assertEqual(review.state_after, "reviewed")
        self.assertTrue(review.reviewed_at)

    def test_review_records_cannot_be_edited(self):
        alert = self._alert()
        alert.action_mark_reviewed(note="Benign.")
        with self.assertRaises(UserError):
            alert.review_ids[0].write({"note": "Rewritten later."})

    def test_review_records_cannot_be_deleted(self):
        alert = self._alert()
        alert.action_mark_reviewed(note="Benign.")
        with self.assertRaises(UserError):
            alert.review_ids[0].unlink()

    def test_review_reaches_the_locker(self):
        if "audit.locker.entry" not in self.env:
            self.skipTest("sec_audit_locker not installed")
        alert = self._alert()
        alert.action_mark_reviewed(note="Checked and closed.")
        entry = self.env["audit.locker.entry"].sudo().search(
            [("model_name", "=", "anomaly.alert"), ("res_id", "=", alert.id)],
            limit=1,
        )
        self.assertTrue(entry, "Triage decision did not reach the Locker")
        self.assertIn("triage", entry.field_changes)

    # --- Double review and reopening ---------------------------------------
    def test_cannot_review_twice_without_reopening(self):
        alert = self._alert()
        alert.action_mark_reviewed(note="First conclusion.")
        with self.assertRaises(UserError):
            alert.action_mark_reviewed(note="Second conclusion.")

    def test_reopening_requires_a_note(self):
        alert = self._alert()
        alert.action_mark_reviewed(note="Benign.")
        with self.assertRaises(UserError):
            alert.action_reopen()

    def test_reopening_is_itself_logged(self):
        alert = self._alert()
        alert.action_mark_reviewed(note="Benign.")
        alert.action_reopen(note="New information from the vendor.")
        self.assertEqual(alert.state, "new")
        self.assertEqual(len(alert.review_ids), 2)
        self.assertEqual(alert.reopened_count, 1)

    def test_reopened_alert_can_be_reviewed_again(self):
        alert = self._alert()
        alert.action_mark_reviewed(note="Benign.")
        alert.action_reopen(note="Reconsidering.")
        alert.action_mark_reviewed(
            outcome="action_taken", note="Escalated to the vendor and resolved."
        )
        self.assertEqual(alert.state, "reviewed")
        self.assertEqual(alert.review_count, 3)

    def test_cannot_reopen_an_open_alert(self):
        alert = self._alert()
        with self.assertRaises(UserError):
            alert.action_reopen(note="x")

    # --- Escalation ---------------------------------------------------------
    def test_escalation_requires_a_note(self):
        alert = self._alert()
        with self.assertRaises(UserError):
            alert.action_escalate()

    def test_escalation_is_logged_and_changes_state(self):
        alert = self._alert(severity="critical")
        alert.action_escalate(note="Needs a decision from the owner.")
        self.assertEqual(alert.state, "escalated")
        self.assertEqual(alert.review_ids[0].outcome, "escalated")

    # --- Reporting ----------------------------------------------------------
    def test_activity_report_counts_by_reviewer_and_outcome(self):
        self._alert().action_mark_reviewed(outcome="benign", note="a")
        self._alert().action_mark_reviewed(outcome="explained", note="b")
        report = self.Alert.review_activity_report(days=30)
        self.assertGreaterEqual(report["reviews"], 2)
        self.assertIn(self.env.user.login, report["by_reviewer"])
        self.assertIn("benign", report["by_outcome"])

    def test_activity_report_counts_open_high_severity(self):
        self._alert(severity="critical")
        report = self.Alert.review_activity_report()
        self.assertGreaterEqual(report["open_high_severity"], 1)

    def test_bulk_flag_is_recorded(self):
        alert = self._alert()
        alert.action_mark_reviewed(note="Batch of routine alerts.", bulk=True)
        self.assertTrue(alert.review_ids[0].bulk)
