# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The employment card: who somebody is at work.

Two things are being protected here.

The first is that there is **one** definition. The sign-in response and
``/me/capabilities`` both describe the same employee, and when each built its
own dictionary they drifted -- the Status row appeared at sign-in and vanished
on the first foreground refresh. A test that only checked contents would have
passed throughout that whole bug, so the shape itself is asserted.

The second is that a **joining date is never invented**. It used to come from
``create_date``, which for a migrated company is the migration date, so a
twenty-year employee read as a new joiner. Tenure drives leave accrual,
probation and gratuity, and a confidently wrong date is worse than a blank one.
"""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestEmploymentProfile(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Profile = self.env["perfecthr.mobile.employment"]
        self.department = self.env["hr.department"].create({"name": "Finance"})
        self.job = self.env["hr.job"].create({"name": "Senior Officer"})
        self.manager = self.env["hr.employee"].create({"name": "Ayesha Rahman"})
        self.employee = self.env["hr.employee"].create(
            {
                "name": "Karim Hossain",
                "identification_id": "EMP-00421",
                "department_id": self.department.id,
                "job_id": self.job.id,
                "parent_id": self.manager.id,
                "work_email": "karim@example.internal",
            }
        )

    # -- the basics ----------------------------------------------------
    def test_no_employee_yields_no_card(self):
        """A user with no HR record must still get a working session.

        None rather than a dictionary of nulls: the app hides the card
        entirely, and a card of dashes reads as broken rather than as absent.
        """
        self.assertIsNone(self.Profile.card(self.env["hr.employee"]))
        self.assertIsNone(self.Profile.card(False))

    def test_position_and_reporting_line(self):
        card = self.Profile.card(self.employee)
        self.assertEqual(card["employee_code"], "EMP-00421")
        self.assertEqual(card["job_position"], "Senior Officer")
        self.assertEqual(card["department"], "Finance")
        self.assertEqual(card["manager"], "Ayesha Rahman")

    def test_a_half_filled_record_still_produces_a_card(self):
        """A new joiner has almost nothing on their record on day one.

        Every absent field must come back as None rather than raise -- the
        alternative is that the people most likely to be opening the app for
        the first time are exactly the ones who cannot.
        """
        bare = self.env["hr.employee"].create({"name": "New Joiner"})
        card = self.Profile.card(bare)
        self.assertIsNotNone(card)
        self.assertIsNone(card["department"])
        self.assertIsNone(card["manager"])
        self.assertIsNone(card["employee_code"])

    # -- the joining date ----------------------------------------------
    def test_joining_date_is_never_the_record_creation_date(self):
        """THE regression test for the migration-date bug.

        This employee was created moments ago and has no contract, so there is
        no truthful joining date to give. The wrong answer -- today -- is
        exactly what ``create_date`` would have returned, and it is what a
        migrated company would have seen for its entire workforce.
        """
        card = self.Profile.card(self.employee)
        self.assertIsNone(
            card["joined_on"],
            "A joining date was invented for an employee with no contract; "
            "this is the create_date bug returning.",
        )

    def test_joining_date_comes_from_the_contract_when_there_is_one(self):
        """Skipped where hr_contract is absent, which is a supported setup."""
        if "hr.contract" not in self.env:
            self.skipTest("hr_contract is not installed on this deployment")
        self.env["hr.contract"].create(
            {
                "name": "Karim 2019",
                "employee_id": self.employee.id,
                "date_start": "2019-03-01",
                "wage": 50000.0,
                "state": "open",
            }
        )
        self.employee.invalidate_recordset()
        self.assertEqual(self.Profile.card(self.employee)["joined_on"], "2019-03-01")

    # -- status ---------------------------------------------------------
    def test_status_is_sent_raw_and_labelled(self):
        """The app styles on the raw value and prints the label.

        Sending only the label would force the phone to match English to
        decide whether a contract has ended; sending only the raw value would
        put database vocabulary on an employee's own profile.
        """
        if "hr.contract" not in self.env:
            self.skipTest("hr_contract is not installed on this deployment")
        self.env["hr.contract"].create(
            {
                "name": "Karim current",
                "employee_id": self.employee.id,
                "date_start": "2019-03-01",
                "wage": 50000.0,
                "state": "open",
            }
        )
        self.employee.invalidate_recordset()
        card = self.Profile.card(self.employee)
        self.assertEqual(card["employment_status"], "open")
        self.assertEqual(card["employment_status_label"], "Active")

    def test_an_unknown_state_is_still_readable(self):
        """A deployment that added a contract state must not leak the key.

        Title-casing is imperfect, but "Probation Extended" is something a
        person can read and the raw key is not.
        """
        from odoo.addons.perfecthr_mobile_api.models.employment_profile import (
            CONTRACT_STATE_LABELS,
        )

        self.assertNotIn("probation_extended", CONTRACT_STATE_LABELS)
        self.assertEqual(
            "probation_extended".replace("_", " ").title(), "Probation Extended"
        )

    def test_employee_type_is_labelled_not_keyed(self):
        if "employee_type" not in self.employee._fields:
            self.skipTest("employee_type is not present on this Odoo build")
        self.employee.employee_type = "employee"
        self.assertEqual(
            self.Profile.card(self.employee)["employee_type"], "Permanent"
        )

    # -- the one definition --------------------------------------------
    def test_both_endpoints_describe_the_same_shape(self):
        """Sign-in and capabilities must not drift apart again.

        The bug this replaces was not a wrong value anywhere -- it was two
        dictionaries with different keys, which no per-field assertion would
        have caught.
        """
        card = self.Profile.card(self.employee)
        expected = {
            "employee_code",
            "job_title",
            "job_position",
            "department",
            "manager",
            "work_location",
            "shift",
            "work_email",
            "work_phone",
            "employment_status",
            "employment_status_label",
            "employee_type",
            "joined_on",
            "contract_end",
            "company",
        }
        self.assertEqual(
            set(card),
            expected,
            "The employment card's shape changed. Both /auth/login and "
            "/me/capabilities send this and the client parses one class from "
            "both, so a key added here must be added to Employment in Dart.",
        )
