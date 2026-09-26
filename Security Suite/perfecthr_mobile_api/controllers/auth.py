# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Sign-in, refresh and sign-out for the mobile app.

THE ORDER OF THE SIGN-IN, AND WHY IT IS THAT ORDER
--------------------------------------------------
    1.  workspace     the tenant URL, resolved by controllers/tenant.py before
                      this module is ever reached
    2.  company       chosen from what that workspace publishes, or skipped
    3.  method        basic or advanced, within what the company permits
    4.  credentials   work email or Employee ID, plus password
    5.  fingerprint   advanced only: the paired handset signs a challenge
    6.  session       tokens issued, and attendance recorded

Steps 1-3 happen **before** the password field is drawn, and that ordering is
deliberate rather than cosmetic. Each one narrows what the next step means: the
workspace decides which database is being talked to, the company decides which
policy applies, and the policy decides whether a fingerprint is going to be
asked for. A person should know they are about to need their thumb before they
have typed a password, not after.

It also means the password is never posted to a host that has not first
answered "yes, I am a Perfect HR workspace".

WHAT THE TWO METHODS ACTUALLY PROVE
-----------------------------------
*Advanced* is the default and the only one this module used to have. The
password proves knowledge of a secret; the device signature proves possession
of a specific handset whose key was released by a fingerprint. A stolen
password alone buys nothing.

*Basic* is the password by itself. It exists because an organisation running
shared or low-risk roles asked for it, and it is a genuine reduction -- said
plainly here rather than buried. Three things bound it:

* It is offered only where a company's policy says so, and the default policy
  on every company is advanced-only, so an upgrade changes nobody's behaviour.
* It is refused outright for anyone holding an approval tier, the WebAuthn
  flag, or an administrator group -- whatever their company permits. See
  ``res.users._mobile_requires_advance``.
* The session records that it was basic. Anything that later asks "how well was
  this person authenticated" gets a truthful answer instead of assuming.

Approvals are unaffected either way: ``sec_override_engine`` demands a
signature bound to the specific request it is approving, so no session of any
kind is sufficient on its own.

SIGNING IN RECORDS ATTENDANCE
-----------------------------
A completed sign-in checks the employee in, once per day. The rules -- and the
lunch-break case that makes the naive version wrong -- are in
``models/mobile_checkin.py``. It can never fail a sign-in.
"""

import logging

from odoo import http
from odoo.exceptions import AccessDenied
from odoo.http import request

from .common import authenticated, bearer_token, current_ip, fail, ok, _payload

# Binds a sign-in assertion to signing in, and to nothing else. A confirmation
# given to unlock the app must not be replayable as an override approval, which
# is the whole reason challenges carry a context at all.
SIGN_IN_CONTEXT = "perfecthr.mobile.session,login"

AUTH_MODE_BASIC = "basic"
AUTH_MODE_ADVANCE = "advance"

_logger = logging.getLogger(__name__)

# Odoo group -> mobile UserRole wire value, most privileged first. The client's
# UserRole enum is the contract; see lib/core/session/user_role.dart.
ROLE_MAP = [
    ("sec_plaza_rbac.group_security_super_admin", "super_admin"),
    ("sec_plaza_rbac.group_plaza_admin", "hr"),
    ("sec_plaza_rbac.group_plaza_compliance", "hr"),
    ("hr.group_hr_manager", "hr"),
    ("hr.group_hr_user", "hr"),
    ("hr_attendance.group_hr_attendance_manager", "manager"),
]


class MobileAuth(http.Controller):
    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    def _resolve_login(self, identifier):
        """Accept a work email or an Employee ID and return the login to use.

        Two things people know about themselves, and only one of them is what
        Odoo authenticates against. ``hr.employee.identification_id`` is the
        standard Employee ID / badge number -- the same field the biometric
        terminals match their punches on, via ``hr_attendance_gateway`` -- so an
        employee who knows the number on their badge can sign in with it and
        does not have to remember which address HR used.

        The login is tried first and unchanged, so nothing about the existing
        email path changes. Only when no such login exists is the identifier
        treated as a badge number.

        Returns the identifier itself when nothing matches. Resolving to
        ``None`` and refusing early would answer a different question than the
        password check does, and the difference in timing and response is how
        an endpoint becomes a way to test whether an Employee ID exists.
        """
        identifier = (identifier or "").strip()
        if not identifier:
            return identifier

        Users = request.env["res.users"].sudo()
        if Users.search_count([("login", "=", identifier)]):
            return identifier

        employee = (
            request.env["hr.employee"]
            .sudo()
            .search(
                [
                    ("identification_id", "=", identifier),
                    ("user_id", "!=", False),
                ],
                limit=1,
            )
        )
        if employee and employee.user_id.active:
            _logger.info(
                "Mobile sign-in: Employee ID %r resolved to %s",
                identifier,
                employee.user_id.login,
            )
            return employee.user_id.login
        return identifier

    def _resolve_role(self, user):
        """Best available mobile role for this user, defaulting to employee."""
        for xmlid, wire in ROLE_MAP:
            try:
                if user.has_group(xmlid):
                    return wire
            except ValueError:
                # The module that defines that group is not installed here.
                continue
        return "employee"

    # ------------------------------------------------------------------
    # Company and method
    # ------------------------------------------------------------------
    def _resolve_company(self, user, raw_company_id):
        """The company to sign into, or a refusal.

        Returns ``(company, None)`` on success and ``(None, response)`` when the
        request must be refused.

        ``res.users.company_ids`` is the authority for who may sign into what --
        see ``models/res_company.py`` for why this does not maintain a second
        list. An omitted company is not an error: most tenants publish none and
        the app skips the step, in which case the user's own default is used.
        """
        permitted = user._mobile_login_companies()
        if not permitted:
            # A user with no active company cannot have a working session at
            # all; every record rule would resolve against nothing.
            return None, fail(
                403,
                "Your account is not linked to an active company. Please ask "
                "your administrator to check it.",
                code="no_company",
                log="no active company for %s" % user.login,
            )

        if not raw_company_id:
            default = user.sudo().company_id
            return (default if default in permitted else permitted[0]), None

        try:
            company_id = int(raw_company_id)
        except (TypeError, ValueError):
            return None, fail(
                422,
                "That company could not be recognised. Please choose it again.",
                code="invalid_company",
                log="unparseable company_id %r from %s"
                % (raw_company_id, current_ip()),
            )

        company = permitted.filtered(lambda c: c.id == company_id)
        if not company:
            # 403, not 404, and the message names the remedy. Saying "no such
            # company" would confirm whether an id exists to somebody holding a
            # valid password for a different account.
            return None, fail(
                403,
                "You do not have access to that company. Choose one you are "
                "assigned to, or ask your administrator.",
                code="company_not_permitted",
                log="%s attempted to sign into company %s without access"
                % (user.login, company_id),
            )
        return company[0], None

    def _resolve_mode(self, user, company, requested):
        """The sign-in method to use, or a refusal.

        Returns ``(mode, None)`` or ``(None, response)``. The permitted set is
        computed server-side from the company policy intersected with what the
        account itself is allowed -- never from what the app sent. An app that
        asks for ``basic`` on an approver's account is told no here, which is
        the point: the client draws the buttons but does not decide the rule.
        """
        available = user._mobile_auth_modes_for(company)
        requested = (requested or "").strip().lower()

        if not requested:
            # The company's own preference, which is the first entry.
            return available[0], None

        if requested not in (AUTH_MODE_BASIC, AUTH_MODE_ADVANCE):
            return None, fail(
                422,
                "That sign-in method is not one this app offers.",
                code="unknown_auth_mode",
                log="unknown auth_mode %r from %s" % (requested, current_ip()),
            )

        if requested not in available:
            if requested == AUTH_MODE_BASIC:
                return None, fail(
                    403,
                    "This account must sign in with a fingerprint on a paired "
                    "device. Password-only sign-in is not available for it.",
                    code="advance_required",
                    log="basic sign-in refused for %s" % user.login,
                )
            return None, fail(
                403,
                "Advanced sign-in is not available for this company.",
                code="advance_unavailable",
                log="advance sign-in refused for %s" % user.login,
            )
        return requested, None

    # ------------------------------------------------------------------
    # Response building
    # ------------------------------------------------------------------
    def _employment(self, employee):
        """Position and standing, which is the first half of authorisation.

        The app shows who somebody is before it shows what they may do, and
        "Senior Officer, Finance, reporting to X" is what makes a role legible
        to the person holding it. Every field is nullable: a new joiner with a
        half-filled record must still get a working session.
        """
        if not employee:
            return None
        contract = getattr(employee, "contract_id", False)
        return {
            "employee_code": employee.identification_id or None,
            "job_title": employee.job_title or (employee.job_id.name or None),
            "job_position": employee.job_id.name or None,
            "department": employee.department_id.name or None,
            "manager": employee.parent_id.name or None,
            "work_location": employee.work_location_id.name or None,
            "shift": employee.resource_calendar_id.name or None,
            "work_email": employee.work_email or None,
            "work_phone": employee.work_phone or None,
            # Employment standing, from the contract when hr_contract is
            # installed. Absent rather than guessed: "active" asserted about
            # somebody whose contract ended is a worse answer than nothing.
            "employment_status": (contract.state if contract else None),
            "joined_on": str(employee.create_date.date())
            if employee.create_date
            else None,
        }

    def _session_user(self, user, company=None, employee=None):
        """The SessionUser payload the client expects on sign-in."""
        company = company or user.company_id
        if employee is None:
            employee = request.env["perfecthr.mobile.checkin"].employee_for(
                user, company
            )

        role = self._resolve_role(user)
        return {
            # employee_id is the app's stable handle for "me". Falling back to
            # the user id keeps a user without an hr.employee record usable
            # rather than crashing the home screen on a null.
            "employee_id": str(employee.id or user.id),
            "display_name": user.name or user.login,
            "role": role,
            # The workspace, which under dbfilter = ^%h$ is the hostname. This
            # used to report the company id, which conflated two different
            # things: a tenant is a database, a company is an organisation
            # inside it, and a multi-company tenant has one of the former and
            # several of the latter.
            "tenant_id": request.db or request.httprequest.host.split(":")[0],
            "tenant_name": request.env["res.company"].sudo().browse(1).name,
            "company_id": str(company.id),
            "company_name": company.name,
            # Every company this person may switch to without signing out
            # again. Sent so the app can offer the switch rather than making
            # them sign out to change employment.
            "companies": [
                {"id": str(c.id), "name": c.name}
                for c in user._mobile_login_companies()
            ],
            "job_title": employee.job_title or (employee.job_id.name or None),
            "avatar_url": "/web/image/hr.employee/%s/avatar_128" % employee.id
            if employee
            else None,
            "employment": self._employment(employee),
            # Advisory, for menu construction only. The real authorisation
            # surface is GET /me/capabilities, which asks Odoo itself.
            "permissions": sorted(
                {
                    "attendance.self",
                    "leave.self",
                    *(
                        ["team.read"]
                        if role in ("manager", "hr", "super_admin")
                        else []
                    ),
                }
            ),
        }

    def _token_response(self, record, access, refresh, user, attendance=None):
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "Bearer",
            # Seconds, as OAuth-style clients expect.
            "expires_in": int(
                (record.access_expires_at - record.create_date).total_seconds()
            ),
            # The app takes the user straight to enrolment when this is set, and
            # every other endpoint refuses the token until a device exists. Sent
            # explicitly rather than inferred from a 403, so the app can explain
            # why up front instead of after the first thing the user tries.
            "enrolment_required": bool(record.enrolment_required),
            # Which proof produced this session. The app shows it in Settings so
            # somebody can see they are on the weaker footing and change it.
            "auth_mode": record.auth_mode,
            # What signing in did to today's attendance. Always present, always
            # carrying a status -- see models/mobile_checkin.py for the values.
            "attendance": attendance,
            "user": self._session_user(user, record.company_id),
        }

    def _complete_sign_in(self, user, company, auth_mode, device_label,
                          enrolment_required=False):
        """Issue the session and record attendance. The end of every path."""
        record, access, refresh = (
            request.env["perfecthr.mobile.token"]
            .sudo()
            .issue(
                user,
                device_label=device_label,
                source_ip=current_ip(),
                company=company,
                auth_mode=auth_mode,
                enrolment_required=enrolment_required,
            )
        )

        # Not for a session that cannot use the product yet. Somebody stuck on
        # the enrolment screen has not started work, and recording attendance
        # for them would be a punch they cannot see, cannot correct from the
        # app, and did not ask for.
        attendance = None
        if not enrolment_required:
            attendance = (
                request.env["perfecthr.mobile.checkin"]
                .sudo()
                .record_sign_in(
                    user,
                    company=company,
                    source_ip=current_ip(),
                    auth_mode=auth_mode,
                )
            )
        return self._token_response(record, access, refresh, user, attendance)

    # ------------------------------------------------------------------
    # Step 4: credentials
    # ------------------------------------------------------------------
    @http.route(
        "/api/mobile/v1/auth/login",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def login(self, **kwargs):
        """Exchange credentials for a session, or for a device challenge.

        ``save_session=False`` matters: without it Odoo would set a session
        cookie for every API call, and a mobile client that then happened to
        hold a cookie would be authenticated two different ways at once.
        """
        data = _payload() or kwargs
        identifier = (data.get("login") or "").strip()
        password = data.get("password") or ""
        device_label = data.get("device_label")
        requested_mode = data.get("auth_mode")
        raw_company = data.get("company_id")

        if not identifier or not password:
            return fail(
                422,
                "Enter your work email or Employee ID, and your password.",
                code="missing_credentials",
                errors={
                    **({} if identifier else {"login": "Required."}),
                    **({} if password else {"password": "Required."}),
                },
            )

        login = self._resolve_login(identifier)

        try:
            # interactive=False: this is not a browser sign-in, and the
            # interactive path expects a session and a request context it does
            # not have here.
            auth_info = request.env["res.users"].authenticate(
                request.db,
                {"type": "password", "login": login, "password": password},
                {"interactive": False},
            )
        except AccessDenied:
            # Deliberately identical for unknown user, unknown Employee ID and
            # wrong password, and deliberately says nothing about which. The
            # real reason goes to the server log only.
            return fail(
                401,
                "Those sign-in details were not recognised.",
                code="invalid_credentials",
                log="failed login for %r from %s" % (identifier, current_ip()),
            )

        uid = auth_info["uid"] if isinstance(auth_info, dict) else auth_info
        user = request.env["res.users"].sudo().browse(uid).exists()
        if not user or not user.active:
            return fail(
                401,
                "Those sign-in details were not recognised.",
                code="invalid_credentials",
                log="authenticate returned an unusable uid %r" % (uid,),
            )

        # Company and method are settled before any second factor is issued.
        # Getting the refusal here costs the user one round trip; getting it
        # after a fingerprint prompt would have asked for their thumb to reach
        # a door that was never open.
        company, refusal = self._resolve_company(user, raw_company)
        if refusal:
            return refusal

        mode, refusal = self._resolve_mode(user, company, requested_mode)
        if refusal:
            return refusal

        if mode == AUTH_MODE_BASIC:
            _logger.info(
                "Mobile sign-in: %s signed in to %s with a password only",
                user.login,
                company.name,
            )
            return ok(
                self._complete_sign_in(user, company, AUTH_MODE_BASIC, device_label)
            )

        return self._begin_advance(user, company, device_label)

    # ------------------------------------------------------------------
    # Step 5: the device
    # ------------------------------------------------------------------
    def _webauthn(self, user):
        """The credential model acting AS ``user``.

        ``issue_authentication_challenge`` and ``verify_authentication`` both
        work from ``env.user``, and at sign-in nobody is logged in yet. Odoo's
        ``sudo()`` sets the superuser *flag* without changing the uid, so
        ``with_user(user).sudo()`` gives exactly what is needed: the ceremony
        runs as the person signing in, with access checks bypassed because they
        have no session to be checked against yet.
        """
        return request.env["sec.webauthn.credential"].with_user(user).sudo()

    def _begin_advance(self, user, company, device_label):
        """Ask for a device, or sign in and require enrolment.

        Someone who has not enrolled a device yet is signed in anyway and sent
        straight to enrolment, because the alternative locks out the person who
        most needs to get in: a new joiner, or a newly-promoted approver who has
        never had a device to enrol with. The token they get is restricted to
        enrolment until they have one -- see ``enrolment_required`` on the token
        and the gate in ``common.authenticated``.

        A paired app is tried before a passkey, and the order is not a
        preference. The app asking this question *is* the paired device, so its
        own key is reachable with certainty. A passkey is reachable only if the
        platform agrees the app speaks for this domain, which is exactly the
        thing that fails on a handset with no server-side fault to find.
        """
        Credential = self._webauthn(user)

        if Credential.bound_devices_for(user) and Credential._device_binding_ready():
            pending, handle = (
                request.env["perfecthr.mobile.pending.auth"]
                .sudo()
                .open_for(
                    user,
                    device_label=device_label,
                    source_ip=current_ip(),
                    company=company,
                )
            )
            try:
                challenge = Credential.issue_device_challenge(user, SIGN_IN_CONTEXT)
            except Exception:  # noqa: BLE001 - never leak the reason at sign-in
                pending.sudo().unlink()
                _logger.exception(
                    "Could not issue a device challenge for %s", user.login
                )
                return fail(
                    503,
                    "Sign-in is temporarily unavailable. Please try again.",
                    code="challenge_unavailable",
                )
            _logger.info(
                "Mobile sign-in: %s passed the password, awaiting paired device",
                user.login,
            )
            return ok(
                {
                    "mfa_required": True,
                    "mfa_method": "device",
                    "mfa_token": handle,
                    "device_challenge": challenge,
                    "company_name": company.name,
                }
            )

        # Passkeys only from here. Bound devices are excluded because no
        # platform authenticator can satisfy one.
        credentials = Credential.enrolled_for(user).filtered(
            lambda c: c.mechanism == "webauthn"
        )

        if credentials and Credential._verification_ready():
            pending, handle = (
                request.env["perfecthr.mobile.pending.auth"]
                .sudo()
                .open_for(
                    user,
                    device_label=device_label,
                    source_ip=current_ip(),
                    company=company,
                )
            )
            try:
                challenge = Credential.issue_authentication_challenge(
                    context_ref=SIGN_IN_CONTEXT
                )
            except Exception:  # noqa: BLE001 - never leak the reason at sign-in
                pending.sudo().unlink()
                _logger.exception(
                    "Could not issue a sign-in challenge for %s", user.login
                )
                return fail(
                    503,
                    "Sign-in is temporarily unavailable. Please try again.",
                    code="challenge_unavailable",
                )

            _logger.info(
                "Mobile sign-in: %s passed the password, awaiting passkey",
                user.login,
            )
            return ok(
                {
                    "mfa_required": True,
                    "mfa_method": "passkey",
                    "mfa_token": handle,
                    # The client passes this straight to the platform
                    # authenticator; the shape is WebAuthn's, not ours.
                    "challenge": challenge,
                    "company_name": company.name,
                }
            )

        # No device, or no library to verify one with. Either way the second
        # factor cannot happen right now, and refusing would strand the user.
        _logger.info(
            "Mobile sign-in: %s signed in with no enrolled device; token is "
            "restricted to enrolment",
            user.login,
        )
        return ok(
            self._complete_sign_in(
                user,
                company,
                AUTH_MODE_ADVANCE,
                device_label,
                enrolment_required=True,
            )
        )

    def _pending_or_refusal(self, data):
        """Resolve the handle from the first call, or the standard refusal."""
        pending = (
            request.env["perfecthr.mobile.pending.auth"]
            .sudo()
            .resolve(data.get("mfa_token"))
        )
        if not pending:
            # Unknown, expired and already-used are one answer on purpose.
            return None, fail(
                401,
                "That sign-in has expired. Please enter your password again.",
                code="sign_in_expired",
                log="pending sign-in not resolvable from %s" % current_ip(),
            )
        return pending, None

    def _finish_advance(self, pending, verify):
        """Verify the proof and issue the session. Shared by both device paths.

        ``verify`` is a callable raising on failure. The two routes below differ only
        in which proof they check, and that difference belongs on the
        credential rather than duplicated here -- including the attempt limit,
        which must be the same for both or the weaker one becomes the way in.
        """
        user = pending.user_id
        try:
            verify(user)
        except Exception as error:  # noqa: BLE001 - message is user-facing
            still_open = pending.register_failure()
            return fail(
                401,
                str(error)
                if still_open
                else "Too many failed attempts. Please start again.",
                code="device_confirmation_failed",
                log="sign-in proof failed for %s: %s" % (user.login, error),
            )

        device_label = pending.device_label
        company = pending.company_id or user.company_id

        # Re-checked at the moment the session is actually minted. The first
        # call may have been minutes ago, and an administrator who removed
        # somebody from a company in between must not be overtaken by a
        # confirmation that was already in flight.
        if company.id not in user.sudo().company_ids.ids:
            pending.sudo().unlink()
            return fail(
                403,
                "Your access to that company has changed. Please sign in "
                "again.",
                code="company_not_permitted",
                log="company %s revoked for %s mid sign-in"
                % (company.id, user.login),
            )

        pending.sudo().unlink()
        _logger.info(
            "Mobile sign-in: %s confirmed on device from %s",
            user.login,
            current_ip(),
        )
        return ok(
            self._complete_sign_in(
                user, company, AUTH_MODE_ADVANCE, device_label
            )
        )

    @http.route(
        "/api/mobile/v1/auth/login/webauthn",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def login_webauthn(self, **kwargs):
        """Complete a sign-in by confirming with a passkey."""
        data = _payload() or kwargs
        pending, refusal = self._pending_or_refusal(data)
        if refusal:
            return refusal
        return self._finish_advance(
            pending,
            lambda user: self._webauthn(user).verify_authentication(
                data.get("assertion"), context_ref=SIGN_IN_CONTEXT
            ),
        )

    @http.route(
        "/api/mobile/v1/auth/login/device",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def login_device(self, **kwargs):
        """Complete a sign-in with a signature from the paired app.

        The fingerprint happened on the handset: it released the private key
        from the platform keystore, and this signature is the evidence that it
        did. The biometric itself never leaves the device and this server never
        sees it -- which is why there is no fingerprint to store or to lose.
        """
        data = _payload() or kwargs
        pending, refusal = self._pending_or_refusal(data)
        if refusal:
            return refusal
        return self._finish_advance(
            pending,
            lambda user: self._webauthn(user).verify_device_signature(
                user, data.get("signature_payload"), context_ref=SIGN_IN_CONTEXT
            ),
        )

    # ------------------------------------------------------------------
    # Session maintenance
    # ------------------------------------------------------------------
    @http.route(
        "/api/mobile/v1/auth/refresh",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def refresh(self, **kwargs):
        """Exchange a refresh token for a new pair. The old pair is revoked.

        Attendance is deliberately not touched here. A refresh is the app
        renewing a token it already holds, not a person arriving at work, and
        checking somebody in every hour on the hour would produce attendance
        from a phone sitting in a drawer.
        """
        data = _payload() or kwargs
        raw = data.get("refresh_token")
        try:
            record, access, refresh = (
                request.env["perfecthr.mobile.token"].sudo().rotate(raw)
            )
        except AccessDenied:
            return fail(
                401,
                "Please sign in again.",
                code="invalid_refresh_token",
                log="refresh rejected from %s" % current_ip(),
            )
        return ok(
            self._token_response(record, access, refresh, record.user_id)
        )

    @http.route(
        "/api/mobile/v1/auth/logout",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def logout(self, **kwargs):
        """Revoke the presented token.

        Only the token that was presented, not every session for the user: a
        phone signing out should not sign out the tablet.

        Nothing is written to attendance. Signing out is not evidence that
        somebody went home, and a check-out invented from it would shorten
        their paid day without their knowing.
        """
        token = (
            request.env["perfecthr.mobile.token"]
            .sudo()
            .resolve_access(bearer_token())
        )
        if token:
            token.revoke()
        return ok({"ok": True})

    @http.route(
        "/api/mobile/v1/auth/company",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def switch_company(self, **kwargs):
        """Move an existing session to another of the user's companies.

        Issues a **new** token rather than editing the one presented. The
        company is pinned on the token precisely so that it cannot change
        underneath a request, and a switch that mutated it in place would be
        that guarantee quietly removed.

        The new session keeps the proof the old one was issued with: switching
        company is not a way to turn an advanced session into a basic one, nor
        the reverse.
        """
        data = _payload() or kwargs
        user = request.env.user
        old = (
            request.env["perfecthr.mobile.token"]
            .sudo()
            .resolve_access(bearer_token())
        )

        company, refusal = self._resolve_company(user, data.get("company_id"))
        if refusal:
            return refusal

        response = self._complete_sign_in(
            user,
            company,
            old.auth_mode if old else AUTH_MODE_ADVANCE,
            old.device_label if old else None,
            enrolment_required=bool(old and old.enrolment_required),
        )
        if old:
            old.revoke()
        _logger.info("%s switched to company %s", user.login, company.name)
        return ok(response)
