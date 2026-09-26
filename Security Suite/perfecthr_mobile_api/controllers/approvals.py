# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Override approvals, on the phone.

This is the reason the whole native-passkey path exists. An override changes a
frozen record, so every approval is gated on a verified WebAuthn assertion bound
to that one request -- and a workflow that bounced to a browser for each
signature is one nobody would use.

**Nothing here decides anything.** Listing, approving and rejecting all run
through ``override.request``'s own methods as the real user, so the tier order,
the reviewer membership, the collusion checks and the append-only evidence
record behave exactly as they do on the web. A second implementation of "may
this person approve this" is the last thing a control like this needs.

Three properties are load-bearing and easy to lose:

* **The assertion is bound to one request.** ``_webauthn_context_ref`` is
  ``override.request,<id>``, so a confirmation given for one override cannot
  approve another -- nor can a sign-in confirmation approve anything at all.
* **It is verified in the same request that approves.** The marker lives on the
  request object, deliberately: an assertion authorises one action once, not
  everything the user does for the rest of the day.
* **Rejection is not gated.** FR-5.3 requires strong authentication for
  approvals. A rejection cannot change a frozen record, and putting a hardware
  ceremony between a reviewer and "no" would discourage the safe answer.
"""

import logging

from odoo import http
from odoo.http import request

from .common import authenticated, fail, ok, _payload

_logger = logging.getLogger(__name__)

# How many pending approvals a phone will render. An approver with more than
# this has a queue problem that a longer list does not solve, and an unbounded
# read is how a mobile endpoint becomes a slow one.
MAX_PENDING = 50


class MobileApprovals(http.Controller):
    def _requests_model(self):
        """``override.request``, or None when the module is not installed.

        The mobile API does not depend on sec_override_engine: a deployment can
        run Perfect HR without the override workflow, and the app degrades to
        not offering approvals rather than failing to start.
        """
        return request.env.get("override.request")

    def _serialise(self, record, review):
        return {
            "id": str(record.id),
            "reference": record.name,
            "target": record.target_display or record.res_model,
            "justification": record.justification or None,
            "reason": record.reason_category_id.name or None,
            "requested_by": record.requester_id.name,
            "submitted_at": record.submitted_at,
            "high_risk": bool(record.high_risk),
            "tier_name": review.definition_id.name
            if review and review.definition_id
            else None,
            "tier_sequence": review.sequence if review else None,
            # What the client must echo back with the assertion. Never derived
            # on the client: it is the binding between a fingerprint and one
            # specific override, and a client that computed it could bind a
            # confirmation to the wrong thing.
            "context_ref": "override.request,%s" % record.id,
        }

    @http.route(
        "/api/mobile/v1/me/approvals",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def approvals(self, **kwargs):
        """Overrides awaiting *this* user, at *their* tier, right now."""
        Requests = self._requests_model()
        if Requests is None:
            # Not an error. The app reads this to hide the tab entirely rather
            # than showing an empty list that will never fill.
            return ok({"available": False, "requests": []})

        user = request.env.user
        pending = Requests.search([("state", "=", "pending")], limit=200)

        items = []
        for record in pending:
            # Asking the record itself, rather than filtering on reviewer ids,
            # so tier order is respected: a Tier 3 approver must not see a
            # request still waiting on Tier 1.
            review = record._pending_tier_for(user)
            if not review:
                continue
            items.append(self._serialise(record, review[0]))
            if len(items) >= MAX_PENDING:
                break

        return ok({"available": True, "requests": items})

    @http.route(
        "/api/mobile/v1/me/approvals/<int:request_id>/challenge",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def challenge(self, request_id, **kwargs):
        """A WebAuthn challenge bound to this one override."""
        Requests = self._requests_model()
        if Requests is None:
            return fail(404, "Approvals are not available on this server.",
                        code="approvals_unavailable")

        record = Requests.browse(request_id).exists()
        if not record or not record._pending_tier_for(request.env.user):
            # 404 rather than 403: whether an override the user cannot act on
            # exists is not their business, and a 403 would confirm that it
            # does.
            return fail(
                404,
                "That approval is no longer waiting for you.",
                code="approval_not_found",
                log="override %s not pending for %s"
                % (request_id, request.env.user.login),
            )

        Credential = request.env["sec.webauthn.credential"]
        context_ref = record._webauthn_context_ref()
        user = request.env.user

        # Same order as sign-in, for the same reason: the app holding this
        # screen is the paired device, so its own key is certain to be
        # reachable. See MobileAuth._begin_or_complete.
        if Credential.bound_devices_for(user) and Credential._device_binding_ready():
            try:
                challenge = Credential.issue_device_challenge(user, context_ref)
            except Exception as error:  # noqa: BLE001 - message is user-facing
                return fail(
                    422,
                    str(error),
                    code="challenge_unavailable",
                    log="approval device challenge failed: %s" % error,
                )
            return ok({"method": "device", "device_challenge": challenge})

        try:
            options = Credential.issue_authentication_challenge(
                context_ref=context_ref
            )
        except Exception as error:  # noqa: BLE001 - message is user-facing
            return fail(
                422,
                str(error),
                code="challenge_unavailable",
                log="approval challenge failed: %s" % error,
            )
        return ok({"method": "passkey", "options": options})

    @http.route(
        "/api/mobile/v1/me/approvals/<int:request_id>/approve",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def approve(self, request_id, **kwargs):
        """Approve, with the assertion verified in this same request."""
        Requests = self._requests_model()
        if Requests is None:
            return fail(404, "Approvals are not available on this server.",
                        code="approvals_unavailable")

        record = Requests.browse(request_id).exists()
        if not record:
            return fail(404, "That approval is no longer waiting for you.",
                        code="approval_not_found")

        data = _payload() or kwargs
        assertion = data.get("assertion")
        signature = data.get("signature_payload")
        if not assertion and not signature:
            return fail(
                422,
                "Confirm on your security device to approve.",
                code="assertion_required",
            )

        Credential = request.env["sec.webauthn.credential"]
        context_ref = record._webauthn_context_ref()
        marked = False
        try:
            if signature:
                # Sets the same request marker the passkey path sets, which is
                # what override_approval._assert_webauthn_confirmed reads. The
                # engine stays unaware of which mechanism answered; the
                # credential's own `mechanism` field is where that is recorded,
                # so the evidence never overstates the proof.
                Credential.verify_device_signature(
                    request.env.user, signature, context_ref=context_ref
                )
            else:
                Credential.verify_authentication(
                    assertion, context_ref=context_ref
                )
            request.sec_webauthn_verified_for = context_ref
            marked = True
            # As the user, never sudo: tier order, reviewer membership and the
            # collusion checks all read env.user, and an approval recorded as
            # somebody else is worse than no approval at all.
            record.validate_tier()
        except Exception as error:  # noqa: BLE001 - message is user-facing
            return fail(
                422,
                str(error),
                code="approval_rejected",
                log="override %s approval failed for %s: %s"
                % (request_id, request.env.user.login, error),
            )
        finally:
            if marked:
                request.sec_webauthn_verified_for = None

        record.invalidate_recordset(["state"])
        _logger.warning(
            "Override %s approved from mobile by %s",
            record.name,
            request.env.user.login,
        )
        return ok({"id": str(record.id), "state": record.state})

    @http.route(
        "/api/mobile/v1/me/approvals/<int:request_id>/reject",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def reject(self, request_id, **kwargs):
        """Reject. Deliberately not gated on a device.

        Strong authentication is required for approvals because an approval can
        change a frozen record. A rejection cannot, and demanding a fingerprint
        to say "no" would put friction on the safe answer. The decision is still
        recorded with actor, time and IP.
        """
        Requests = self._requests_model()
        if Requests is None:
            return fail(404, "Approvals are not available on this server.",
                        code="approvals_unavailable")

        record = Requests.browse(request_id).exists()
        if not record:
            return fail(404, "That approval is no longer waiting for you.",
                        code="approval_not_found")

        try:
            record.reject_tier()
        except Exception as error:  # noqa: BLE001 - message is user-facing
            return fail(
                422,
                str(error),
                code="rejection_rejected",
                log="override %s rejection failed: %s" % (request_id, error),
            )

        record.invalidate_recordset(["state"])
        _logger.warning(
            "Override %s rejected from mobile by %s",
            record.name,
            request.env.user.login,
        )
        return ok({"id": str(record.id), "state": record.state})
