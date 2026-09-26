# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The HR role catalog, and the duty separation it encodes.

HR was outside the segregation-of-duties checker and the monthly review while
finance was inside them, which is backwards: leave approval and payroll
preparation are exactly the duties those controls exist for.

These tests protect the separations rather than the data. A role gaining a
capability it should not have is a control failure that no amount of reading the
XML will reliably catch.
"""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestHrRoleCatalog(TransactionCase):
    def _role(self, xmlid):
        return self.env.ref("sec_plaza_rbac.%s" % xmlid)

    def test_hr_roles_are_present(self):
        for xmlid in (
            "role_hr_employee",
            "role_hr_line_manager",
            "role_hr_officer",
            "role_hr_payroll_officer",
            "role_hr_manager",
            "role_chro",
        ):
            self.assertTrue(self._role(xmlid), "missing HR role %s" % xmlid)

    def test_payroll_preparer_cannot_approve(self):
        """The highest-value separation in the HR catalog.

        A payroll run moves money to named individuals, so the person who
        prepares it must not be the person who confirms it.
        """
        officer = self._role("role_hr_payroll_officer")
        payroll_lines = officer.access_line_ids.filtered(
            lambda line: line.transaction_type == "payroll_run"
        )
        self.assertTrue(payroll_lines)
        for line in payroll_lines:
            self.assertEqual(line.capability, "create")

        manager = self._role("role_hr_manager")
        approver_lines = manager.access_line_ids.filtered(
            lambda line: line.transaction_type == "payroll_run"
        )
        self.assertTrue(approver_lines)
        for line in approver_lines:
            self.assertEqual(line.capability, "approve")

    def test_self_service_carries_no_capability(self):
        """Self-service is outside the scope of segregation of duties.

        Every line manager is also an employee who books their own leave, so
        modelling self-service creation as a capability would raise a conflict
        for every manager in the company -- and a control that fires on everyone
        is one nobody reads.
        """
        employee = self._role("role_hr_employee")
        self.assertTrue(employee.access_line_ids)
        for line in employee.access_line_ids:
            self.assertEqual(
                line.capability,
                "none",
                "self-service line %s must not carry a capability" % line.id,
            )

    def test_approvers_require_a_security_key(self):
        """requires_webauthn computes from the tier, so this is really a check
        that the HR approvers were given a tier at all."""
        for xmlid in ("role_hr_line_manager", "role_hr_manager"):
            role = self._role(xmlid)
            self.assertNotEqual(role.is_approval_tier, "none")
            self.assertTrue(role.requires_webauthn)

    def test_chro_approves_nothing(self):
        """An executive who can also approve individual transactions
        concentrates the authority the tiered override workflow exists to
        split, and the reporting they need requires no write access."""
        chro = self._role("role_chro")
        self.assertEqual(chro.is_approval_tier, "none")
        for line in chro.access_line_ids:
            self.assertEqual(line.capability, "none")
            self.assertFalse(line.perm_create)
            self.assertFalse(line.perm_write)
            self.assertFalse(line.perm_unlink)

    def test_no_hr_role_both_creates_and_approves_one_class(self):
        """The model rejects create_approve on a single line. This is the
        cross-line version: one role holding create on a transaction class and
        approve on the same class through two separate lines."""
        codes = (
            "HR_EMPLOYEE",
            "HR_LINE_MANAGER",
            "HR_OFFICER",
            "PAYROLL_OFFICER",
            "HR_MANAGER",
            "CHRO",
        )
        roles = self.env["role.plaza_model"].search([("code", "in", codes)])
        for role in roles:
            creates = {
                line.transaction_type
                for line in role.access_line_ids
                if line.capability == "create"
            }
            approves = {
                line.transaction_type
                for line in role.access_line_ids
                if line.capability == "approve"
            }
            self.assertFalse(
                creates & approves,
                "%s both creates and approves %s"
                % (role.code, creates & approves),
            )

    def test_every_capability_line_names_a_transaction_class(self):
        """Without one the segregation-of-duties checker cannot group the line,
        so the duty would be invisible to the control."""
        roles = self.env["role.plaza_model"].search([])
        for line in roles.mapped("access_line_ids"):
            if line.capability != "none":
                self.assertTrue(
                    line.transaction_type,
                    "line %s carries a capability but no transaction class"
                    % line.id,
                )

    def test_roles_grant_something(self):
        """The catalog must not install as roles that describe access nobody has.

        A role whose permissions are set while its backing group confers
        nothing gives its holders nothing at all, and the monthly review signs
        off on a description that does not match the system.

        Employee is excluded deliberately: every one of its areas is
        self-service, and Perfect HR's baseline access already covers acting on
        your own records. It confers nothing extra and is complete as it is.
        """
        for xmlid in ("role_hr_line_manager", "role_hr_officer", "role_hr_manager"):
            role = self._role(xmlid)
            self.assertTrue(
                role.group_id.sudo().implied_ids,
                "%s confers no access, so holders get nothing" % role.code,
            )
            self.assertFalse(role.grants_nothing)

    def test_self_service_role_is_not_flagged_as_empty(self):
        """Employee grants nothing extra, and that is correct.

        Baseline access already covers your own attendance and leave. Flagging
        it would train people to ignore the warning.
        """
        self.assertFalse(self._role("role_hr_employee").grants_nothing)

    def test_grants_nothing_flags_the_gap(self):
        """A role with matrix lines and no grants is flagged, not silent."""
        role = self.env["role.plaza_model"].create(
            {
                "code": "TEST_HOLLOW",
                "name": "Hollow Role",
                "description": "Declares access it does not grant.",
                "access_line_ids": [
                    (0, 0, {"area": "payroll", "access_level": "view"})
                ],
            }
        )
        self.assertTrue(role.grants_nothing)

    def test_a_role_with_no_matrix_is_not_flagged(self):
        """`grants_nothing` means "declares more than it grants", not "grants
        nothing". A role with no matrix declares nothing and is not a gap."""
        role = self.env["role.plaza_model"].create(
            {
                "code": "TEST_EMPTY",
                "name": "Empty Role",
                "description": "Declares nothing, grants nothing.",
            }
        )
        self.assertFalse(role.grants_nothing)

    def test_applying_default_grants_is_additive(self):
        """A deliberate local grant must survive the next upgrade.

        Silently revoking access on upgrade is far worse than leaving an extra
        grant in place, so the applier only ever adds.
        """
        role = self._role("role_chro")
        extra = self.env["res.groups"].create({"name": "Test Extra Group"})
        role.group_id.sudo().write(
            {"implied_ids": [(4, extra.id)]}
        )

        self.env["role.plaza_model"]._apply_all_permission_grants()

        self.assertIn(
            extra,
            role.group_id.sudo().implied_ids,
            "a locally-added grant was removed by the upgrade applier",
        )

    def test_default_grants_skip_absent_modules(self):
        """Optional modules are routine; a missing one must not raise."""
        # Runs against whatever this deployment has installed. The assertion is
        # simply that it completes -- hr_recruitment and friends may be absent.
        self.env["role.plaza_model"]._apply_all_permission_grants()
