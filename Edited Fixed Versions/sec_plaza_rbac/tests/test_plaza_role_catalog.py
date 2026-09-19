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

    # --- AC: bounded catalog, min MIN_ACTIVE_ROLES / max MAX_ACTIVE_ROLES ---
    def test_seed_catalog_is_within_bounds(self):
        """The shipped catalog satisfies the active-role bound.

        Asserted against the constants rather than literals: the ceiling was
        raised from 20 to 25 for the HR extension, and a test carrying the old
        number would have passed while describing something untrue.
        """
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

    # --- AC: permissions are one area and one level ------------------------
    def test_a_permission_is_an_area_and_a_level(self):
        """Everything else on the line is derived from those two.

        The previous form asked for seven fields, six of which were mechanical
        consequences of the first and any of which could be made to contradict
        the rest.
        """
        role = self._make_role("MATRIX")
        line = self.Access.create(
            {
                "role_id": role.id,
                "area": "sales",
                "access_level": "submit",
                "field_restrictions": "margin_percent",
            }
        )
        self.assertEqual(role.access_line_count, 1)
        self.assertEqual(line.module_label, "Sales Orders")
        self.assertEqual(line.transaction_type, "sale_order")
        self.assertEqual(line.capability, "create")
        self.assertTrue(line.perm_read)
        self.assertTrue(line.perm_create)
        self.assertEqual(line.field_restrictions, "margin_percent")

    def test_approve_grants_write_but_never_create(self):
        """An approver who could also raise the work would defeat the control."""
        role = self._make_role("APPROVER")
        line = self.Access.create(
            {"role_id": role.id, "area": "payments", "access_level": "approve"}
        )
        self.assertTrue(line.perm_write)
        self.assertFalse(line.perm_create)
        self.assertEqual(line.capability, "approve")

    def test_view_only_grants_no_capability(self):
        """Observing cannot put anybody in conflict with anybody."""
        role = self._make_role("WATCHER")
        line = self.Access.create(
            {"role_id": role.id, "area": "payroll", "access_level": "view"}
        )
        self.assertTrue(line.perm_read)
        self.assertFalse(line.perm_write)
        self.assertEqual(line.capability, "none")

    def test_no_permission_grants_delete(self):
        """Delete was removed entirely: records are archived, never removed,
        and an option nobody needs is one somebody grants by accident."""
        role = self._make_role("NODELETE")
        for level in ("view", "submit", "approve"):
            line = self.Access.create(
                {"role_id": role.id, "area": "sales", "access_level": level}
            )
            self.assertFalse(line.perm_unlink)
            line.unlink()

    def test_self_service_raises_no_duty_conflict(self):
        """Segregation of duties governs acting on somebody else's records.

        Booking your own leave is not a duty conflict with whoever approves
        leave. Without this, every line manager in the company would be flagged
        — and a control that fires on everyone is one nobody reads.
        """
        role = self._make_role("SELFSERVE")
        line = self.Access.create(
            {"role_id": role.id, "area": "leave", "access_level": "submit"}
        )
        self.assertFalse(line.transaction_type)
        self.assertEqual(line.capability, "none")

        # Approving others' leave is a duty, and does carry one.
        approver = self._make_role("LEAVEAPPROVER")
        approving = self.Access.create(
            {"role_id": approver.id, "area": "leave", "access_level": "approve"}
        )
        self.assertEqual(approving.transaction_type, "leave_request")
        self.assertEqual(approving.capability, "approve")

    def test_same_area_twice_on_one_role_rejected(self):
        role = self._make_role("DUPAREA")
        base = {"role_id": role.id, "area": "sales", "access_level": "view"}
        self.Access.create(base)
        with self.assertRaises(Exception):
            self.Access.create(dict(base))

    def test_area_is_required_when_a_line_is_edited(self):
        """Enforced in Python rather than with `required=True`.

        A NOT NULL column would have made an unconvertible line fail the whole
        upgrade, leaving only bad options: delete reviewed configuration, or
        guess at it.
        """
        role = self._make_role("NOAREA")
        with self.assertRaises(ValidationError):
            self.Access.create({"role_id": role.id, "access_level": "view"})

    def test_permissions_confer_access_without_a_second_step(self):
        """Saving permissions grants them. There is no separate apply.

        The gap between describing a role and granting it is exactly where the
        catalog used to drift from the system it was supposed to describe.
        """
        role = self._make_role("GRANTS")
        self.Access.create(
            {"role_id": role.id, "area": "employees", "access_level": "view"}
        )
        role.invalidate_recordset()
        expected = self.env.ref("hr.group_hr_user", raise_if_not_found=False)
        if not expected:
            self.skipTest("hr is not installed on this deployment")
        self.assertIn(expected, role.group_id.sudo().implied_ids)

    def test_applying_grants_never_revokes(self):
        """Access set outside the catalog survives.

        Quietly revoking because a permission line changed would break somebody
        mid-task with no trace of why. Removals are made on purpose, by a
        person.
        """
        role = self._make_role("KEEPS")
        extra = self.env["res.groups"].create({"name": "Test Outside Grant"})
        role.group_id.sudo().write({"implied_ids": [(4, extra.id)]})

        self.Access.create(
            {"role_id": role.id, "area": "sales", "access_level": "view"}
        )
        role._apply_permission_grants()

        self.assertIn(extra, role.group_id.sudo().implied_ids)

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

    # --- Regression: the 18.0.1.5.0 conversion --------------------------------
    def test_no_role_has_two_lines_for_one_area(self):
        """The unique key is (role, area), and the seed must already satisfy it.

        Two old lines could map to one area — account.move as a journal entry
        and account.analytic.line are both "Journal Entries" — and the first
        attempt at this upgrade failed exactly there: the migration kept whichever
        duplicate Postgres happened to return first, so the surviving row was
        sometimes the one the data file no longer names. Its external ID then
        pointed at a deleted row, Odoo treated the data-file record as new, and
        creating it collided with the row that had been kept.
        """
        self.env.cr.execute(
            """
            SELECT role_id, area, count(*)
              FROM role_plaza_model_access
             WHERE area IS NOT NULL
          GROUP BY role_id, area
            HAVING count(*) > 1
            """
        )
        self.assertFalse(
            self.env.cr.fetchall(),
            "a role has two permission lines for the same area",
        )

    def test_every_converted_line_has_an_area(self):
        """A line with no area grants nothing and is invisible to the scan.

        Not an assertion that conversion is impossible to fail — a line that
        could not be mapped is deliberately kept with a blank area rather than
        deleted — but the shipped catalog must contain none of them.
        """
        blank = self.Access.search([("area", "=", False)])
        self.assertFalse(
            blank,
            "permission lines without an area: %s"
            % blank.mapped("role_id.code"),
        )
