# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Attach the freeze mixin to the in-scope models.

Scope is Sales, Purchase and Accounting (BRD Section 4.1). Line models are
included deliberately: freezing a Sales Order's total while leaving its lines
editable would be theatre, since editing a line recomputes the total.
"""

from odoo import models


class SaleOrder(models.Model):
    _name = "sale.order"
    _inherit = ["sale.order", "sec.record.freeze.mixin"]


class SaleOrderLine(models.Model):
    _name = "sale.order.line"
    _inherit = ["sale.order.line", "sec.record.freeze.mixin"]


class PurchaseOrder(models.Model):
    _name = "purchase.order"
    _inherit = ["purchase.order", "sec.record.freeze.mixin"]


class PurchaseOrderLine(models.Model):
    _name = "purchase.order.line"
    _inherit = ["purchase.order.line", "sec.record.freeze.mixin"]


class AccountMove(models.Model):
    _name = "account.move"
    _inherit = ["account.move", "sec.record.freeze.mixin"]


class AccountMoveLine(models.Model):
    _name = "account.move.line"
    _inherit = ["account.move.line", "sec.record.freeze.mixin"]
