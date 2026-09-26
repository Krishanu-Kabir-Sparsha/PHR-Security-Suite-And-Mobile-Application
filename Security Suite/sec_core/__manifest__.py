# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Security Suite - Core",
    "summary": "Shared anomaly alert model and raising mixin for the security suite.",
    # 18.0.1.2.0 - adds _raise_anomaly_out_of_band to the mixin. An alert
    # written on the caller's own cursor immediately before a raise() is
    # rolled back by that raise, which silently destroyed exactly the
    # alerts worth keeping: the ones recording a refused action.
    "version": "18.0.1.2.0",
    "category": "Security",
    "license": "AGPL-3",
    "author": "Internal Security Programme",
    "website": "https://example.internal/security-suite",
    "development_status": "Alpha",
    "depends": ["sec_plaza_rbac"],
    "data": [
        "security/ir.model.access.csv",
        "views/anomaly_alert_views.xml",
        "views/anomaly_review_views.xml",
    ],
    "installable": True,
    "application": False,
}
