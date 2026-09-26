# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Security Suite - Plaza Model RBAC",
    "summary": "Bounded role catalog with area-based permissions and "
    "segregation-of-duties checking.",
    # 18.0.1.5.0 - a permission is now one area and one level. The module,
    # record type, four permission checkboxes, transaction class and capability
    # it replaced are all derived, and the role's permissions now confer access
    # directly instead of only describing it. migrations/18.0.1.5.0 converts
    # existing lines; see its docstring for why it must run pre-ORM.
    "version": "18.0.1.5.0",
    "category": "Security",
    "license": "AGPL-3",
    "author": "Internal Security Programme",
    "website": "https://example.internal/security-suite",
    "development_status": "Alpha",
    "depends": [
        "base",
        "mail",
    ],
    "data": [
        "security/security_groups.xml",
        "security/ir.model.access.csv",
        "views/plaza_role_views.xml",
        "views/grant_exception_views.xml",
        "views/sod_views.xml",
        "views/menus.xml",
        "data/plaza_role_data.xml",
        "data/plaza_role_hr_data.xml",
    ],
    "application": True,
    "installable": True,
    "auto_install": False,
}
