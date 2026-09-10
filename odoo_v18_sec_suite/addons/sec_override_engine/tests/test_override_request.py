# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for the override request (P2-5, US-5.1)."""

import base64

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOverrideRequest(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Request = cls.env["override.request"]
        cls.Category = cls.env["override.reason.category"]
        cls.data_entry = cls.env.ref("sec_override_engine.reason_data_entry_error")
        cls.partner = cls.env["res.partner"].create({"name": "Override Customer"})
        cls.product = cls.env["product.product"].create(
            {"name": "Override Product", "list_price": 100.0}
        )
        cls.supervisor = cls.env["res.users"].create(
            {"name": "Supervisor", "login": "ovr_supervisor"}
        )

    def _confirmed_order(self):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "order_line": [
                    (0, 0, {
                        "product_id": self.product.id,
                        "product_uom_qty": 1,
                        "price_unit": 10000.0,
                    })
                ],
            }
        )
        order.action_confirm()
        return order

    def _attachment(self):
        return self.env["ir.attachment"].create(
            {"name": "source_invoice.pdf", "datas": base64.b64encode(b"evidence")}
        )

    def _request(self, order=None, **kwargs):
        order = order or self._confirmed_order()
        vals = {
            "res_model": "sale.order",
            "res_id": order.id,
            "reason_category_id": self.data_entry.id,
            "justification": "Amount keyed as 10,000; source document says 1,000.",
            "proposed_changes": "order_line[0].price_unit: 10000.00 -> 1000.00",
            "instruction_type": "written",
            "attachment_ids": [(4, self._attachment().id)],
        }
        vals.update(kwargs)
        return self.Request.create(vals)

    # --- Reference and target ---------------------------------------------
    def test_request_gets_a_sequence_reference(self):
        request_record = self._request()
        self.assertNotEqual(request_record.name, "New")
        self.assertIn("OVR/", request_record.name)

    def test_target_display_resolves(self):
        order = self._confirmed_order()
        request_record = self._request(order=order)
        self.assertEqual(request_record.target_display, order.display_name)

    def test_target_must_be_a_freeze_covered_model(self):
        """Otherwise this becomes a general approval workflow."""
        with self.assertRaises(ValidationError):
            self.Request.create(
                {
                    "res_model": "res.partner",
                    "res_id": self.partner.id,
                    "reason_category_id": self.data_entry.id,
                    "justification": "x",
                    "proposed_changes": "x",
                    "instruction_type": "written",
                }
            )

    def test_target_must_exist(self):
        with self.assertRaises(ValidationError):
            self.Request.create(
                {
                    "res_model": "sale.order",
                    "res_id": 999999999,
                    "reason_category_id": self.data_entry.id,
                    "justification": "x",
                    "proposed_changes": "x",
                    "instruction_type": "written",
                }
            )

    # --- AC: recognised policy category required ---------------------------
    def test_category_is_mandatory(self):
        order = self._confirmed_order()
        with self.assertRaises(Exception):
            self.Request.create(
                {
                    "res_model": "sale.order",
                    "res_id": order.id,
                    "justification": "x",
                    "proposed_changes": "x",
                    "instruction_type": "written",
                }
            )

    def test_retired_category_cannot_be_submitted(self):
        category = self.Category.create(
            {
                "name": "Temporary",
                "code": "TEMP",
                "description": "For the test.",
                "requires_attachment": False,
            }
        )
        request_record = self._request(reason_category_id=category.id)
        category.active = False
        with self.assertRaises(UserError):
            request_record.action_submit()

    def test_cannot_retire_every_category(self):
        """Otherwise no override could ever be raised again."""
        with self.assertRaises(ValidationError):
            self.Category.search([]).write({"active": False})

    def test_category_requiring_attachment_is_enforced(self):
        request_record = self._request(attachment_ids=[(5, 0, 0)])
        with self.assertRaises(Exception):
            request_record.action_submit()

    # --- AC: only against a frozen record ----------------------------------
    def test_cannot_submit_against_an_unfrozen_record(self):
        draft = self.env["sale.order"].create({"partner_id": self.partner.id})
        request_record = self._request(res_id=draft.id)
        with self.assertRaises(UserError) as caught:
            request_record.action_submit()
        self.assertIn("not currently frozen", str(caught.exception))

    def test_submit_succeeds_against_a_frozen_record(self):
        request_record = self._request()
        request_record.action_submit()
        self.assertEqual(request_record.state, "pending")
        self.assertTrue(request_record.submitted_at)

    # --- Written/Oral rules are inherited, not reimplemented ---------------
    def test_instruction_mixin_is_inherited(self):
        self.assertIn("instruction_type", self.Request._fields)
        self.assertIn("documentation_complete", self.Request._fields)

    def test_oral_instruction_needs_supervisor_and_attachment(self):
        request_record = self._request(
            instruction_type="oral", attachment_ids=[(5, 0, 0)]
        )
        with self.assertRaises(Exception):
            request_record.action_submit()

    def test_oral_with_full_documentation_submits(self):
        request_record = self._request(
            instruction_type="oral",
            instructing_person_id=self.supervisor.id,
        )
        request_record.action_submit()
        self.assertEqual(request_record.state, "pending")

    # --- Tier wiring -------------------------------------------------------
    def test_three_tier_definitions_exist(self):
        definitions = self.env["tier.definition"].search(
            [("model", "=", "override.request")]
        )
        self.assertEqual(len(definitions), 3)

    def test_tiers_are_sequential_not_parallel(self):
        """The single most losable setting in this module (US-5.2)."""
        definitions = self.env["tier.definition"].search(
            [("model", "=", "override.request")]
        )
        for definition in definitions:
            self.assertTrue(
                definition.approve_sequence,
                "%s would allow parallel approval" % definition.name,
            )
            self.assertFalse(
                definition.approve_sequence_bypass,
                "%s allows a tier to be skipped" % definition.name,
            )

    def test_tier_sequence_order_is_dept_compliance_ceo(self):
        definitions = self.env["tier.definition"].search(
            [("model", "=", "override.request")], order="sequence"
        )
        self.assertIn("Department Head", definitions[0].name)
        self.assertIn("Compliance", definitions[1].name)
        self.assertIn("CEO", definitions[2].name)

    def test_submission_creates_reviews(self):
        request_record = self._request()
        request_record.action_submit()
        self.assertTrue(request_record.review_ids)
        self.assertFalse(request_record.validated)

    # --- Immutability while under review -----------------------------------
    def test_justification_locked_once_under_review(self):
        """Tier 3 must approve what Tier 1 saw."""
        request_record = self._request()
        request_record.action_submit()
        with self.assertRaises(Exception):
            request_record.write({"justification": "Something quite different."})

    def test_proposed_changes_locked_once_under_review(self):
        request_record = self._request()
        request_record.action_submit()
        with self.assertRaises(Exception):
            request_record.write({"proposed_changes": "everything"})

    # --- Alerting ----------------------------------------------------------
    def test_submission_raises_an_alert(self):
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        self._request().action_submit()
        self.assertGreater(Alert.search_count([]), before)

    def test_high_risk_category_raises_a_higher_severity(self):
        refund = self.env.ref("sec_override_engine.reason_refund_policy")
        request_record = self._request(reason_category_id=refund.id)
        self.assertTrue(request_record.high_risk)
        request_record.action_submit()
        alert = self.env["anomaly.alert"].sudo().search(
            [], order="id desc", limit=1
        )
        self.assertEqual(alert.severity, "high")

    def test_cancel_is_possible_before_execution(self):
        request_record = self._request()
        request_record.action_submit()
        request_record.action_cancel()
        self.assertEqual(request_record.state, "cancelled")
