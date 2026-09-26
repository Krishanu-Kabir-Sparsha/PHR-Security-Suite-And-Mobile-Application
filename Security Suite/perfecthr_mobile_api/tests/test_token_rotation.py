# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""What a refresh must carry forward, and must never grant.

A refresh renews a session. It is not a second sign-in, and it must not be able
to produce a session stronger than the one it replaces. Until 18.0.1.12.0 it
could, and the consequence was not theoretical -- see the first test.
"""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestTokenRotation(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Token = self.env["perfecthr.mobile.token"]
        self.alpha = self.env["res.company"].create({"name": "Rotation Alpha"})
        self.beta = self.env["res.company"].create({"name": "Rotation Beta"})
        self.user = self.env["res.users"].create(
            {
                "name": "Rotation Tester",
                "login": "rotation.tester@example.internal",
                "password": "correct-horse-battery-staple",
                "company_id": self.alpha.id,
                "company_ids": [(6, 0, [self.alpha.id, self.beta.id])],
            }
        )

    def test_refresh_cannot_lift_the_enrolment_restriction(self):
        """REGRESSION. This was exploitable, and trivially so.

        A user with no enrolled device is signed in with a token restricted to
        the enrolment endpoints -- which include /auth/refresh, necessarily,
        because a token that cannot be renewed expires mid-enrolment.

        Rotation did not carry ``enrolment_required`` forward, so the
        replacement was issued with the field's default of False. One call to
        an endpoint the restriction explicitly permits removed the restriction.
        Every "you must enrol a device" gate in the product was one refresh
        away from being advice, and the account most likely to take that route
        is the one most reluctant to enrol.
        """
        record, _access, refresh = self.Token.issue(
            self.user, enrolment_required=True
        )
        self.assertTrue(record.enrolment_required)

        replacement, _new_access, _new_refresh = self.Token.rotate(refresh)
        self.assertTrue(
            replacement.enrolment_required,
            "a refresh promoted an enrolment-restricted token to a full one",
        )

    def test_refresh_cannot_promote_basic_to_advanced(self):
        """Otherwise a password-only session becomes an advanced one in an hour.

        ``auth_mode`` defaults to 'advance', so a basic session that did not
        carry its mode forward would be *reported* as advanced from its first
        refresh -- and anything trusting that distinction would start trusting
        a session that only ever proved a password.
        """
        record, _access, refresh = self.Token.issue(
            self.user, company=self.alpha, auth_mode="basic"
        )
        self.assertEqual(record.auth_mode, "basic")

        replacement, _a, _r = self.Token.rotate(refresh)
        self.assertEqual(replacement.auth_mode, "basic")

    def test_refresh_keeps_the_session_in_its_own_company(self):
        """A pinned company that reverted to the default would move the session.

        The user here may use both companies, so nothing would be refused --
        the session would simply start showing the other employment's data,
        with every record rule behaving exactly as designed.
        """
        record, _access, refresh = self.Token.issue(
            self.user, company=self.beta, auth_mode="advance"
        )
        self.assertEqual(record.company_id, self.beta)
        self.assertNotEqual(self.user.company_id, self.beta)

        replacement, _a, _r = self.Token.rotate(refresh)
        self.assertEqual(replacement.company_id, self.beta)

    def test_the_old_pair_is_dead_after_rotation(self):
        """Rotation is not optional; a reusable refresh token is replayable."""
        _record, _access, refresh = self.Token.issue(self.user)
        self.Token.rotate(refresh)

        from odoo.exceptions import AccessDenied

        with self.assertRaises(AccessDenied):
            self.Token.rotate(refresh)

    def test_issue_pins_a_company_even_when_none_is_given(self):
        """A session with no company would resolve record rules against nothing."""
        record, _a, _r = self.Token.issue(self.user)
        self.assertEqual(record.company_id, self.user.company_id)
