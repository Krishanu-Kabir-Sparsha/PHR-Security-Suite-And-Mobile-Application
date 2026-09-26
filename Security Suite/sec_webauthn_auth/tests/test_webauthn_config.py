# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for the Relying Party preconditions (BRD FR-6.3, PRD dependency 3)."""

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestWebauthnConfig(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Config = cls.env["sec.webauthn.config"]
        cls.Param = cls.env["ir.config_parameter"].sudo()

    def _set_rp(self, rp_id="erp.example.com", origin=""):
        self.Param.set_param("sec_webauthn.rp_id", rp_id)
        self.Param.set_param("sec_webauthn.origin", origin)

    def test_rp_id_ships_empty(self):
        """No safe default exists; guessing one would kill every credential."""
        self.assertFalse(
            self.env.ref("sec_webauthn_auth.param_rp_id").value.strip()
        )

    def test_enrolment_refused_without_rp_id(self):
        self._set_rp(rp_id="")
        with self.assertRaises(UserError) as caught:
            self.Config.check_ready(origin="https://erp.example.com")
        self.assertIn("Relying Party ID", str(caught.exception))

    def test_error_warns_that_rp_id_cannot_change_later(self):
        self._set_rp(rp_id="")
        with self.assertRaises(UserError) as caught:
            self.Config.check_ready()
        self.assertIn("re-enrol", str(caught.exception))

    def test_plain_http_origin_refused(self):
        """Browsers refuse WebAuthn on insecure origins; say so clearly."""
        self._set_rp()
        with self.assertRaises(UserError) as caught:
            self.Config.check_ready(origin="http://192.168.1.10:8069")
        message = str(caught.exception)
        self.assertIn("HTTPS", message)
        self.assertIn("192.168.1.10", message)

    def test_https_origin_accepted(self):
        self._set_rp()
        self.assertTrue(self.Config.check_ready(origin="https://erp.example.com"))

    def test_mismatched_origin_refused(self):
        self._set_rp(origin="https://erp.example.com")
        with self.assertRaises(UserError):
            self.Config.check_ready(origin="https://other.example.com")

    def test_insecure_override_is_off_by_default(self):
        self.assertFalse(self.Config.allow_insecure_origin())

    def test_insecure_override_permits_http_for_local_dev(self):
        self._set_rp()
        self.Param.set_param("sec_webauthn.allow_insecure_origin", "True")
        self.assertTrue(self.Config.check_ready(origin="http://localhost:8069"))
        self.Param.set_param("sec_webauthn.allow_insecure_origin", "False")
