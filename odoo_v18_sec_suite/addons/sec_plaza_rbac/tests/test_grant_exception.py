# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for non-standard grant handling (PRD US-2.1, third criterion)."""

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestGrantException(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Exception_ = cls.env["plaza.grant.exception"]
        cls.user = cls.env["res.users"].create(
            {"name": "Grant Test User", "login": "grant_test_user"}
        )
        # A group that is deliberately outside the Plaza catalog.
        cls.rogue_group = cls.env["res.groups"].create({"name": "Rogue Group"})
        cls.catalog_group = cls.env.ref("sec_plaza_rbac.role_sales_exec").group_id

    def test_catalog_role_grant_is_allowed(self):
        self.user.write({"groups_id": [(4, self.catalog_group.id)]})
        self.assertIn(self.catalog_group, self.user.groups_id)

    def test_nonstandard_grant_blocked_without_exception(self):
        with self.assertRaises(ValidationError):
            self.user.write({"groups_id": [(4, self.rogue_group.id)]})

    def test_nonstandard_grant_allowed_with_approved_exception(self):
        exception = self.Exception_.create(
            {
                "user_id": self.user.id,
                "group_id": self.rogue_group.id,
                "justification": "Temporary access for the FY26 migration cutover.",
            }
        )
        exception.action_approve()
        self.user.write({"groups_id": [(4, self.rogue_group.id)]})
        self.assertIn(self.rogue_group, self.user.groups_id)

    def test_draft_exception_does_not_authorise_grant(self):
        self.Exception_.create(
            {
                "user_id": self.user.id,
                "group_id": self.rogue_group.id,
                "justification": "Pending approval.",
            }
        )
        with self.assertRaises(ValidationError):
            self.user.write({"groups_id": [(4, self.rogue_group.id)]})

    def test_expired_exception_does_not_authorise_grant(self):
        exception = self.Exception_.create(
            {
                "user_id": self.user.id,
                "group_id": self.rogue_group.id,
                "justification": "Expired cover.",
                "expires_on": "2020-01-01",
            }
        )
        exception.action_approve()
        with self.assertRaises(ValidationError):
            self.user.write({"groups_id": [(4, self.rogue_group.id)]})

    def test_exception_is_flagged_for_monthly_audit(self):
        exception = self.Exception_.create(
            {
                "user_id": self.user.id,
                "group_id": self.rogue_group.id,
                "justification": "Audited by design.",
            }
        )
        self.assertTrue(exception.flagged_for_audit)

    def test_justification_is_mandatory(self):
        with self.assertRaises(Exception):
            self.Exception_.create(
                {"user_id": self.user.id, "group_id": self.rogue_group.id}
            )

    def test_bypass_context_only_skips_the_check(self):
        self.user.with_context(plaza_bypass_grant_check=True).write(
            {"groups_id": [(4, self.rogue_group.id)]}
        )
        self.assertIn(self.rogue_group, self.user.groups_id)
        self.assertTrue(self.user.has_nonstandard_access)
