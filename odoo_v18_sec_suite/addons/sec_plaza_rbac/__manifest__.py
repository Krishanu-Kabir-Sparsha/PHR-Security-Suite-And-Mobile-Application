# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Security Suite - Plaza Model RBAC",
    "summary": "Bounded role catalog (Plaza Model) with module/field access matrix "
    "and segregation-of-duties checking.",
    "version": "18.0.1.0.0",
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
    ],
    "application": True,
    "installable": True,
    "auto_install": False,
}
