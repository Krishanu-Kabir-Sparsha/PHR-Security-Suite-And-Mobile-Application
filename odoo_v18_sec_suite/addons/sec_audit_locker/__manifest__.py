# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Security Suite - Audit Locker",
    "summary": "Hash-chained, append-only audit trail built on OCA auditlog, "
    "capturing user, UTC timestamp, source IP and field-level before/after.",
    "version": "18.0.1.2.0",
    "category": "Security",
    "license": "AGPL-3",
    "author": "Internal Security Programme",
    "website": "https://example.internal/security-suite",
    "development_status": "Alpha",
    # auditlog is OCA/server-tools @ 18.0 (18.0.2.0.9 verified in P0-4).
    # It must be on the addons path; see README.
    "depends": [
        "sec_core",
        "sec_record_freeze",
        "sec_declaration_gateway",
        "auditlog",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/locker_views.xml",
        "views/replication_views.xml",
        "views/reconciliation_views.xml",
        "data/auditlog_rules.xml",
        "data/cron.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
