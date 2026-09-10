# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Security Suite - Record Freeze",
    "summary": "Freezes Sales, Purchase and Accounting records once confirmed, "
    "posted or done, for every role including administrators.",
    "version": "18.0.1.1.0",
    "category": "Security",
    "license": "AGPL-3",
    "author": "Internal Security Programme",
    "website": "https://example.internal/security-suite",
    "development_status": "Alpha",
    # sec_plaza_rbac is already implied by sec_core, but freeze_mixin imports
    # install_guard from it in Python, so name it explicitly.
    "depends": ["sec_plaza_rbac", "sec_core", "sale", "purchase", "account"],
    "data": [
        "security/ir.model.access.csv",
        "views/freeze_rule_views.xml",
        "views/stream_lock_views.xml",
        "data/freeze_rule_data.xml",
        "data/stream_lock_data.xml",
    ],
    "post_init_hook": "post_init_hook",
    "uninstall_hook": "uninstall_hook",
    "installable": True,
    "application": False,
}
