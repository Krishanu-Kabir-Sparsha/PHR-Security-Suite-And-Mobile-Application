# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Pairing this installation of the app to one account.

Deliberately reachable without a bearer token. Pairing is what a *new* phone
does before it can sign in, so requiring a session here would be circular: the
device cannot authenticate until it is paired, and could not pair until it had
authenticated. That circularity is precisely the ordering trap that made the
old flow require a detour through the browser on every new handset.

The code carries the authority instead, and is built to survive being the only
thing standing in the way: minted only from an authenticated web session, valid
ten minutes, usable once, dead after five wrong presentations, and useless on
its own because the account's login must accompany it.

One consequence worth stating rather than discovering: because a wrong
presentation burns an attempt, someone who knows a login can spend a user's
outstanding code by guessing at it five times. That is a nuisance, not a
compromise -- the user presses "Generate a new code" -- and it is the right side
of the trade against letting a code be guessed at indefinitely.
"""

import logging

from odoo import http
from odoo.exceptions import AccessDenied, UserError, ValidationError
from odoo.http import request

from .common import current_ip, fail, ok, _payload

_logger = logging.getLogger(__name__)


class MobileDevicePairing(http.Controller):
    @http.route(
        "/api/mobile/v1/device/pair",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def pair(self, **kwargs):
        """Bind a freshly generated public key to the account naming the code."""
        data = _payload() or kwargs
        login = (data.get("login") or "").strip()
        code = data.get("code") or ""
        public_key = data.get("public_key") or ""
        device_label = data.get("device_label") or ""
        platform = data.get("platform") or ""

        missing = {
            **({} if login else {"login": "Required."}),
            **({} if code else {"code": "Required."}),
        }
        if missing:
            return fail(
                422,
                "Enter your username and the pairing code shown in your "
                "browser.",
                code="missing_pairing_details",
                errors=missing,
            )
        if not public_key:
            return fail(
                422,
                "This device could not create its security key. Check that a "
                "screen lock is set up, then try again.",
                code="missing_public_key",
            )

        try:
            result = (
                request.env["sec.webauthn.credential"]
                .sudo()
                .pair_bound_device(
                    login=login,
                    code=code,
                    public_key=public_key,
                    device_label=device_label,
                    platform=platform,
                )
            )
        except AccessDenied as error:
            # redeem() already made every failure identical; pass its text
            # through because it names the remedy (generate a fresh code).
            return fail(
                401,
                str(error) or "That pairing code is not valid for this account.",
                code="pairing_rejected",
                log="pairing refused for %r from %s" % (login, current_ip()),
            )
        except (UserError, ValidationError) as error:
            return fail(
                422,
                str(error),
                code="pairing_failed",
                log="pairing failed for %r: %s" % (login, error),
            )
        except Exception:  # noqa: BLE001 - never leak internals to an anon caller
            _logger.exception("Unexpected failure pairing a device for %r", login)
            return fail(
                503,
                "Pairing is temporarily unavailable. Please try again.",
                code="pairing_unavailable",
            )

        _logger.info("Device paired for %s from %s", login, current_ip())
        return ok(result)
