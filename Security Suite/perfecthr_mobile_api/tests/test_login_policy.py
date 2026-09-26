# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Company rules and sign-in method: who may sign in where, and how.

The interesting cases are all about a policy NOT being able to weaken
something. A company can offer the basic path; it cannot offer it to an
approver. A refresh can renew a session; it cannot promote one.
"""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLoginPolicy(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Company = self.env["res.company"]
        self.alpha = self.Company.create({"name": "Alpha Ltd"})
        self.beta = self.Company.create({"name": "Beta Ltd"})
        self.user = self.env["res.users"].create(
            {
                "name": "Policy Tester",
                "login": "policy.tester@example.internal",
                "password": "correct-horse-battery-staple",
                "company_id": self.alpha.id,
                "company_ids": [(6, 0, [self.alpha.id])],
            }
        )

    # -- defaults ------------------------------------------------------
    def test_a_new_company_is_advanced_only_and_unpublished(self):
        """Upgrading must not change anybody's behaviour.

        Both defaults matter. A company that silently allowed the basic path on
        upgrade would weaken every existing deployment, and one that silently
        published its name would disclose an org chart nobody asked to publish.
        """
        self.assertEqual(self.alpha.mobile_auth_policy, "advance")
        self.assertFalse(self.alpha.mobile_login_enabled)
        self.assertEqual(self.alpha._mobile_auth_modes(), ["advance"])

    def test_auto_checkin_is_on_by_default(self):
        self.assertTrue(self.alpha.mobile_auto_checkin)

    # -- which companies -----------------------------------------------
    def test_login_companies_are_company_ids(self):
        self.assertEqual(self.user._mobile_login_companies(), self.alpha)

        self.user.company_ids = [(4, self.beta.id)]
        self.assertEqual(
            set(self.user._mobile_login_companies().ids),
            {self.alpha.id, self.beta.id},
        )

    def test_archived_companies_are_not_offered(self):
        """Landing in an archived company produces a session about nothing."""
        self.user.company_ids = [(4, self.beta.id)]
        self.beta.active = False
        self.assertEqual(self.user._mobile_login_companies(), self.alpha)

    # -- which method --------------------------------------------------
    def test_choice_policy_offers_both_advance_first(self):
        self.alpha.mobile_auth_policy = "choice"
        self.assertEqual(
            self.user._mobile_auth_modes_for(self.alpha), ["advance", "basic"]
        )

    def test_basic_policy_still_offers_advance(self):
        """The stronger option is never removed, only de-preferred.

        A user who wants to sign in with their fingerprint must always be able
        to, whatever their company has chosen as the default.
        """
        self.alpha.mobile_auth_policy = "basic"
        modes = self.user._mobile_auth_modes_for(self.alpha)
        self.assertEqual(modes[0], "basic")
        self.assertIn("advance", modes)

    def test_system_administrator_cannot_use_basic(self):
        """The account with the most access may not have the weakest sign-in."""
        self.alpha.mobile_auth_policy = "basic"
        self.user.groups_id = [(4, self.env.ref("base.group_system").id)]
        self.assertEqual(self.user._mobile_auth_modes_for(self.alpha), ["advance"])
        self.assertTrue(self.user._mobile_requires_advance())

    def test_approval_tier_role_forces_advance(self):
        """An approver's password-only session is a password-only override.

        Skipped rather than silently passing where sec_plaza_rbac is absent:
        a test that quietly tests nothing is worse than no test.
        """
        if "role.plaza_model" not in self.env:
            self.skipTest("sec_plaza_rbac is not installed")

        role = self.env["role.plaza_model"].create(
            {
                "name": "Test Approver",
                "code": "TEST_APPROVER",
                "description": "Fixture role for the sign-in policy tests.",
                "is_approval_tier": "tier_1",
            }
        )
        self.user.plaza_role_ids = [(4, role.id)]
        self.alpha.mobile_auth_policy = "basic"

        self.assertTrue(self.user._mobile_requires_advance())
        self.assertEqual(self.user._mobile_auth_modes_for(self.alpha), ["advance"])

    # -- what is published ---------------------------------------------
    def test_public_payload_carries_nothing_confidential(self):
        """Read before authentication, so every key here is published."""
        self.alpha.mobile_login_enabled = True
        payload = self.alpha._mobile_public_payload()
        self.assertEqual(
            set(payload),
            {"id", "name", "logo_url", "auth_modes", "auto_checkin"},
        )
