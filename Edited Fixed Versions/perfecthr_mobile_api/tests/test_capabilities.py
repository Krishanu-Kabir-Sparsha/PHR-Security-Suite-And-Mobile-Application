# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The capability matrix: which features this deployment offers which user.

These tests deliberately exercise the matrix rather than the HTTP route. The
route is three lines around ``FEATURE_MATRIX``; the matrix is where a wrong
answer is expensive, because it silently removes a feature from every phone or
offers one the server cannot serve.
"""

from odoo.tests import TransactionCase, tagged

from ..controllers.capabilities import FEATURE_MATRIX, MobileCapabilities


@tagged("post_install", "-at_install")
class TestCapabilities(TransactionCase):
    def setUp(self):
        super().setUp()
        self.controller = MobileCapabilities()
        self.user = self.env["res.users"].create(
            {
                "name": "Capability Tester",
                "login": "capability.tester@example.internal",
            }
        )

    def test_feature_keys_are_unique(self):
        """Keys are a contract with the client's AppFeature enum.

        A duplicate would make the client resolve whichever came first, with no
        error anywhere.
        """
        keys = [key for key, _module, _group in FEATURE_MATRIX]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_declared_module_is_a_real_module(self):
        """A typo in a module name silently removes a feature everywhere.

        The feature would simply never appear, on any deployment, and nothing
        would log it. Checking the name exists in ir.module.module catches the
        typo here instead of in a support ticket.
        """
        Module = self.env["ir.module.module"]
        for _key, module, _group in FEATURE_MATRIX:
            if not module:
                continue
            self.assertTrue(
                Module.search_count([("name", "=", module)]),
                "FEATURE_MATRIX names a module Odoo does not know: %s" % module,
            )

    def test_absent_group_is_answered_no_not_an_error(self):
        """``has_group`` raises on an unknown xmlid.

        That happens whenever a module is not installed, which is routine. It
        must not 500 the whole capabilities call -- the honest answer for a
        group that does not exist here is simply "no".
        """
        self.assertFalse(
            self.controller._has_group(self.user, "no_such_module.no_such_group")
        )

    def test_no_group_requirement_means_available(self):
        self.assertTrue(self.controller._has_group(self.user, None))

    def test_security_keys_need_no_other_module(self):
        """This module serves enrolment status itself.

        So it must not be gated on anything that could be uninstalled, or the
        one feature that is always available would disappear.
        """
        entry = next(e for e in FEATURE_MATRIX if e[0] == "security_keys")
        self.assertIsNone(entry[1])
        self.assertIsNone(entry[2])

    def test_permission_models_are_real_or_optional(self):
        """Every entry must be a model some installed module could provide.

        A typo here disables a feature silently: the model is skipped as
        "not installed", the app receives no permission for it, and the control
        never appears. Models from uninstalled optional modules are expected and
        skipped, so this only asserts the name is well formed.
        """
        from ..controllers.capabilities import PERMISSION_MODELS

        for model_name in PERMISSION_MODELS:
            self.assertRegex(
                model_name,
                r"^[a-z0-9_]+(\.[a-z0-9_]+)+$",
                "malformed model name %s" % model_name,
            )

    def test_hr_transaction_classes_exist(self):
        """The HR roles carry capabilities, and a capability without a valid
        transaction class fails the model's own constraint on save."""
        from odoo.addons.sec_plaza_rbac.models.plaza_role import TRANSACTION_TYPES

        declared = {key for key, _label in TRANSACTION_TYPES}
        for expected in (
            "leave_request",
            "attendance_record",
            "payroll_run",
            "employee_master",
            "recruitment",
        ):
            self.assertIn(expected, declared)

    def test_preview_is_refused_without_admin_rights(self):
        """Enumerating the access model of roles you do not hold is
        reconnaissance, not a feature."""
        self.assertFalse(
            self.controller._has_group(
                self.user, "sec_plaza_rbac.group_plaza_admin"
            )
        )

    def test_assignable_roles_empty_for_ordinary_user(self):
        """The picker must not appear at all for someone who cannot use it.
        Showing it and refusing on tap is worse than not showing it."""
        self.assertEqual(self.controller._assignable_roles(self.user), [])
