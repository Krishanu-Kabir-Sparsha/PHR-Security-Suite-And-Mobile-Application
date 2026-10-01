# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Hard enforcement: the gate, the multi-site rule, and the way out.

THE PROPERTY BEING PROTECTED
----------------------------
Under ENFORCE, an employee cannot check themselves in from outside the radius.
Not from the app, not from the web dashboard, not from Odoo's own widget.

The reason this lives on ``hr.attendance.create`` and not in a controller is
that it used to live in a controller -- exactly one of them. The mobile toggle
checked location; the auto check-in that happens when somebody signs in to the
app did not, nor did the web dashboard, nor the backend widget. A rule enforced
on one of four routes is not enforced.

WHAT MUST STILL WORK
--------------------
Three things, and each has a test here, because a gate that broke any of them
would be withdrawn within a day:

* HR correcting somebody's attendance
* the biometric terminal, which writes for an employee as a different user
* an approved off-site request, which IS the authorisation
"""

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

# Somewhere in Dhaka. The exact point does not matter; the separations do.
LAT, LON = 23.8759, 90.3200
# ~1.1 km north, comfortably outside any sane radius.
FAR_LAT = LAT + 0.010


@tagged("post_install", "-at_install")
class TestGeofenceGate(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env["res.company"].create({
            "name": "Gate Co",
            "attendance_geofence_mode": "enforce",
        })
        self.location = self.env["hr.work.location"].create({
            "name": "Gate HQ",
            "company_id": self.company.id,
            "geofence_latitude": LAT,
            "geofence_longitude": LON,
            "geofence_radius_m": 250,
        })
        self.user = self.env["res.users"].create({
            "name": "Rafiq Ahmed",
            "login": "rafiq.gate@example.internal",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        self.employee = self.env["hr.employee"].create({
            "name": "Rafiq Ahmed",
            "company_id": self.company.id,
            "user_id": self.user.id,
            "work_location_id": self.location.id,
        })

    def _punch_as_self(self, latitude=None, longitude=None, accuracy=None):
        """Create attendance the way the employee's own device would."""
        return (
            self.env["hr.attendance"]
            .with_user(self.user)
            .with_context(perfecthr_punch_location={
                "latitude": latitude,
                "longitude": longitude,
                "accuracy_m": accuracy,
            })
            .create({
                "employee_id": self.employee.id,
                "check_in": fields.Datetime.now(),
            })
        )

    # -- what is refused -------------------------------------------------
    def test_punching_from_far_away_is_refused(self):
        with self.assertRaises(ValidationError):
            self._punch_as_self(FAR_LAT, LON)

    def test_punching_with_no_position_is_refused(self):
        """The bypass that would otherwise exist.

        If an absent position were allowed, every route would only have to
        omit it -- and declining the location permission on the handset would
        be the way around the rule.
        """
        with self.assertRaises(ValidationError):
            self._punch_as_self()

    def test_the_refusal_explains_which_problem_it_was(self):
        """Three refusals, three remedies. One message would misdirect two
        thirds of the people who read it."""
        with self.assertRaises(ValidationError) as caught:
            self._punch_as_self()
        self.assertIn("could not tell where you are", str(caught.exception))

        with self.assertRaises(ValidationError) as caught:
            self._punch_as_self(FAR_LAT, LON)
        self.assertIn("Gate HQ", str(caught.exception))

    # -- what is allowed -------------------------------------------------
    def test_punching_from_the_office_works(self):
        attendance = self._punch_as_self(LAT, LON, accuracy=15)
        self.assertTrue(attendance.id)

    def test_warn_mode_never_refuses(self):
        self.company.attendance_geofence_mode = "warn"
        self.assertTrue(self._punch_as_self(FAR_LAT, LON).id)

    def test_off_mode_never_refuses(self):
        self.company.attendance_geofence_mode = "off"
        self.assertTrue(self._punch_as_self().id)

    def test_hr_correcting_somebody_else_is_not_gated(self):
        """The biometric gateway and every HR correction land here.

        Gating these would break attendance for people who were physically at
        a terminal, and would stop HR fixing a mistyped day.
        """
        attendance = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": fields.Datetime.now(),
        })
        self.assertTrue(attendance.id)

    def test_an_hr_manager_is_not_gated_even_for_themselves(self):
        """Not a loophole, an honest admission.

        An HR manager can already create and edit any attendance row for
        anybody. Refusing them their own would stop nothing and would strand
        the person most likely to be configuring this in the first place.
        """
        self.user.groups_id = [(4, self.env.ref("hr.group_hr_manager").id)]
        self.assertTrue(self._punch_as_self().id)

    def test_an_employee_nobody_placed_is_not_gated(self):
        """A configuration gap must never cost somebody their attendance."""
        self.employee.work_location_id = False
        self.assertTrue(self._punch_as_self().id)


@tagged("post_install", "-at_install")
class TestMultipleWorkLocations(TransactionCase):
    """Somebody who legitimately works in more than one place.

    Without this they are refused on every day they spend at the second site,
    for doing exactly what they were asked to do -- and the flag that results
    is noise that buries the real anomalies.
    """

    def setUp(self):
        super().setUp()
        self.company = self.env["res.company"].create({
            "name": "Two Site Co",
            "attendance_geofence_mode": "enforce",
        })
        self.head = self.env["hr.work.location"].create({
            "name": "Head Office",
            "company_id": self.company.id,
            "geofence_latitude": LAT,
            "geofence_longitude": LON,
            "geofence_radius_m": 250,
        })
        self.branch = self.env["hr.work.location"].create({
            "name": "Branch",
            "company_id": self.company.id,
            "geofence_latitude": FAR_LAT,
            "geofence_longitude": LON,
            "geofence_radius_m": 250,
        })
        self.employee = self.env["hr.employee"].create({
            "name": "Two Site Tester",
            "company_id": self.company.id,
            "work_location_id": self.head.id,
        })
        self.Fence = self.env["perfecthr.attendance.geofence"]

    def test_the_branch_is_refused_until_it_is_listed(self):
        self.assertEqual(
            self.Fence.evaluate(self.employee, FAR_LAT, LON)["outcome"],
            "refuse",
        )

    def test_listing_the_branch_lets_them_work_there(self):
        self.employee.attendance_location_ids = [(6, 0, [self.branch.id])]
        self.assertEqual(
            self.Fence.evaluate(self.employee, FAR_LAT, LON)["outcome"],
            "allow",
        )

    def test_head_office_still_works_too(self):
        self.employee.attendance_location_ids = [(6, 0, [self.branch.id])]
        self.assertEqual(
            self.Fence.evaluate(self.employee, LAT, LON)["outcome"], "allow"
        )

    def test_the_site_they_are_actually_at_is_the_one_named(self):
        """Telling somebody at the branch how far they are from head office
        answers a question nobody asked."""
        self.employee.attendance_location_ids = [(6, 0, [self.branch.id])]
        result = self.Fence.evaluate(self.employee, FAR_LAT + 0.02, LON)
        self.assertEqual(result["location_name"], self.branch.display_name)

    def test_a_location_with_no_coordinates_is_ignored_not_failed(self):
        unplaced = self.env["hr.work.location"].create({
            "name": "Not Placed Yet", "company_id": self.company.id,
        })
        self.employee.attendance_location_ids = [(6, 0, [unplaced.id])]
        self.assertEqual(
            self.Fence.evaluate(self.employee, LAT, LON)["outcome"], "allow"
        )


@tagged("post_install", "-at_install")
class TestOffsiteApproval(TransactionCase):
    """The way out of a refusal, and why it is not self-service."""

    def setUp(self):
        super().setUp()
        self.company = self.env["res.company"].create({
            "name": "Approval Co",
            "attendance_geofence_mode": "enforce",
        })
        self.user = self.env["res.users"].create({
            "name": "Nadia Islam",
            "login": "nadia.approval@example.internal",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        self.manager = self.env["hr.employee"].create({"name": "Imran Hossain"})
        self.employee = self.env["hr.employee"].create({
            "name": "Nadia Islam",
            "company_id": self.company.id,
            "user_id": self.user.id,
            "parent_id": self.manager.id,
        })
        self.Request = self.env["hr.attendance.offsite.request"]
        self.fence = {
            "outcome": "refuse",
            "reason": "out_of_range",
            "distance_m": 1100,
            "location_name": "Head Office",
            "latitude": FAR_LAT,
            "longitude": LON,
            "accuracy_m": 14,
        }

    def _submit(self, reason="Client visit at Gulshan"):
        return self.Request.submit(self.employee, self.fence, reason)

    def test_submitting_records_no_attendance(self):
        """THE property. The old design accepted the punch on the strength of
        a typed sentence, which made the employee their own authoriser."""
        before = self.env["hr.attendance"].search_count([
            ("employee_id", "=", self.employee.id)
        ])
        self._submit()
        after = self.env["hr.attendance"].search_count([
            ("employee_id", "=", self.employee.id)
        ])
        self.assertEqual(before, after)

    def test_a_blank_reason_is_refused(self):
        with self.assertRaises(ValidationError):
            self._submit("   ")

    def test_tapping_four_times_does_not_make_four_requests(self):
        """A manager reading four identical rows learns nothing from three."""
        first = self._submit()
        for _ in range(3):
            self._submit()
        self.assertEqual(
            self.Request.search_count([
                ("employee_id", "=", self.employee.id),
                ("state", "=", "pending"),
            ]),
            1,
        )
        self.assertEqual(self._submit().id, first.id)

    def test_approving_records_the_attempt_time_not_the_decision_time(self):
        """An approval at five in the afternoon must not record somebody as
        having started work at five in the afternoon."""
        request = self._submit()
        attempted = request.requested_at
        request.action_approve()

        self.assertEqual(request.state, "approved")
        self.assertTrue(request.attendance_id)
        self.assertEqual(request.attendance_id.check_in, attempted)
        self.assertTrue(request.attendance_id.off_site)
        self.assertEqual(request.attendance_id.off_site_distance_m, 1100)

    def test_the_employee_cannot_approve_their_own(self):
        """Without this it is a form, not an approval."""
        request = self._submit()
        with self.assertRaises(UserError):
            request.with_user(self.user).action_approve()

    def test_rejecting_records_nothing(self):
        request = self._submit()
        request.action_reject()
        self.assertEqual(request.state, "rejected")
        self.assertFalse(request.attendance_id)

    def test_a_decided_request_cannot_be_decided_again(self):
        request = self._submit()
        request.action_approve()
        with self.assertRaises(UserError):
            request.action_reject()

    def test_approving_over_existing_attendance_says_what_is_wrong(self):
        """Odoo's own overlap error names a constraint. This names the
        situation, because the approver has to choose what to do about it."""
        request = self._submit()
        self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": request.requested_at,
        })
        with self.assertRaises(UserError) as caught:
            request.action_approve()
        self.assertIn("already has attendance", str(caught.exception))

    def test_an_approved_request_survives_the_location_gate(self):
        """The approval IS the authorisation. If the gate refused it, the only
        way out of a refusal would itself be refused."""
        request = self._submit()
        request.action_approve()
        self.assertTrue(request.attendance_id.id)
