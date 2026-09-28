# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Who somebody is at work -- the first half of authorisation.

THE ONE DEFINITION
------------------
Both the sign-in response and ``/me/capabilities`` describe the signed-in
employee's position and standing, and until now each built that dictionary
itself. The two had drifted: sign-in sent ``employment_status`` and
``joined_on``, capabilities did not. Because the app re-reads capabilities
whenever it returns to the foreground, an employee's Status row appeared at
sign-in and then silently vanished the first time they switched apps.

That is the ordinary fate of a payload defined twice, so it is defined once
here and both callers ask for it.

WHY JOINING DATE IS NOT ``create_date``
---------------------------------------
It used to be. ``create_date`` is when the *record* was made, which for any
company that migrated into Perfect HR is the migration date -- so every
employee, including someone with twenty years' service, would be shown as
having joined the day the database was loaded.

Tenure is not decoration. It drives leave accrual, probation, increments and
gratuity, and a person who reads "joined 2026" on their own profile has been
told something false about their employment. So the date is taken from the
contract record, through whichever field this deployment actually has, and is
**omitted when it cannot be established**. A blank row prompts someone to ask
HR; a confidently wrong one does not.

EVERY FIELD IS OPTIONAL, ON PURPOSE
-----------------------------------
``hr_contract``, ``hr_employee_updation`` and the rest are installed on some
deployments and not others, and a new joiner's record is half-empty by
definition. Every lookup is guarded and every value is nullable: a missing
field means one row is not drawn, never that somebody cannot sign in.
"""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# Contract states, in the words an employee would use about their own job.
#
# Odoo's raw values (``draft``, ``open``, ``close``, ``cancel``) are database
# vocabulary; "Ended" is what a person calls the same thing. Mapped here rather
# than in the app so that the phone and the web never disagree about what a
# state means.
CONTRACT_STATE_LABELS = {
    "draft": "Awaiting contract",
    "open": "Active",
    "close": "Ended",
    "cancel": "Cancelled",
}

# ``hr.employee.employee_type`` -- core Odoo, but its labels are translated
# through the user's language, so they are taken from the field itself rather
# than restated here. This map exists only for the values core does not label
# in a way an employee would recognise.
EMPLOYEE_TYPE_OVERRIDES = {
    "employee": "Permanent",
}


class MobileEmploymentProfile(models.AbstractModel):
    """The employment card, built one way for every caller."""

    _name = "perfecthr.mobile.employment"
    _description = "Mobile Employment Profile"

    # ------------------------------------------------------------------
    # Helpers, each tolerant of a module this deployment does not have
    # ------------------------------------------------------------------
    @api.model
    def _has(self, record, field_name):
        """True when this deployment's schema actually carries the field.

        The house pattern -- ``perfecthr_ai_insights`` guards ``joining_date``
        the same way -- because addons that add fields to ``hr.employee`` are
        optional here and ``getattr`` on an absent field raises rather than
        returning a default.
        """
        return bool(record) and field_name in record._fields

    @api.model
    def _contract(self, employee):
        """The employee's current contract, or an empty recordset.

        ``contract_id`` is what ``hr_contract`` computes as the running
        contract. Absent entirely where the module is not installed, which is
        a supported deployment rather than a fault.
        """
        if not self._has(employee, "contract_id"):
            return None
        return employee.contract_id or None

    @api.model
    def _joined_on(self, employee):
        """When this person started, from the contract record only.

        Three sources, best first, and no fallback to ``create_date`` -- see
        the module docstring for why a migration date presented as a joining
        date is worse than no date at all.
        """
        # 1. hr_employee_updation computes this as the earliest contract start.
        if self._has(employee, "joining_date") and employee.joining_date:
            return employee.joining_date

        # 2. hr_contract's own computed first contract date.
        if self._has(employee, "first_contract_date") and employee.first_contract_date:
            return employee.first_contract_date

        # 3. The earliest contract we can see, computed here. sudo() because an
        #    employee may read their own contract dates without holding general
        #    contract access, and this is their own record by construction.
        if self._has(employee, "contract_ids"):
            starts = [
                contract.date_start
                for contract in employee.sudo().contract_ids
                if contract.date_start
            ]
            if starts:
                return min(starts)

        # Nothing truthful to say.
        return None

    @api.model
    def _employee_type(self, employee):
        """Permanent, contractor, intern -- in the deployment's own words.

        Read through the field's selection rather than a table here, so a
        company that has added its own employment types sees its own labels
        instead of falling through to the raw key.
        """
        if not self._has(employee, "employee_type") or not employee.employee_type:
            return None
        raw = employee.employee_type
        if raw in EMPLOYEE_TYPE_OVERRIDES:
            return EMPLOYEE_TYPE_OVERRIDES[raw]
        try:
            labels = dict(
                employee._fields["employee_type"]._description_selection(self.env)
            )
            return labels.get(raw) or raw.replace("_", " ").title()
        except Exception:  # noqa: BLE001
            # A custom selection that cannot be introspected must not cost the
            # whole profile. Title-case the key: imperfect, but readable.
            return raw.replace("_", " ").title()

    # ------------------------------------------------------------------
    # The card
    # ------------------------------------------------------------------
    @api.model
    def card(self, employee):
        """Position and standing for the signed-in employee.

        Returns ``None`` where there is no linked employee record at all --
        which the app reports as an HR data task rather than an error, because
        that is what it is.

        Every value is either a real fact or ``None``. Nothing is inferred,
        defaulted or guessed, because each row here is something a person will
        read about their own job.
        """
        if not employee:
            return None

        contract = self._contract(employee)
        state = contract.state if contract else None
        joined_on = self._joined_on(employee)

        return {
            # The badge number. The same value the fingerprint terminals match
            # punches on, and one of the two things somebody may sign in with.
            "employee_code": employee.identification_id or None,
            "job_title": employee.job_title or (employee.job_id.name or None),
            "job_position": employee.job_id.name or None,
            "department": employee.department_id.name or None,
            "manager": employee.parent_id.name or None,
            "work_location": employee.work_location_id.name or None,
            "shift": employee.resource_calendar_id.name or None,
            "work_email": employee.work_email or None,
            "work_phone": employee.work_phone or None,
            # Employment standing, from the contract where hr_contract is
            # installed. Sent both raw and labelled: the app renders the label,
            # and keeps the raw value so it can style an ended contract
            # differently without parsing English.
            "employment_status": state,
            "employment_status_label": (
                CONTRACT_STATE_LABELS.get(state, state.replace("_", " ").title())
                if state
                else None
            ),
            # Permanent, contractor, intern. What the employee *is*, which is
            # a different question from whether their contract is running.
            "employee_type": self._employee_type(employee),
            "joined_on": str(joined_on) if joined_on else None,
            # When the current contract runs out, where one is set. Open-ended
            # contracts have no end date and correctly report nothing.
            "contract_end": (
                str(contract.date_end)
                if contract and getattr(contract, "date_end", False)
                else None
            ),
            # The company this employment belongs to, which in a multi-company
            # tenant is not necessarily the company the session is operating
            # in -- so it is stated rather than assumed.
            "company": employee.company_id.name or None,
        }
