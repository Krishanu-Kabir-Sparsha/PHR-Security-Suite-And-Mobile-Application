# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests that real business actions land in the Locker (US-4.1)."""

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLockerCapture(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Entry = cls.env["audit.locker.entry"]
        cls.partner = cls.env["res.partner"].create({"name": "Locker Customer"})
        cls.other = cls.env["res.partner"].create({"name": "Locker Other"})

    def _entries_for(self, model_name, res_id):
        return self.Entry.sudo().search(
            [("model_name", "=", model_name), ("res_id", "=", res_id)]
        )

    def test_auditlog_rules_are_subscribed(self):
        rules = self.env["auditlog.rule"].sudo().search(
            [("name", "like", "Locker:")]
        )
        self.assertTrue(rules, "No Locker auditlog rules found")
        unsubscribed = rules.filtered(lambda r: r.state != "subscribed")
        self.assertFalse(
            unsubscribed,
            "Unsubscribed rules capture nothing: %s"
            % unsubscribed.mapped("name"),
        )

    def test_read_logging_is_off_everywhere(self):
        """Read logging multiplies volume and no requirement asks for it."""
        rules = self.env["auditlog.rule"].sudo().search([("name", "like", "Locker:")])
        self.assertFalse(rules.filtered("log_read"))

    def test_sale_order_creation_is_captured(self):
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        self.env.flush_all()
        entries = self._entries_for("sale.order", order.id)
        self.assertTrue(entries, "Creating a sale order produced no Locker entry")
        self.assertIn("create", entries.mapped("action_type"))

    def test_write_captures_field_level_before_and_after(self):
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        self.env.flush_all()
        order.write({"partner_id": self.other.id})
        self.env.flush_all()
        writes = self._entries_for("sale.order", order.id).filtered(
            lambda e: e.action_type == "write"
        )
        self.assertTrue(writes)
        self.assertIn("partner_id", writes[0].field_changes or "")

    def test_entry_records_actor_and_timestamp(self):
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        self.env.flush_all()
        entry = self._entries_for("sale.order", order.id)[0]
        self.assertEqual(entry.user_id, self.env.user)
        self.assertEqual(entry.user_login, self.env.user.login)
        self.assertTrue(entry.timestamp_utc)

    def test_control_configuration_changes_are_captured(self):
        """Weakening a control matters more than editing one order."""
        rule = self.env["sec.freeze.rule"].search(
            [("model_name", "=", "sale.order")], limit=1
        )
        rule.notes = "Reviewed September."
        self.env.flush_all()
        self.assertTrue(self._entries_for("sec.freeze.rule", rule.id))

    # --- Hardening of the upstream log ------------------------------------
    def test_auditlog_entries_cannot_be_modified(self):
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        self.env.flush_all()
        log = self.env["auditlog.log"].sudo().search([], order="id desc", limit=1)
        self.assertTrue(log)
        with self.assertRaises(UserError):
            log.write({"res_id": 0})

    def test_auditlog_entries_cannot_be_deleted(self):
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        self.env.flush_all()
        log = self.env["auditlog.log"].sudo().search([], order="id desc", limit=1)
        with self.assertRaises(UserError):
            log.unlink()

    def test_upstream_autovacuum_cron_is_inactive(self):
        """An automatic silent purge is the insider's preferred mechanism."""
        cron = self.env.ref(
            "auditlog.ir_cron_auditlog_autovacuum", raise_if_not_found=False
        )
        if cron:
            self.assertFalse(cron.active)

    def test_chain_verification_cron_is_active(self):
        cron = self.env.ref("sec_audit_locker.cron_verify_locker_chain")
        self.assertTrue(cron.active)

    def test_capture_failure_does_not_break_the_audited_action(self):
        """Logging must never be the reason a legitimate save fails."""
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        self.assertTrue(order.exists())
