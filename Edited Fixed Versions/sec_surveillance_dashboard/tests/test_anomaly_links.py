# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for evidence links on alerts (P3-1, US-7.1 second criterion)."""

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAnomalyLinks(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Alert = cls.env["anomaly.alert"]
        cls.Locker = cls.env["audit.locker.entry"]
        cls.partner = cls.env["res.partner"].create({"name": "Link Customer"})

    def _alert(self, **kwargs):
        vals = {
            "alert_type": "other",
            "name": "Test alert",
            "reason": "Testing links.",
            "severity": "medium",
        }
        vals.update(kwargs)
        return self.Alert.sudo().create(vals)

    def test_alert_links_to_locker_entries_for_the_same_record(self):
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        self.env.flush_all()
        alert = self._alert(res_model="sale.order", res_id=order.id)
        self.assertGreaterEqual(alert.locker_entry_count, 1)

    def test_alert_links_to_its_source_locker_entry(self):
        entry = self.Locker.append(
            {
                "user_id": self.env.user.id,
                "user_login": self.env.user.login,
                "model_name": "sale.order",
                "res_id": 99,
                "action_type": "write",
            }
        )
        alert = self._alert(source_ref="audit.locker.entry,%s" % entry.id)
        self.assertIn(entry, alert.locker_entry_ids)

    def test_alert_resolves_its_override_request(self):
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        order.action_confirm()
        override = self.env["override.request"].create(
            {
                "res_model": "sale.order",
                "res_id": order.id,
                "reason_category_id": self.env.ref(
                    "sec_override_engine.reason_data_entry_error"
                ).id,
                "justification": "x",
                "proposed_changes": "y",
                "instruction_type": "written",
            }
        )
        alert = self._alert(source_ref="override.request,%s" % override.id)
        self.assertEqual(alert.override_request_id, override)

    def test_malformed_source_ref_does_not_raise(self):
        alert = self._alert(source_ref="this is not a reference")
        self.assertFalse(alert.override_request_id)
        self.assertFalse(alert.locker_entry_ids)

    def test_target_exists_is_false_for_a_deleted_record(self):
        alert = self._alert(res_model="sale.order", res_id=999999999)
        self.assertFalse(alert.target_exists)

    def test_opening_a_missing_target_gives_a_clear_error(self):
        alert = self._alert(res_model="sale.order", res_id=999999999)
        with self.assertRaises(UserError):
            alert.action_open_target()

    def test_open_target_returns_a_form_action(self):
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        alert = self._alert(res_model="sale.order", res_id=order.id)
        action = alert.action_open_target()
        self.assertEqual(action["res_model"], "sale.order")
        self.assertEqual(action["res_id"], order.id)

    def test_dashboard_summary_shape(self):
        self._alert(severity="critical")
        summary = self.Alert.dashboard_summary(hours=24)
        self.assertIn("by_type", summary)
        self.assertGreaterEqual(summary["total"], 1)
        self.assertGreaterEqual(summary["critical"], 1)
        self.assertGreaterEqual(summary["unreviewed"], 1)

    def test_summary_respects_the_period(self):
        summary = self.Alert.dashboard_summary(hours=1)
        self.assertEqual(summary["period_hours"], 1)
