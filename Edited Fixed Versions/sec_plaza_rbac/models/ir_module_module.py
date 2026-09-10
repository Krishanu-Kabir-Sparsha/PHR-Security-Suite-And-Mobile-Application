# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Disambiguate module names in the access-matrix picker.

``ir.module.module`` displays as ``shortdesc``, which is not unique. On a stock
Odoo 18 with Sales installed there are two installed modules both labelled
simply "Sales" -- ``sale`` (23 selectable models) and ``sale_management`` (8) --
and nothing on screen to tell them apart. Picking the wrong one silently
produces a role whose Model list is missing most of what the author expected,
and a role catalog that quietly grants the wrong scope is the specific failure
this module exists to prevent.

The label is also not always the one people expect: ``account`` displays as
"Invoicing", not "Accounting".

So the picker shows ``Sales (sale)`` rather than ``Sales``. This is scoped to a
context flag rather than applied globally, because the Apps screen and every
other place a module is named should keep Odoo's own wording.
"""

from odoo import api, models


class IrModuleModule(models.Model):
    _inherit = "ir.module.module"

    @api.depends_context("plaza_show_technical_name")
    def _compute_display_name(self):
        super()._compute_display_name()
        if not self.env.context.get("plaza_show_technical_name"):
            return
        for module in self:
            if module.name and module.display_name:
                module.display_name = "%s (%s)" % (module.display_name, module.name)
