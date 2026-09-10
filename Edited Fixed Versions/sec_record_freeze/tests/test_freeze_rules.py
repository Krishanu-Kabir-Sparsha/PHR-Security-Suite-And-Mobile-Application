# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for freeze rule configuration integrity."""

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestFreezeRules(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Rule = cls.env["sec.freeze.rule"]

    def test_all_six_in_scope_models_have_a_rule(self):
        expected = {
            "sale.order",
            "sale.order.line",
            "purchase.order",
            "purchase.order.line",
            "account.move",
            "account.move.line",
        }
        found = set(
            self.Rule.search([("enforcement_active", "=", True)]).mapped("model_name")
        )
        self.assertTrue(
            expected.issubset(found),
            "Missing freeze rules for: %s" % (expected - found),
        )

    def test_rule_with_no_protected_fields_rejected(self):
        with self.assertRaises(ValidationError):
            self.Rule.create(
                {
                    "name": "Empty",
                    "model_name": "res.partner",
                    "frozen_states": "done",
                    "protected_fields": "  ,  ",
                    "stream": "other",
                }
            )

    def test_misspelled_protected_field_rejected(self):
        """A typo protects nothing while appearing configured."""
        with self.assertRaises(ValidationError):
            self.Rule.create(
                {
                    "name": "Typo",
                    "model_name": "sale.order",
                    "frozen_states": "sale",
                    "protected_fields": "partner_idd",
                    "stream": "sales",
                }
            )

    def test_bad_state_path_rejected(self):
        with self.assertRaises(ValidationError):
            self.Rule.create(
                {
                    "name": "Bad path",
                    "model_name": "sale.order",
                    "state_field_path": "not_a_field.state",
                    "frozen_states": "sale",
                    "protected_fields": "partner_id",
                    "stream": "sales",
                }
            )

    def test_one_rule_per_model(self):
        with self.assertRaises(Exception):
            self.Rule.create(
                {
                    "name": "Duplicate",
                    "model_name": "sale.order",
                    "frozen_states": "sale",
                    "protected_fields": "partner_id",
                    "stream": "sales",
                }
            )

    def test_technical_fields_never_protected(self):
        rule = self.Rule.create(
            {
                "name": "Tech",
                "model_name": "res.partner",
                "frozen_states": "x",
                "protected_fields": "name,write_date,message_ids",
                "stream": "other",
            }
        )
        protected = rule.protected_field_set()
        self.assertIn("name", protected)
        self.assertNotIn("write_date", protected)
        self.assertNotIn("message_ids", protected)

    def test_disabling_enforcement_raises_critical_anomaly(self):
        rule = self.Rule.search([("model_name", "=", "sale.order")], limit=1)
        before = self.env["anomaly.alert"].sudo().search_count([])
        rule.enforcement_active = False
        alerts = self.env["anomaly.alert"].sudo().search([], order="id desc", limit=1)
        self.assertGreater(self.env["anomaly.alert"].sudo().search_count([]), before)
        self.assertEqual(alerts.severity, "critical")
