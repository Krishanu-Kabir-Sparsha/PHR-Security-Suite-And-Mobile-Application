# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for the declaration sign-off gateway (PRD US-1.1)."""

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDeclarationGateway(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Version = cls.env["declaration.version"]
        cls.Signoff = cls.env["declaration.signoff"]
        cls.user = cls.env["res.users"].create(
            {"name": "Declaration Test User", "login": "decl_test_user"}
        )

    def _make_version(self, version="1.0", body="<p>Approved text.</p>", publish=True):
        record = self.Version.create(
            {
                "name": "Unified Declaration %s" % version,
                "version": version,
                "body_html": body,
                "approved_by_legal": True,
                "legal_reviewer": "Test Counsel",
            }
        )
        if publish:
            record.action_publish()
        return record

    def _accept(self, user, version):
        return self.Signoff.create(
            {
                "user_id": user.id,
                "version_id": version.id,
                "declaration_version": version.version,
                "text_hash": version.text_hash,
            }
        )

    # --- AC: acceptance captures user, timestamp, and a text hash ----------
    def test_signoff_captures_user_timestamp_and_hash(self):
        version = self._make_version()
        signoff = self._accept(self.user, version)
        self.assertEqual(signoff.user_id, self.user)
        self.assertTrue(signoff.accepted_at)
        self.assertEqual(signoff.text_hash, version.text_hash)
        self.assertTrue(signoff.hash_matches_version)

    def test_hash_changes_with_text(self):
        one = self._make_version("1.0", "<p>First.</p>", publish=False)
        two = self._make_version("2.0", "<p>Second.</p>", publish=False)
        self.assertNotEqual(one.text_hash, two.text_hash)

    def test_hash_is_stable_for_identical_text(self):
        version = self._make_version("1.0", publish=False)
        original = version.text_hash
        version.invalidate_recordset()
        self.assertEqual(version.text_hash, original)

    # --- AC: gate blocks until accepted ------------------------------------
    def test_user_must_accept_when_version_published(self):
        self._make_version()
        self.user.invalidate_recordset()
        self.assertTrue(self.user.must_accept_declaration)

    def test_user_clear_after_acceptance(self):
        version = self._make_version()
        self._accept(self.user, version)
        self.user.invalidate_recordset()
        self.assertFalse(self.user.must_accept_declaration)

    def test_no_published_version_locks_nobody_out(self):
        """A fresh install must not block every user before Legal supplies text."""
        self.env["declaration.version"].search(
            [("state", "=", "published")]
        ).write({"state": "superseded"})
        self.user.invalidate_recordset()
        self.assertFalse(self.user.must_accept_declaration)

    # --- AC: re-acceptance triggered by a version change -------------------
    def test_new_version_forces_reacceptance(self):
        first = self._make_version("1.0")
        self._accept(self.user, first)
        self.user.invalidate_recordset()
        self.assertFalse(self.user.must_accept_declaration)

        self._make_version("2.0", "<p>Updated text.</p>")
        self.user.invalidate_recordset()
        self.assertTrue(self.user.must_accept_declaration)

    def test_publishing_supersedes_previous_version(self):
        first = self._make_version("1.0")
        self._make_version("2.0")
        first.invalidate_recordset()
        self.assertEqual(first.state, "superseded")
        self.assertEqual(
            self.Version.search_count([("state", "=", "published")]), 1
        )

    # --- Governance --------------------------------------------------------
    def test_cannot_publish_without_legal_approval(self):
        record = self.Version.create(
            {
                "name": "Unapproved",
                "version": "9.9",
                "body_html": "<p>Draft.</p>",
                "approved_by_legal": False,
            }
        )
        with self.assertRaises(UserError):
            record.action_publish()

    def test_shipped_placeholder_is_not_published(self):
        placeholder = self.env.ref(
            "sec_declaration_gateway.declaration_version_placeholder"
        )
        self.assertEqual(placeholder.state, "draft")
        self.assertFalse(placeholder.approved_by_legal)

    def test_text_cannot_change_after_someone_accepted(self):
        version = self._make_version()
        self._accept(self.user, version)
        with self.assertRaises(UserError):
            version.body_html = "<p>Silently altered.</p>"

    def test_signoff_cannot_be_modified(self):
        version = self._make_version()
        signoff = self._accept(self.user, version)
        with self.assertRaises(UserError):
            signoff.write({"source_ip": "1.2.3.4"})

    def test_signoff_cannot_be_deleted(self):
        version = self._make_version()
        signoff = self._accept(self.user, version)
        with self.assertRaises(UserError):
            signoff.unlink()

    def test_duplicate_signoff_rejected(self):
        version = self._make_version()
        self._accept(self.user, version)
        with self.assertRaises(Exception):
            self._accept(self.user, version)

    def test_administrators_are_not_exempt_from_the_gate(self):
        """The BRD threat model is an admin acting on informal instruction."""
        admin = self.env.ref("base.user_admin")
        self.assertFalse(admin._is_declaration_exempt())

    def test_superuser_is_exempt_so_cron_and_install_still_work(self):
        root = self.env.ref("base.user_root")
        self.assertTrue(root._is_declaration_exempt())

    # --- Gate path logic ---------------------------------------------------
    def test_gated_and_allowlisted_paths(self):
        IrHttp = self.env["ir.http"]
        self.assertTrue(IrHttp._is_declaration_gated_path("/odoo/sales"))
        self.assertTrue(IrHttp._is_declaration_gated_path("/web/dataset/call_kw"))
        self.assertFalse(IrHttp._is_declaration_gated_path("/declaration/pending"))
        self.assertFalse(IrHttp._is_declaration_gated_path("/web/login"))
        self.assertFalse(IrHttp._is_declaration_gated_path("/web/session/logout"))
        self.assertFalse(IrHttp._is_declaration_gated_path("/web/assets/1/web.assets.js"))
