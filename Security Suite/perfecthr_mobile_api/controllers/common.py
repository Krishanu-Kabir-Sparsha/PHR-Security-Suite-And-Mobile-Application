# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Shared plumbing for the mobile endpoints.

Two things live here, and both exist so no individual endpoint has to remember
them.

**Response shape.** The Flutter client's `DioFailureMapper` distrusts server
error text by default and renders only a `user_message` that survives its shape
checks (no tracebacks, no SQL, no `odoo.` strings, nothing over-long). So every
error response is built here, from fixed copy, and the exception's own text is
never forwarded. A traceback that reaches the client would be discarded anyway;
the difference is that here it also never leaves the server.

**Status semantics.** The client's UX branches on the status code:
401 re-authenticate, 403 permission, 404 empty state, 422 validation. In
particular 403 must not be used for "outside your data scope" -- the client
would show a permission wall for a record that simply isn't theirs.
"""

import functools
import json
import logging
from datetime import date, datetime, timezone

from odoo.http import request, Response

_logger = logging.getLogger(__name__)

# Kept in step with the client's ApiHeaders.
CORRELATION_HEADER = "X-Correlation-Id"

# What a token issued on a password alone may still reach.
#
# Everything a user needs in order to get a device enrolled and nothing else:
# what the app can offer them, where enrolment happens, and the ability to sign
# out or refresh. Anything touching their HR data waits until the second factor
# exists.
#
# Matched on a prefix, so /me/authenticators covers the whole enrolment surface
# without listing each path and going stale the moment one is added.
ENROLMENT_ONLY_PATHS = (
    "/api/mobile/v1/me/capabilities",
    "/api/mobile/v1/me/authenticators",
    "/api/mobile/v1/auth/logout",
    "/api/mobile/v1/auth/refresh",
)


def _payload():
    """Parsed JSON body, or an empty dict.

    Endpoints are declared ``type="http"`` rather than ``type="json"`` on
    purpose: Odoo's JSON dispatcher wraps everything in its own
    ``{"jsonrpc": ..., "result"/"error": ...}`` envelope, which is not a REST
    contract and would force the Dio client to unwrap a layer that means
    nothing to it. Reading the body here keeps the wire format plain REST.
    """
    try:
        raw = request.httprequest.get_data(as_text=True)
        if not raw:
            return {}
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _json_default(value):
    """Serialise a value json.dumps cannot handle natively.

    DATETIMES ARE THE WHOLE REASON THIS EXISTS
    ------------------------------------------
    Odoo stores datetimes as naive UTC, and ``str(datetime)`` renders them
    ``"2026-09-26 05:53:00"`` -- no ``T``, no ``Z``, nothing saying which zone
    that is. Every JSON parser worth using reads a timestamp with no offset as
    **local time**, so a client in Dhaka took 05:53 UTC to mean 05:53 local and
    displayed every attendance six hours early.

    The failure mode is what makes it worth this much comment: nothing errors,
    nothing logs, and the times look entirely plausible. It was found by
    noticing a check-in at "5:53 AM" on a phone whose clock read 11:56 AM.

    So every datetime leaves here as unambiguous ISO-8601 UTC with a ``Z``, and
    the client converts. ``date`` (no time) stays a plain ``YYYY-MM-DD``: a
    calendar day has no zone, and giving it one would move it.
    """
    if isinstance(value, datetime):
        # Odoo's datetimes are naive UTC. Stamping the zone is a statement of
        # fact about data already in UTC, not a conversion.
        aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        return aware.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _respond(body, status=200):
    headers = [("Content-Type", "application/json; charset=utf-8")]
    correlation = request.httprequest.headers.get(CORRELATION_HEADER)
    if correlation:
        # Echoed so a mobile report and an Odoo log line can be tied together.
        headers.append((CORRELATION_HEADER, correlation))
    return Response(
        json.dumps(body, default=_json_default), status=status, headers=headers
    )


def ok(data, status=200):
    return _respond(data, status=status)


def fail(status, user_message, code=None, errors=None, log=None):
    """Build an error response from fixed copy.

    ``log`` is written to the server log and never to the body.
    """
    if log:
        _logger.warning("Mobile API %s: %s", status, log)
    body = {"user_message": user_message}
    if code:
        body["code"] = code
    if errors:
        body["errors"] = errors
    return _respond(body, status=status)


def current_ip():
    return request.httprequest.environ.get("REMOTE_ADDR")


def bearer_token():
    """The raw bearer token from the Authorization header, or None."""
    header = request.httprequest.headers.get("Authorization") or ""
    prefix = "Bearer "
    if not header.startswith(prefix):
        return None
    value = header[len(prefix):].strip()
    return value or None


def authenticated(func):
    """Resolve the bearer token and run the endpoint as that Odoo user.

    The route itself is ``auth="public"`` because Odoo's own ``auth="user"``
    means a *session cookie*, which a mobile client does not have. Authorisation
    is not weakened by that: the request is switched to the resolved user with
    ``update_env``, so every ORM call below runs under their real record rules
    and ACLs -- including the Plaza RBAC and Record Freeze guards. Nothing here
    is sudo'd.
    """

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        raw = bearer_token()
        if not raw:
            return fail(
                401,
                "Please sign in again.",
                code="missing_token",
                log="no bearer token presented",
            )
        token = request.env["perfecthr.mobile.token"].sudo().resolve_access(raw)
        if not token:
            # One message for absent, unknown and expired alike. Telling a
            # caller which of the three it was is free reconnaissance.
            return fail(
                401,
                "Your session has expired. Please sign in again.",
                code="invalid_token",
                log="bearer token not resolvable",
            )

        user = token.user_id

        # The Unified Declaration gate (BRD FR-1) is enforced here, and it has
        # to be. sec_declaration_gateway hooks ir.http._dispatch and keys on
        # `request.session.uid`; a bearer-token request carries no session, so
        # that hook never fires for mobile. Left alone, the app would be a way
        # *around* a control whose whole purpose is to be unavoidable -- the
        # opposite of the redirect problem it first looked like.
        #
        # 403 with a machine-readable code, never the gateway's 303 redirect to
        # an HTML page: a JSON client cannot follow that, and would report it as
        # a parse error rather than as "you must sign the declaration".
        try:
            gated = (
                not user._is_declaration_exempt()
                and user.must_accept_declaration
            )
        except AttributeError:
            # sec_declaration_gateway absent or mid-upgrade. Fail open rather
            # than locking every user out of the app over a missing field, and
            # say so loudly in the log.
            _logger.warning(
                "Declaration gate fields unavailable; mobile request allowed "
                "without the check"
            )
            gated = False
        if gated:
            return fail(
                403,
                "Please accept the Unified Declaration before using Perfect "
                "HR. You can do this by signing in on the web.",
                code="declaration_required",
                log="declaration not accepted by %s" % user.login,
            )

        # A token issued on a password alone reaches enrolment and nothing
        # else. Without this the "everyone must confirm on a device" rule would
        # be advice: a user could simply never enrol and carry on working, and
        # the one account most likely to do that is the one with the most
        # access.
        if token.enrolment_required:
            path = request.httprequest.path or ""
            if not any(path.startswith(p) for p in ENROLMENT_ONLY_PATHS):
                return fail(
                    403,
                    "Register a security device before using Perfect HR on "
                    "this phone.",
                    code="enrolment_required",
                    log="enrolment-restricted token used for %s by %s"
                    % (path, user.login),
                )

        # The company is pinned on the token at sign-in, but the user's right
        # to be in it is re-checked on every request rather than trusted from
        # then on. Removing somebody from a company has to take effect on the
        # phone they are already holding; otherwise revoking access would only
        # work at the pace of the refresh cycle, which is up to thirty days.
        company = token.company_id
        if company and company.id not in user.sudo().company_ids.ids:
            token.revoke()
            return fail(
                401,
                "Your access to this company has changed. Please sign in "
                "again.",
                code="company_revoked",
                log="token company %s no longer permitted for %s"
                % (company.id, user.login),
            )

        request.update_env(user=user.id)
        if company:
            # allowed_company_ids is what Odoo's multi-company record rules
            # read. Without it the request runs in the user's *default*
            # company, so somebody who signed into their second employment
            # would be shown the first one's data throughout -- silently, and
            # with every record rule behaving exactly as designed.
            request.update_env(
                context=dict(
                    request.env.context,
                    allowed_company_ids=[company.id],
                )
            )

        # Stashed for request_token/request_company below. Re-resolving it per
        # helper would cost a SELECT *and* a write: resolve_access stamps
        # last_used_at on every call, so three helpers in one endpoint would
        # write that column three times for one request.
        #
        # Set after update_env, because that rebuilds the environment and the
        # recordset has to belong to the one the endpoint will actually use.
        request.mobile_token = token.with_env(request.env)
        return func(self, *args, **kwargs)

    return wrapper


def request_token():
    """The token record for this request, or an empty recordset.

    Only meaningful inside an ``@authenticated`` endpoint, which is what puts
    it there. Falls back to resolving it so that a helper called from anywhere
    else still answers correctly rather than silently reporting no session.
    """
    token = getattr(request, "mobile_token", None)
    if token is not None:
        return token
    return request.env["perfecthr.mobile.token"].sudo().resolve_access(
        bearer_token()
    )


def request_company():
    """The company this request's token is pinned to, or the user's default.

    Endpoints use this rather than ``request.env.company`` so that the answer
    is the one the person chose when they signed in, which is the only reading
    that matches what the app is showing them.
    """
    token = request_token()
    return (token.company_id if token else False) or request.env.user.company_id


def request_employee():
    """The hr.employee for this request, scoped to the session's company.

    One definition of "me", shared by every endpoint. A multi-company tenant
    gives one user an employee record per company, so an unscoped lookup
    returns whichever row the database ordered first -- and every balance,
    payslip and attendance figure drawn from it belongs to the wrong
    employment, with nothing to show that anything went wrong.
    """
    return request.env["perfecthr.mobile.checkin"].employee_for(
        request.env.user, request_company()
    )
