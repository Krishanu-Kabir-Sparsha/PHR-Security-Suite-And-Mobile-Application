# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Two-factor sign-in: the state between password and device.

The record under test holds one fact -- "this person proved they know the
password, just now" -- and the tests are about the ways that fact must not be
reusable: not after it expires, not twice, not after somebody has guessed at it
repeatedly, and not in a form that survives a database dump.
"""

from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged

from ..models.mobile_token import token_hash
from ..models.pending_auth import MAX_ATTEMPTS, PENDING_TTL


@tagged("post_install", "-at_install")
class TestPendingAuth(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Pending = self.env["perfecthr.mobile.pending.auth"]
        self.user = self.env["res.users"].create(
            {"name": "Step Up Tester", "login": "stepup.tester@example.internal"}
        )

    def test_handle_is_never_stored(self):
        """The same rule as the access tokens, for the same reason.

        A database dump, a log line or a backup must not contain anything that
        can be replayed into a session.
        """
        record, handle = self.Pending.open_for(self.user)
        self.assertNotEqual(record.token_hash, handle)
        self.assertEqual(record.token_hash, token_hash(handle))
        self.assertFalse(self.Pending.search([("token_hash", "=", handle)]))

    def test_resolves_its_own_handle(self):
        record, handle = self.Pending.open_for(self.user)
        self.assertEqual(self.Pending.resolve(handle), record)

    def test_unknown_and_expired_are_the_same_answer(self):
        """Distinguishing them tells an attacker their password was correct."""
        self.assertFalse(self.Pending.resolve("never-issued"))
        self.assertFalse(self.Pending.resolve(None))

        record, handle = self.Pending.open_for(self.user)
        record.sudo().write(
            {"expires_at": fields.Datetime.now() - timedelta(seconds=1)}
        )
        self.assertFalse(self.Pending.resolve(handle))

    def test_an_expired_handle_is_cleaned_up_when_presented(self):
        record, handle = self.Pending.open_for(self.user)
        record.sudo().write(
            {"expires_at": fields.Datetime.now() - timedelta(seconds=1)}
        )
        self.Pending.resolve(handle)
        self.assertFalse(record.exists())

    def test_retrying_the_password_abandons_the_previous_attempt(self):
        """Two usable handles for one sign-in is one more than is needed."""
        first, first_handle = self.Pending.open_for(self.user)
        _second, second_handle = self.Pending.open_for(self.user)

        self.assertFalse(first.exists())
        self.assertFalse(self.Pending.resolve(first_handle))
        self.assertTrue(self.Pending.resolve(second_handle))

    def test_repeated_failures_end_the_attempt(self):
        """An assertion either verifies or it does not; there is nothing to
        guess, so a run of failures means start again from the password."""
        record, handle = self.Pending.open_for(self.user)
        for _ in range(MAX_ATTEMPTS - 1):
            self.assertTrue(record.register_failure())
            self.assertTrue(record.exists())

        self.assertFalse(record.register_failure())
        self.assertFalse(record.exists())
        self.assertFalse(self.Pending.resolve(handle))

    def test_window_is_short(self):
        """Long enough to find a fingerprint reader, short enough that a stolen
        password plus a stolen handset is a race rather than an opportunity.

        Capped at the WebAuthn challenge lifetime: a longer window here would
        only produce a confusing "challenge expired" after this said it was
        still fine.
        """
        self.assertLessEqual(PENDING_TTL, timedelta(minutes=5))

    def test_purge_removes_only_the_expired(self):
        live, _live_handle = self.Pending.open_for(self.user)
        other = self.env["res.users"].create(
            {"name": "Other", "login": "stepup.other@example.internal"}
        )
        dead, _dead_handle = self.Pending.open_for(other)
        dead.sudo().write(
            {"expires_at": fields.Datetime.now() - timedelta(minutes=1)}
        )

        self.assertEqual(self.Pending.purge_expired(), 1)
        self.assertTrue(live.exists())
        self.assertFalse(dead.exists())


@tagged("post_install", "-at_install")
class TestEnrolmentRestrictedToken(TransactionCase):
    """A token issued on a password alone must not be a working session."""

    def setUp(self):
        super().setUp()
        self.Token = self.env["perfecthr.mobile.token"]
        self.user = self.env["res.users"].create(
            {"name": "No Device", "login": "nodevice@example.internal"}
        )

    def test_a_normal_token_is_not_restricted(self):
        record, _a, _r = self.Token.issue(self.user)
        self.assertFalse(record.enrolment_required)

    def test_the_restriction_is_recorded_on_the_token(self):
        record, _a, _r = self.Token.issue(self.user, enrolment_required=True)
        self.assertTrue(record.enrolment_required)

    def test_the_allowed_paths_cover_enrolment_and_nothing_else(self):
        """The list is what makes the requirement real rather than advice.

        It must reach enrolment -- otherwise the user is stuck with a token that
        cannot do the one thing it exists for -- and must not reach HR data.
        """
        from ..controllers.common import ENROLMENT_ONLY_PATHS

        allowed = lambda path: any(path.startswith(p) for p in ENROLMENT_ONLY_PATHS)

        self.assertTrue(allowed("/api/mobile/v1/me/authenticators"))
        self.assertTrue(allowed("/api/mobile/v1/me/capabilities"))
        self.assertTrue(allowed("/api/mobile/v1/auth/logout"))

        self.assertFalse(allowed("/api/mobile/v1/me/home"))
        self.assertFalse(allowed("/api/mobile/v1/me/leave"))
        self.assertFalse(allowed("/api/mobile/v1/me/attendance"))
        self.assertFalse(allowed("/api/mobile/v1/me/attendance/toggle"))
