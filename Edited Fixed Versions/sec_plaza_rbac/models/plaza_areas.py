# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The areas of Perfect HR a role can be given access to.

This file is the whole reason a permission line is now one dropdown instead of
seven fields. Everything the system needs -- which records the line covers, what
class of transaction it is, whether the holder originates or approves, and what
access it actually confers -- is derived from two choices: **an area and a
level**.

Before this, an author had to supply a module, a model, four permission
checkboxes, a transaction class and a capability, and then separately configure
the access that made any of it real. Six of those seven are mechanical
consequences of the first, and leaving them to be entered by hand meant they
could disagree with each other -- a line could claim "approve" while granting
create, or name a transaction class that contradicted the model.

Adding a new area is the only change needed to extend the catalog's reach.

**Areas are business language, never technical names.** "Leave", not `hr.leave`.
The record names are an implementation detail of this file and appear nowhere a
user can see.
"""

# Access levels, in increasing order of authority. The order matters: it is what
# lets the form present them as a single escalating choice, and what the
# migration uses to pick the closest level for an existing permission line.
#
# Delete is deliberately absent. No role in the catalog held it, HR records are
# evidence for payroll and attendance history -- they are archived, never
# removed -- and offering the option only creates a way to grant it by accident.
LEVEL_NONE = "none"
LEVEL_VIEW = "view"
LEVEL_SUBMIT = "submit"
LEVEL_APPROVE = "approve"

ACCESS_LEVELS = [
    (LEVEL_NONE, "No access"),
    (LEVEL_VIEW, "View only"),
    (LEVEL_SUBMIT, "Submit own"),
    (LEVEL_APPROVE, "Approve others'"),
]

LEVEL_ORDER = [LEVEL_NONE, LEVEL_VIEW, LEVEL_SUBMIT, LEVEL_APPROVE]

# What each level means in permission terms.
#
# "Submit own" carries write because an originator must be able to correct a
# draft before it is approved. "Approve others'" carries write but NOT create:
# an approver who could also raise the request would defeat the separation, and
# the model rejects that combination on save anyway.
LEVEL_PERMISSIONS = {
    LEVEL_NONE: {"read": False, "create": False, "write": False},
    LEVEL_VIEW: {"read": True, "create": False, "write": False},
    LEVEL_SUBMIT: {"read": True, "create": True, "write": True},
    LEVEL_APPROVE: {"read": True, "create": False, "write": True},
}

# The capability the segregation-of-duties scan groups by. Only the two levels
# that act on a transaction carry one; "view" observes and cannot create a
# conflict with anybody.
LEVEL_CAPABILITY = {
    LEVEL_NONE: "none",
    LEVEL_VIEW: "none",
    LEVEL_SUBMIT: "create",
    LEVEL_APPROVE: "approve",
}


class Area:
    """One area of Perfect HR, and everything derivable from choosing it.

    ``grants`` maps a level to the access it confers, cumulatively: a level
    receives its own entry plus every lower level's. That is why "Approve
    others'" does not need to repeat the groups that "View only" already gives.

    ``transaction`` is the segregation-of-duties class. ``None`` means the area
    is not a transaction -- reading a policy document or looking up an asset is
    not something one person originates and another signs off -- so lines in it
    never produce a duty conflict.
    """

    __slots__ = ("key", "label", "records", "transaction", "grants", "self_service")

    def __init__(
        self,
        key,
        label,
        records,
        transaction=None,
        grants=None,
        self_service=False,
    ):
        self.key = key
        self.label = label
        self.records = records
        self.transaction = transaction
        self.grants = grants or {}
        # True where Perfect HR's baseline access already covers acting on
        # one's own records. Such an area needs no access granted for the lower
        # levels, and -- more importantly -- a self-service line raises no duty
        # conflict, because segregation of duties governs acting on somebody
        # else's records, not your own.
        self.self_service = self_service

    def access_for(self, level):
        """Cumulative access at ``level``: its own plus every lower level's."""
        wanted = []
        for candidate in LEVEL_ORDER:
            wanted.extend(self.grants.get(candidate, ()))
            if candidate == level:
                break
        # De-duplicated, order preserved, so the log of what changed reads in a
        # stable order rather than a set's arbitrary one.
        seen = set()
        return [g for g in wanted if not (g in seen or seen.add(g))]


# ---------------------------------------------------------------------------
# The catalog of areas.
#
# Access names are referenced as strings and looked up defensively at the point
# of use, never with ``ref()`` in a data file. This module governs finance and
# procurement as well as HR, and must install on a deployment that runs only
# some of them -- so a missing one is skipped, not an error.
# ---------------------------------------------------------------------------
AREAS = [
    # ---- People -----------------------------------------------------------
    Area(
        "attendance",
        "Attendance",
        ["hr.attendance"],
        transaction="attendance_record",
        self_service=True,
        grants={
            LEVEL_VIEW: ["hr_attendance.group_hr_attendance_own_reader"],
            LEVEL_APPROVE: ["hr_attendance.group_hr_attendance_officer"],
        },
    ),
    Area(
        "leave",
        "Leave",
        ["hr.leave", "hr.leave.allocation"],
        transaction="leave_request",
        self_service=True,
        grants={
            # Requesting your own leave needs nothing beyond baseline access.
            LEVEL_APPROVE: ["hr_holidays.group_hr_holidays_responsible"],
        },
    ),
    Area(
        "employees",
        "Employee Records",
        ["hr.employee", "hr.contract"],
        transaction="employee_master",
        grants={
            LEVEL_VIEW: ["hr.group_hr_user"],
            LEVEL_APPROVE: ["hr.group_hr_manager"],
        },
    ),
    Area(
        "payroll",
        "Payroll",
        ["hr.payslip"],
        transaction="payroll_run",
        grants={
            LEVEL_VIEW: ["hr_payroll_community.group_hr_payroll_community_user"],
            LEVEL_APPROVE: [
                "hr_payroll_community.group_hr_payroll_community_manager"
            ],
        },
    ),
    Area(
        "recruitment",
        "Recruitment",
        ["hr.applicant"],
        transaction="recruitment",
        grants={
            LEVEL_VIEW: ["hr_recruitment.group_hr_recruitment_interviewer"],
            LEVEL_SUBMIT: ["hr_recruitment.group_hr_recruitment_user"],
            LEVEL_APPROVE: ["hr_recruitment.group_hr_recruitment_manager"],
        },
    ),
    Area("expenses", "Expenses", ["hr.expense"], self_service=True),
    Area("documents", "Documents", ["hr.dms.document"]),
    Area("assets", "Assets", ["eam.asset.allocation"]),
    Area("loans", "Loans & Advances", ["hr.loan", "salary.advance"], self_service=True),
    Area("appraisals", "Appraisals", ["hr.appraisal"]),
    # ---- Commercial -------------------------------------------------------
    Area(
        "sales",
        "Sales Orders",
        ["sale.order"],
        transaction="sale_order",
        grants={
            LEVEL_VIEW: ["sales_team.group_sale_salesman"],
            LEVEL_APPROVE: ["sales_team.group_sale_manager"],
        },
    ),
    Area(
        "purchasing",
        "Purchase Orders",
        ["purchase.order"],
        transaction="purchase_order",
        grants={
            LEVEL_VIEW: ["purchase.group_purchase_user"],
            LEVEL_APPROVE: ["purchase.group_purchase_manager"],
        },
    ),
    Area(
        "customer_invoices",
        "Customer Invoices",
        ["account.move"],
        transaction="customer_invoice",
        grants={
            LEVEL_VIEW: ["account.group_account_invoice"],
            LEVEL_APPROVE: ["account.group_account_manager"],
        },
    ),
    Area(
        "vendor_bills",
        "Vendor Bills",
        ["account.move"],
        transaction="vendor_bill",
        grants={
            LEVEL_VIEW: ["account.group_account_invoice"],
            LEVEL_APPROVE: ["account.group_account_manager"],
        },
    ),
    Area(
        "payments",
        "Payments",
        ["account.payment"],
        transaction="vendor_payment",
        grants={
            LEVEL_VIEW: ["account.group_account_invoice"],
            LEVEL_APPROVE: ["account.group_account_manager"],
        },
    ),
    Area(
        "journals",
        "Journal Entries",
        ["account.move", "account.analytic.line", "account.journal"],
        transaction="journal_entry",
        grants={
            LEVEL_VIEW: ["account.group_account_readonly"],
            LEVEL_SUBMIT: ["account.group_account_user"],
            LEVEL_APPROVE: ["account.group_account_manager"],
        },
    ),
    Area(
        "inventory",
        "Inventory",
        ["stock.move", "stock.picking"],
        transaction="stock_move",
        grants={
            LEVEL_VIEW: ["stock.group_stock_user"],
            LEVEL_APPROVE: ["stock.group_stock_manager"],
        },
    ),
    Area(
        "master_data",
        "Master Data",
        [
            "res.partner",
            "product.template",
            "product.product",
            "product.pricelist",
            "product.supplierinfo",
        ],
        transaction="master_data",
        grants={
            LEVEL_APPROVE: ["base.group_partner_manager"],
        },
    ),
    Area(
        "crm",
        "Leads & Opportunities",
        ["crm.lead"],
        grants={
            LEVEL_VIEW: ["sales_team.group_sale_salesman"],
            LEVEL_APPROVE: ["sales_team.group_sale_manager"],
        },
    ),
    # Not a transaction: administering users is a standing capability, not
    # something one person raises and another signs off. It carries no
    # transaction class, so it produces no duty conflict -- the control that
    # matters here is the non-standard-grant check in ResUsers.write, not this
    # catalog.
    Area(
        "user_admin",
        "User Administration",
        ["res.users", "res.groups"],
        grants={
            LEVEL_APPROVE: ["base.group_erp_manager"],
        },
    ),
]

AREA_SELECTION = [(area.key, area.label) for area in AREAS]
AREAS_BY_KEY = {area.key: area for area in AREAS}


def area_for_record(record_name):
    """The first area covering ``record_name``, or None.

    Used only by the migration from the old free-form matrix. Several areas can
    cover the same record -- customer invoices, vendor bills and journal entries
    are all ``account.move`` -- so the transaction class is consulted first
    where the old line had one, and this is the fallback.
    """
    for area in AREAS:
        if record_name in area.records:
            return area
    return None


def area_for_transaction(transaction):
    """The area owning a transaction class, or None."""
    if not transaction:
        return None
    for area in AREAS:
        if area.transaction == transaction:
            return area
    return None
