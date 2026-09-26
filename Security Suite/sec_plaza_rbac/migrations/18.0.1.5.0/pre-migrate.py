# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Convert free-form permission lines to Area + Level.

**This has to run before the ORM loads the new field definitions**, which is why
it is a pre-migration and why it works in raw SQL. ``model_name``,
``module_label`` and the ``perm_*`` columns became computed-and-stored in this
version; the moment Odoo registers them it will recompute every row from
``area``, and ``area`` is exactly what does not exist yet. Reading the old values
afterwards would read values this migration was supposed to produce.

Nothing is deleted. A line that cannot be mapped keeps its old columns and is
reported in the log with its role code, so it can be set by hand rather than
disappearing from a catalog somebody signed off.
"""

import logging

_logger = logging.getLogger(__name__)

TABLE = "role_plaza_model_access"

# transaction class -> area. Consulted first, because several areas cover the
# same record: customer invoices, vendor bills and journal entries are all
# account.move, and only the transaction class tells them apart.
BY_TRANSACTION = {
    "sale_order": "sales",
    "purchase_order": "purchasing",
    "customer_invoice": "customer_invoices",
    "vendor_bill": "vendor_bills",
    "vendor_payment": "payments",
    "journal_entry": "journals",
    "stock_move": "inventory",
    "master_data": "master_data",
    "leave_request": "leave",
    "attendance_record": "attendance",
    "payroll_run": "payroll",
    "employee_master": "employees",
    "recruitment": "recruitment",
}

# record name -> area, for lines that carried no transaction class.
BY_RECORD = {
    "sale.order": "sales",
    "purchase.order": "purchasing",
    "account.move": "journals",
    "account.payment": "payments",
    "account.journal": "journals",
    "account.analytic.line": "journals",
    "stock.picking": "inventory",
    "stock.move": "inventory",
    "res.partner": "master_data",
    "product.template": "master_data",
    "product.product": "master_data",
    "product.pricelist": "master_data",
    "product.supplierinfo": "master_data",
    "crm.lead": "crm",
    "res.users": "user_admin",
    "res.groups": "user_admin",
    "hr.attendance": "attendance",
    "hr.leave": "leave",
    "hr.leave.allocation": "leave",
    "hr.employee": "employees",
    "hr.contract": "employees",
    "hr.payslip": "payroll",
    "hr.applicant": "recruitment",
    "hr.expense": "expenses",
    "hr.dms.document": "documents",
    "eam.asset.allocation": "assets",
    "hr.loan": "loans",
    "salary.advance": "loans",
    "hr.appraisal": "appraisals",
}


def _level_for(capability, perm_create, perm_write, perm_read):
    """The closest level for an old line's permission bits.

    Capability decides it where the line had one -- it is the more specific
    statement, and it is what the segregation-of-duties scan already read. The
    permission bits are the fallback for the majority of lines, which carried no
    capability at all.

    A line that granted write but not create maps to "Approve others'": under
    the old model that combination was how an approver was expressed, and
    reading it as "Submit own" would hand somebody the ability to raise work
    they are only meant to sign off.
    """
    if capability == "approve":
        return "approve"
    if capability in ("create", "create_approve"):
        return "submit"
    if perm_create:
        return "submit"
    if perm_write:
        return "approve"
    if perm_read:
        return "view"
    return "none"


LEVEL_RANK = {"none": 0, "view": 1, "submit": 2, "approve": 3}


def _convert(cr):
    """Set area and access_level on every line that has none yet."""
    cr.execute(
        """
        SELECT a.id, a.model_name, a.transaction_type, a.capability,
               a.perm_create, a.perm_write, a.perm_read, r.code
          FROM %s a
          LEFT JOIN role_plaza_model r ON r.id = a.role_id
         WHERE a.area IS NULL
         ORDER BY a.id
        """
        % TABLE
    )

    converted = 0
    for (
        line_id,
        model_name,
        transaction_type,
        capability,
        perm_create,
        perm_write,
        perm_read,
        role_code,
    ) in cr.fetchall():
        area = BY_TRANSACTION.get(transaction_type) or BY_RECORD.get(model_name)
        if not area:
            _logger.warning(
                "Plaza RBAC: permission line on role %s (%s) could not be "
                "converted. It is kept, with a blank Area, and needs setting by "
                "hand on the role's Permissions tab.",
                role_code,
                model_name,
            )
            continue
        cr.execute(
            "UPDATE %s SET area = %%s, access_level = %%s WHERE id = %%s" % TABLE,
            (
                area,
                _level_for(capability, perm_create, perm_write, perm_read),
                line_id,
            ),
        )
        converted += 1

    _logger.info("Plaza RBAC: converted %s permission lines to Area + Level", converted)


def _deduplicate(cr):
    """Collapse lines that now share a (role, area), before the unique key lands.

    Two old lines can map to one area -- account.move as a journal entry and
    account.analytic.line are both "Journal Entries" -- and the new unique key
    is (role_id, area).

    Two things here are load-bearing, and getting either wrong is what broke the
    first attempt at this upgrade:

    * **The lowest id wins.** Without ``ORDER BY`` Postgres returns rows in
      whatever order it likes, so the surviving row was arbitrary -- and the
      seeded data file only still contains the *first* of each pair. When the
      second one survived, the first one's external ID pointed at a deleted row,
      Odoo treated the data-file record as new, and creating it collided with
      the row that had been kept.
    * **The external ID goes with the row.** Deleting from the table alone
      leaves ``ir_model_data`` pointing at nothing, which is the same failure by
      a different route.

    The stronger level wins, because the role genuinely held that access and
    quietly reducing it would break somebody the next morning with no trace of
    why.

    Runs unconditionally rather than only after a conversion, so a half-applied
    upgrade can be repaired by simply running it again.
    """
    cr.execute(
        """
        SELECT role_id, area, array_agg(id ORDER BY id)
          FROM %s
         WHERE area IS NOT NULL
      GROUP BY role_id, area
        HAVING count(*) > 1
        """
        % TABLE
    )
    groups = cr.fetchall()
    if not groups:
        return

    for role_id, area, ids in groups:
        keep, drop = ids[0], ids[1:]

        cr.execute(
            "SELECT access_level FROM %s WHERE id IN %%s" % TABLE,
            (tuple(ids),),
        )
        strongest = max(
            (row[0] or "none" for row in cr.fetchall()),
            key=lambda level: LEVEL_RANK.get(level, 0),
        )

        cr.execute(
            "UPDATE %s SET access_level = %%s WHERE id = %%s" % TABLE,
            (strongest, keep),
        )
        # External IDs first: a row deleted without its ir_model_data entry
        # leaves Odoo believing the record still exists.
        cr.execute(
            """
            DELETE FROM ir_model_data
             WHERE model = 'role.plaza_model.access'
               AND res_id IN %s
            """,
            (tuple(drop),),
        )
        cr.execute("DELETE FROM %s WHERE id IN %%s" % TABLE, (tuple(drop),))

        _logger.info(
            "Plaza RBAC: role %s had %s permission lines for %s; merged into "
            "one at the stronger level (%s)",
            role_id,
            len(ids),
            area,
            strongest,
        )


def migrate(cr, version):
    if not version:
        return

    # The ORM has not created these yet; this migration runs before it does.
    for column in ("area", "access_level", "record_types"):
        cr.execute(
            "ALTER TABLE %s ADD COLUMN IF NOT EXISTS %s varchar" % (TABLE, column)
        )

    _convert(cr)
    # Unconditional, so re-running repairs a partly-applied upgrade.
    _deduplicate(cr)

    # Nothing is parked or deleted for lines that could not be converted. `area`
    # is deliberately nullable on the model for exactly this case, so they
    # survive with a blank Area -- visible on the form, reported in the log, and
    # refused the moment anyone edits them.
