# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Perfect HR - Mobile API",
    "summary": "Bearer-token REST endpoints shaped for the Perfect HR mobile app.",
    # 18.0.1.12.0 - the sign-in gains the three steps that come before the
    # password: the workspace (which under dbfilter = ^%h$ is the hostname and
    # therefore the tenant), the company, and the method. Adds
    # /tenant/resolve and /tenant/companies so the app can be pointed at a
    # workspace at run time instead of shipping one compiled in; accepts an
    # Employee ID as well as a work email; pins the chosen company on the
    # token; records attendance on the first sign-in of the day.
    #
    #   FIXED HERE, and it was exploitable: token rotation did not carry
    #   enrolment_required forward, so a token restricted to enrolment became
    #   an unrestricted one on its first refresh -- and /auth/refresh is on the
    #   enrolment allow-list. Anybody could reach every endpoint without ever
    #   enrolling a device. See models/mobile_token.rotate.
    #
    # 18.0.1.11.0 - /me/authenticators reports each credential's mechanism and
    # how many paired apps the account has. The app could not tell a paired
    # phone from a synced passkey in its own device list, and so kept offering
    # a native passkey ceremony that cannot complete on Android.
    # 18.0.1.10.0 - sign-in and approvals accept a paired app's signature, not
    # only a passkey. /device/pair is public by necessity: a new handset cannot
    # authenticate until it is paired, so requiring a token there would be
    # circular. The pairing code carries the authority instead.
    # 18.0.1.13.0 - check-in/out made correct and consistent with the web.
    #   * datetimes go out as ISO-8601 UTC with a Z. They were naive
    #     ("2026-09-26 05:53:00"), which every client reads as LOCAL -- so the
    #     app showed every attendance six hours early in Dhaka, silently.
    #   * one definition of "checked in", shared by /me/home, /me/attendance
    #     and the toggle. They had three, and they disagreed across midnight.
    #   * a day's sessions come back chronological; a descending list made the
    #     app print a two-session day as "5:57 AM -> 5:53 AM".
    #   * a session left open on an earlier day is its own state rather than a
    #     raw constraint error after the fact, with /me/attendance/resolve-stale
    #     to close it at the end of the day it belongs to.
    "version": "18.0.1.13.0",
    "category": "Human Resources",
    "license": "AGPL-3",
    "author": "Internal Security Programme",
    "website": "https://example.internal/perfect-hr",
    "development_status": "Alpha",
    # hr_holidays brings hr; hr_attendance is what the home screen's TODAY
    # section reads, and what the sign-in check-in writes to.
    # sec_declaration_gateway is a real dependency, not a courtesy: its ir.http
    # override has to learn about /api paths or every mobile request from a
    # user who has not signed the declaration is answered with an HTML redirect
    # a JSON client cannot parse.
    "depends": [
        "hr",
        "hr_attendance",
        "hr_holidays",
        "sec_declaration_gateway",
        # authenticators.py reads sec.webauthn.credential/config to report
        # enrolment status and hand the app the enrolment URL; the sign-in
        # reads the role catalog through sec_plaza_rbac, which this brings in
        # transitively, to decide who may never use the basic path.
        "sec_webauthn_auth",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/mobile_token_rules.xml",
        "data/ir_cron.xml",
        "views/res_company_views.xml",
        "views/mobile_menus.xml",
    ],
    "installable": True,
    "application": False,
}
