# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for the bounded Plaza Model role catalog (PRD US-2.1)."""

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged

from ..models.plaza_role import MAX_ACTIVE_ROLES, MIN_ACTIVE_ROLES


@tagged("post_install", "-at_install")
class TestPlazaRoleCatalog(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Role = cls.env["role.plaza_model"]
        cls.Access = cls.env["role.plaza_model.access"]

    def _make_role(self, code, **kwargs):
        vals = {
            "code": code,
            "name": kwargs.pop("name", code.title()),
            "description": kwargs.pop("description", "Test role %s." % code),
        }
        vals.update(kwargs)
        return self.Role.create(vals)

    # --- AC: bounded catalog, min 10 / max 20 active roles -----------------
    def test_seed_catalog_is_within_bounds(self):
        """The shipped catalog satisfies the 10-20 active role bound."""
        count = self.Role.search_count([("active", "=", True)])
        self.assertGreaterEqual(count, MIN_ACTIVE_ROLES)
        self.assertLessEqual(count, MAX_ACTIVE_ROLES)

    def test_cannot_exceed_maximum_active_roles(self):
        """Creating past the ceiling raises rather than silently growing."""
        existing = self.Role.search_count([("active", "=", True)])
        headroom = MAX_ACTIVE_ROLES - existing
        for i in range(headroom):
            self._make_role("FILLER_%d" % i)
        with self.assertRaises(ValidationError):
            self._make_role("ONE_TOO_MANY")

    def test_archiving_frees_a_catalog_slot(self):
        """The bound counts active roles only."""
        existing = self.Role.search_count([("active", "=", True)])
        headroom = MAX_ACTIVE_ROLES - existing
        fillers = self.Role
        for i in range(headroom):
            fillers |= self._make_role("FILLER_%d" % i)
        fillers[0].active = False
        # A slot is now free, so this must succeed.
        self._make_role("REPLACEMENT")

    # --- AC: required description per role ---------------------------------
    def test_description_is_mandatory(self):
        with self.assertRaises(Exception):
            self.Role.create({"code": "NODESC", "name": "No Description"})

    def test_whitespace_only_description_rejected(self):
        with self.assertRaises(ValidationError):
            self._make_role("BLANKDESC", description="   \n  ")

    def test_role_code_is_unique(self):
        self._make_role("DUPE")
        with self.assertRaises(Exception):
            self._make_role("DUPE")

    # --- AC: explicit module + field-level access matrix -------------------
    def test_access_matrix_line_records_module_and_fields(self):
        role = self._make_role("MATRIX")
        line = self.Access.create(
            {
                "role_id": role.id,
                "module_label": "Sales",
                "model_name": "sale.order",
                "perm_read": True,
                "perm_create": True,
                "transaction_type": "sale_order",
                "capability": "create",
                "field_restrictions": "margin_percent",
            }
        )
        self.assertEqual(role.access_line_count, 1)
        self.assertEqual(line.field_restrictions, "margin_percent")

    def test_same_model_twice_on_one_role_rejected(self):
        role = self._make_role("DUPMODEL")
        base = {
            "role_id": role.id,
            "module_label": "Sales",
            "model_name": "sale.order",
        }
        self.Access.create(base)
        with self.assertRaises(Exception):
            self.Access.create(dict(base))

    def test_capability_requires_transaction_type(self):
        role = self._make_role("NOTXN")
        with self.assertRaises(ValidationError):
            self.Access.create(
                {
                    "role_id": role.id,
                    "module_label": "Sales",
                    "model_name": "sale.order",
                    "capability": "create",
                }
            )

    def test_single_role_cannot_create_and_approve(self):
        """Intra-role SoD breach is impossible to author (BRD FR-2.4)."""
        role = self._make_role("BOTHCAPS")
        with self.assertRaises(ValidationError):
            self.Access.create(
                {
                    "role_id": role.id,
                    "module_label": "Accounting",
                    "model_name": "account.payment",
                    "transaction_type": "vendor_payment",
                    "capability": "create_approve",
                }
            )

    # --- Nuclear Key uniqueness -------------------------------------------
    def test_only_one_nuclear_key_role(self):
        with self.assertRaises(ValidationError):
            self._make_role("SECOND_CEO", is_approval_tier="tier_3")

    def test_approval_tier_role_requires_webauthn(self):
        role = self.Role.search([("is_approval_tier", "=", "tier_3")], limit=1)
        self.assertTrue(role.requires_webauthn)
        plain = self._make_role("PLAIN")
        self.assertFalse(plain.requires_webauthn)

    # --- Readiness ---------------------------------------------------------
    def test_seed_catalog_is_go_live_ready(self):
        verdict = self.Role.check_catalog_readiness()
        self.assertTrue(
            verdict["ready"],
            "Seed catalog is not go-live ready: %s" % verdict["findings"],
        )

    def test_readiness_flags_role_without_group(self):
        self._make_role("NOGROUP")
        verdict = self.Role.check_catalog_readiness()
        self.assertFalse(verdict["ready"])
        self.assertTrue(
            any("no backing security group" in f for f in verdict["findings"])
        )
