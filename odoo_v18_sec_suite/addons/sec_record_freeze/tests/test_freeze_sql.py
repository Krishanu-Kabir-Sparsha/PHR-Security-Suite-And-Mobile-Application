# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for database-level freeze enforcement (PRD US-3.1, second criterion).

These bypass the ORM entirely and go at the tables with raw SQL, which is the
only way to test a control whose whole purpose is to survive an ORM bypass.

Every statement expected to fail is wrapped in a savepoint: a raised SQL error
aborts the surrounding transaction, and without a savepoint the rest of the
test class would fail with InternalError instead of reporting the real result.
"""

import psycopg2

from odoo.tests.common import TransactionCase, tagged

from ..models.freeze_sql import GUARD_FUNCTION, TRIGGER_PREFIX, UNLOCK_GUC


@tagged("post_install", "-at_install")
class TestFreezeSql(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Rule = cls.env["sec.freeze.rule"]
        cls.partner = cls.env["res.partner"].create({"name": "SQL Freeze Customer"})
        cls.other_partner = cls.env["res.partner"].create({"name": "SQL Other"})
        cls.product = cls.env["product.product"].create(
            {"name": "SQL Freeze Product", "list_price": 100.0}
        )
        # Triggers are installed by post_init_hook; make sure this database has
        # them regardless of how the test database was built.
        cls.Rule.sync_all_triggers()

    def _confirmed_order(self):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "order_line": [
                    (0, 0, {
                        "product_id": self.product.id,
                        "product_uom_qty": 1,
                        "price_unit": 100.0,
                    })
                ],
            }
        )
        order.action_confirm()
        self.env.flush_all()
        return order

    # --- Objects exist -----------------------------------------------------
    def test_guard_function_exists(self):
        self.env.cr.execute(
            "SELECT 1 FROM pg_proc WHERE proname = %s", (GUARD_FUNCTION,)
        )
        self.assertTrue(self.env.cr.fetchone())

    def test_triggers_installed_on_in_scope_tables(self):
        self.env.cr.execute(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE %s",
            (TRIGGER_PREFIX + "%",),
        )
        present = {row[0] for row in self.env.cr.fetchall()}
        for table in ("sale_order", "purchase_order", "account_move"):
            self.assertIn(
                TRIGGER_PREFIX + table,
                present,
                "No freeze trigger on %s" % table,
            )

    def test_verify_triggers_reports_healthy(self):
        report = self.Rule.verify_triggers()
        self.assertTrue(report["healthy"], "Missing: %s" % report["missing"])

    # --- The actual point: raw SQL is refused ------------------------------
    def test_raw_sql_update_of_protected_column_blocked(self):
        order = self._confirmed_order()
        with self.assertRaises(psycopg2.errors.CheckViolation):
            with self.env.cr.savepoint(flush=False):
                self.env.cr.execute(
                    "UPDATE sale_order SET partner_id = %s WHERE id = %s",
                    (self.other_partner.id, order.id),
                )

    def test_raw_sql_update_of_amount_blocked(self):
        order = self._confirmed_order()
        with self.assertRaises(psycopg2.errors.CheckViolation):
            with self.env.cr.savepoint(flush=False):
                self.env.cr.execute(
                    "UPDATE sale_order SET amount_total = 1.0 WHERE id = %s",
                    (order.id,),
                )

    def test_raw_sql_delete_of_frozen_row_blocked(self):
        order = self._confirmed_order()
        with self.assertRaises(psycopg2.errors.CheckViolation):
            with self.env.cr.savepoint(flush=False):
                self.env.cr.execute(
                    "DELETE FROM sale_order WHERE id = %s", (order.id,)
                )

    def test_raw_sql_update_of_line_blocked_via_parent_state(self):
        """Line tables resolve their frozen state from the parent document."""
        order = self._confirmed_order()
        line_id = order.order_line[0].id
        with self.assertRaises(psycopg2.errors.CheckViolation):
            with self.env.cr.savepoint(flush=False):
                self.env.cr.execute(
                    "UPDATE sale_order_line SET price_unit = 1.0 WHERE id = %s",
                    (line_id,),
                )

    # --- False positives would break the ERP; check they do not occur ------
    def test_draft_order_unaffected_by_trigger(self):
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE sale_order SET partner_id = %s WHERE id = %s",
            (self.other_partner.id, order.id),
        )

    def test_unprotected_column_still_writable_when_frozen(self):
        order = self._confirmed_order()
        self.env.cr.execute(
            "UPDATE sale_order SET note = %s WHERE id = %s",
            ("dispatch note", order.id),
        )

    def test_no_op_write_of_protected_column_allowed(self):
        """A recompute rewriting an unchanged value must not be refused."""
        order = self._confirmed_order()
        self.env.cr.execute(
            "UPDATE sale_order SET partner_id = %s WHERE id = %s",
            (self.partner.id, order.id),
        )

    def test_confirmation_write_itself_is_allowed(self):
        """OLD.state is still draft during the confirming write."""
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "order_line": [
                    (0, 0, {
                        "product_id": self.product.id,
                        "product_uom_qty": 1,
                        "price_unit": 100.0,
                    })
                ],
            }
        )
        order.action_confirm()
        self.assertEqual(order.state, "sale")

    # --- The unlock path P2-8 will use -------------------------------------
    def test_transaction_scoped_unlock_permits_the_write(self):
        order = self._confirmed_order()
        self.env.cr.execute("SET LOCAL %s = 'granted'" % UNLOCK_GUC)
        self.env.cr.execute(
            "UPDATE sale_order SET partner_id = %s WHERE id = %s",
            (self.other_partner.id, order.id),
        )
        self.env.cr.execute("SET LOCAL %s = ''" % UNLOCK_GUC)

    def test_unlock_does_not_persist_beyond_the_setting(self):
        order = self._confirmed_order()
        self.env.cr.execute("SET LOCAL %s = ''" % UNLOCK_GUC)
        with self.assertRaises(psycopg2.errors.CheckViolation):
            with self.env.cr.savepoint(flush=False):
                self.env.cr.execute(
                    "UPDATE sale_order SET partner_id = %s WHERE id = %s",
                    (self.other_partner.id, order.id),
                )

    # --- Configuration drives the triggers ---------------------------------
    def test_guardable_columns_exclude_one2many_fields(self):
        rule = self.Rule.search([("model_name", "=", "sale.order")], limit=1)
        columns = rule._guardable_columns()
        self.assertIn("partner_id", columns)
        self.assertNotIn("order_line", columns)

    def test_disabling_enforcement_drops_the_trigger(self):
        rule = self.Rule.search([("model_name", "=", "sale.order")], limit=1)
        rule.enforcement_active = False
        self.env.cr.execute(
            "SELECT 1 FROM pg_trigger WHERE NOT tgisinternal AND tgname = %s",
            (TRIGGER_PREFIX + "sale_order",),
        )
        self.assertFalse(self.env.cr.fetchone())
        rule.enforcement_active = True
        self.env.cr.execute(
            "SELECT 1 FROM pg_trigger WHERE NOT tgisinternal AND tgname = %s",
            (TRIGGER_PREFIX + "sale_order",),
        )
        self.assertTrue(self.env.cr.fetchone())

    def test_missing_trigger_is_reported_and_alerts(self):
        """A dropped trigger is a deliberate act and must surface as critical."""
        self.env.cr.execute(
            "DROP TRIGGER IF EXISTS %ssale_order ON sale_order" % TRIGGER_PREFIX
        )
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        report = self.Rule.verify_triggers()
        self.assertFalse(report["healthy"])
        self.assertIn(TRIGGER_PREFIX + "sale_order", report["missing"])
        self.assertGreater(Alert.search_count([]), before)
        self.Rule.sync_all_triggers()
