# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for Written/Oral classification and its documentation gate.

Covers PRD US-1.2 and US-1.3, and BRD FR-1.2 / FR-1.3 / FR-1.4.
"""

import base64

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestInstructionDocumentation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Request = cls.env["sec.edit.request"]
        cls.Alert = cls.env["anomaly.alert"]
        cls.supervisor = cls.env["res.users"].create(
            {"name": "Instructing Supervisor", "login": "instr_super"}
        )

    def _attachment(self, name="voice_note.ogg"):
        return self.env["ir.attachment"].create(
            {"name": name, "datas": base64.b64encode(b"evidence")}
        )

    def _request(self, **kwargs):
        vals = {
            "name": "Correct mis-entered amount",
            "justification": "Amount was keyed as 10,000 instead of 1,000.",
        }
        vals.update(kwargs)
        return self.Request.create(vals)

    # --- AC: instruction type is mandatory ---------------------------------
    def test_instruction_type_is_required(self):
        with self.assertRaises(Exception):
            self.Request.create(
                {"name": "No type", "justification": "Missing classification."}
            )

    # --- AC: oral requires an attachment -----------------------------------
    def test_oral_without_attachment_is_incomplete(self):
        request_record = self._request(
            instruction_type="oral", instructing_person_id=self.supervisor.id
        )
        self.assertFalse(request_record.documentation_complete)

    def test_oral_without_instructing_person_is_incomplete(self):
        request_record = self._request(
            instruction_type="oral",
            attachment_ids=[(4, self._attachment().id)],
        )
        self.assertFalse(request_record.documentation_complete)

    def test_oral_with_attachment_and_supervisor_is_complete(self):
        request_record = self._request(
            instruction_type="oral",
            instructing_person_id=self.supervisor.id,
            attachment_ids=[(4, self._attachment().id)],
        )
        self.assertTrue(request_record.documentation_complete)

    def test_written_requires_the_written_document(self):
        request_record = self._request(instruction_type="written")
        self.assertFalse(request_record.documentation_complete)
        request_record.attachment_ids = [(4, self._attachment("memo.pdf").id)]
        self.assertTrue(request_record.documentation_complete)

    # --- AC: re-validated server-side --------------------------------------
    def test_submission_blocked_when_documentation_missing(self):
        request_record = self._request(instruction_type="oral")
        with self.assertRaises(ValidationError):
            request_record.action_submit()
        self.assertEqual(request_record.state, "draft")

    def test_submission_succeeds_when_documentation_present(self):
        request_record = self._request(
            instruction_type="oral",
            instructing_person_id=self.supervisor.id,
            attachment_ids=[(4, self._attachment().id)],
        )
        request_record.action_submit()
        self.assertEqual(request_record.state, "submitted")
        self.assertTrue(request_record.submitted_at)

    # --- AC (US-1.3): blocked attempt raises an anomaly alert --------------
    def test_blocked_submission_raises_anomaly_alert(self):
        """The alert must survive the rollback of the blocked transaction.

        It is written on a separate cursor, so it is queried here on a fresh
        one rather than through self.env.
        """
        before = self.Alert.sudo().search_count(
            [("alert_type", "=", "missing_documentation")]
        )
        request_record = self._request(instruction_type="oral")
        with self.assertRaises(ValidationError):
            request_record.action_submit()
        after = self.Alert.sudo().search_count(
            [("alert_type", "=", "missing_documentation")]
        )
        self.assertGreater(
            after,
            before,
            "A blocked submission must raise a missing-documentation anomaly "
            "that survives the rollback (BRD FR-1.4).",
        )

    def test_alert_records_user_and_reason(self):
        request_record = self._request(instruction_type="oral")
        with self.assertRaises(ValidationError):
            request_record.action_submit()
        alert = self.Alert.sudo().search(
            [("alert_type", "=", "missing_documentation")],
            order="id desc",
            limit=1,
        )
        self.assertTrue(alert)
        self.assertEqual(alert.user_id, self.env.user)
        self.assertEqual(alert.severity, "high")
        self.assertIn("supporting documentation", alert.reason)

    def test_only_draft_requests_can_be_submitted(self):
        request_record = self._request(
            instruction_type="written",
            attachment_ids=[(4, self._attachment("memo.pdf").id)],
        )
        request_record.action_submit()
        with self.assertRaises(ValidationError):
            request_record.action_submit()
