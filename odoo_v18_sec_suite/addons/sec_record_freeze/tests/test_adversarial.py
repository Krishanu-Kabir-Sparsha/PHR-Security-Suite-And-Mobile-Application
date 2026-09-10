# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Adversarial tests (P4-4).

Written by attacking the claims rather than by re-reading the code that makes
them. Each test here corresponds to a specific way somebody might try to change
a confirmed record, including the three routes that actually worked before this
review.
"""

import psycopg2

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestFreezeAdversarial(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Adversary Co"})
        cls.other = cls.env["res.partner"].create({"name": "Other Co"})
        cls.product = cls.env["product.product"].create(
            {"name": "Adversary Product", "list_price": 100.0}
        )

    def _confirmed(self):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "order_line": [
                    (0, 0, {"product_id": self.product.id,
                            "product_uom_qty": 1, "price_unit": 100.0})
                ],
            }
        )
        order.action_confirm()
        return order

    # --- FINDING 1 (P4-4): adding a line to a frozen document ---------------
    def test_cannot_add_a_line_to_a_confirmed_order(self):
        """This worked before the adversarial review.

        Editing the order's total was blocked; creating a line against the same
        order was not, and the total recomputes either way.
        """
        order = self._confirmed()
        before = order.amount_total
        with self.assertRaises(UserError):
            self.env["sale.order.line"].create(
                {
                    "order_id": order.id,
                    "product_id": self.product.id,
                    "product_uom_qty": 5,
                    "price_unit": 1000.0,
                }
            )
        order.invalidate_recordset()
        self.assertEqual(order.amount_total, before)

    def test_cannot_add_a_line_by_sudo(self):
        order = self._confirmed()
        with self.assertRaises(UserError):
            self.env["sale.order.line"].sudo().create(
                {
                    "order_id": order.id,
                    "product_id": self.product.id,
                    "product_uom_qty": 1,
                    "price_unit": 50.0,
                }
            )

    def test_adding_a_line_raises_a_critical_anomaly(self):
        order = self._confirmed()
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        with self.assertRaises(UserError):
            self.env["sale.order.line"].create(
                {"order_id": order.id, "product_id": self.product.id,
                 "product_uom_qty": 1, "price_unit": 1.0}
            )
        self.assertGreater(Alert.search_count([]), before)

    def test_cannot_add_a_line_by_raw_sql(self):
        """The database trigger had the same gap: it fired on UPDATE and
        DELETE only."""
        order = self._confirmed()
        self.env.flush_all()
        template = order.order_line[0]
        with self.assertRaises(psycopg2.errors.CheckViolation):
            with self.env.cr.savepoint(flush=False):
                self.env.cr.execute(
                    "INSERT INTO sale_order_line "
                    "(order_id, product_id, product_uom_qty, price_unit, "
                    " name, company_id, create_uid, write_uid, create_date, "
                    " write_date, state) "
                    "SELECT order_id, product_id, product_uom_qty, 999.0, name, "
                    "company_id, create_uid, write_uid, create_date, "
                    "write_date, state FROM sale_order_line WHERE id = %s",
                    (template.id,),
                )

    def test_lines_can_still_be_added_to_a_draft_order(self):
        """The fix must not break ordinary work."""
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        self.env["sale.order.line"].create(
            {"order_id": order.id, "product_id": self.product.id,
             "product_uom_qty": 2, "price_unit": 10.0}
        )
        self.assertEqual(len(order.order_line), 1)

    def test_confirming_an_order_still_works(self):
        order = self._confirmed()
        self.assertEqual(order.state, "sale")

    # --- Previously-claimed defences, re-attacked --------------------------
    def test_sudo_still_cannot_edit_a_protected_field(self):
        order = self._confirmed()
        with self.assertRaises(UserError):
            order.sudo().write({"partner_id": self.other.id})

    def test_superuser_still_cannot_edit(self):
        order = self._confirmed()
        with self.assertRaises(UserError):
            order.with_user(self.env.ref("base.user_root")).write(
                {"partner_id": self.other.id}
            )

    def test_fabricated_unlock_ticket_authorises_nothing(self):
        order = self._confirmed()
        with self.assertRaises(UserError):
            order.with_context(sec_freeze_unlock_ticket=99999999).write(
                {"partner_id": self.other.id}
            )

    def test_ticket_for_another_field_does_not_widen(self):
        order = self._confirmed()
        ticket = self.env["sec.freeze.unlock.ticket"].issue(
            order, ["client_order_ref"], "override.request,0"
        )
        with self.assertRaises(UserError):
            order.with_context(
                sec_freeze_unlock_ticket=ticket.id
            ).write({"partner_id": self.other.id,
                     "client_order_ref": "allowed"})

    def test_deleting_a_line_of_a_frozen_order_is_refused(self):
        order = self._confirmed()
        with self.assertRaises(UserError):
            order.order_line[0].unlink()
