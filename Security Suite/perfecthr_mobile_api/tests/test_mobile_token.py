# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Token lifecycle: issue, resolve, rotate, revoke, purge."""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessDenied
from odoo.tests import TransactionCase, tagged

from ..models.mobile_token import token_hash


@tagged("post_install", "-at_install")
class TestMobileToken(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Token = self.env["perfecthr.mobile.token"]
        self.user = self.env["res.users"].create(
            {
                "name": "Mobile Tester",
                "login": "mobile.tester@example.internal",
                "password": "correct-horse-battery-staple",
            }
        )

    def test_plaintext_is_never_stored(self):
        """The whole point of hashing: the table must not hold the token."""
        record, access, refresh = self.Token.issue(self.user)
        self.assertNotEqual(record.access_hash, access)
        self.assertNotEqual(record.refresh_hash, refresh)
        self.assertEqual(record.access_hash, token_hash(access))
        # And a search for the plaintext finds nothing.
        self.assertFalse(self.Token.search([("access_hash", "=", access)]))

    def test_resolve_returns_the_owner(self):
        _record, access, _refresh = self.Token.issue(self.user)
        self.assertEqual(self.Token.resolve_access(access).user_id, self.user)

    def test_resolve_rejects_unknown_and_empty(self):
        self.assertFalse(self.Token.resolve_access("not-a-token"))
        self.assertFalse(self.Token.resolve_access(None))
        self.assertFalse(self.Token.resolve_access(""))

    def test_expired_access_token_does_not_resolve(self):
        record, access, _refresh = self.Token.issue(self.user)
        record.sudo().write(
            {"access_expires_at": fields.Datetime.now() - timedelta(minutes=1)}
        )
        self.assertFalse(self.Token.resolve_access(access))

    def test_revoked_token_does_not_resolve(self):
        record, access, _refresh = self.Token.issue(self.user)
        record.revoke()
        self.assertFalse(self.Token.resolve_access(access))

    def test_rotation_revokes_the_old_pair(self):
        """A refresh token must not survive its own use.

        If it did, anyone who captured it could replay it, and the legitimate
        client would not notice because its own token still worked.
        """
        old, old_access, old_refresh = self.Token.issue(self.user)
        _new, new_access, new_refresh = self.Token.rotate(old_refresh)

        self.assertFalse(old.active)
        self.assertFalse(self.Token.resolve_access(old_access))
        self.assertTrue(self.Token.resolve_access(new_access))
        self.assertNotEqual(new_refresh, old_refresh)

        # And the spent refresh token cannot be used a second time.
        with self.assertRaises(AccessDenied):
            self.Token.rotate(old_refresh)

    def test_rotation_rejects_unknown_refresh(self):
        with self.assertRaises(AccessDenied):
            self.Token.rotate("not-a-refresh-token")

    def test_archiving_a_user_ends_their_sessions(self):
        """A departed employee's phone must stop working immediately."""
        _record, _access, refresh = self.Token.issue(self.user)
        self.user.sudo().write({"active": False})
        with self.assertRaises(AccessDenied):
            self.Token.rotate(refresh)

    def test_purge_removes_only_dead_rows(self):
        live, _a1, _r1 = self.Token.issue(self.user)
        dead, _a2, _r2 = self.Token.issue(self.user)
        dead.sudo().write(
            {"refresh_expires_at": fields.Datetime.now() - timedelta(days=1)}
        )
        self.Token.cron_purge_expired()
        self.assertTrue(live.exists())
        self.assertFalse(dead.exists())

    def test_purge_keeps_a_revoked_but_unexpired_row(self):
        """Revocations stay visible for their lifetime, for the audit trail."""
        record, _a, _r = self.Token.issue(self.user)
        record.revoke()
        self.Token.cron_purge_expired()
        self.assertTrue(record.exists())

    def test_tokens_are_distinct_per_issue(self):
        _r1, a1, f1 = self.Token.issue(self.user)
        _r2, a2, f2 = self.Token.issue(self.user)
        self.assertNotEqual(a1, a2)
        self.assertNotEqual(f1, f2)
