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

from odoo.http import request, Response

_logger = logging.getLogger(__name__)

# Kept in step with the client's ApiHeaders.
CORRELATION_HEADER = "X-Correlation-Id"


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


def _respond(body, status=200):
    headers = [("Content-Type", "application/json; charset=utf-8")]
    correlation = request.httprequest.headers.get(CORRELATION_HEADER)
    if correlation:
        # Echoed so a mobile report and an Odoo log line can be tied together.
        headers.append((CORRELATION_HEADER, correlation))
    return Response(
        json.dumps(body, default=str), status=status, headers=headers
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

        request.update_env(user=user.id)
        return func(self, *args, **kwargs)

    return wrapper
