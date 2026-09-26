# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for high-value field thresholds (P3-2, US-7.1 third bullet)."""

import json
from datetime import datetime

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestValueThresholds(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Threshold = cls.env["sec.value.threshold"]
        cls.Locker = cls.env["audit.locker.entry"]
        cls.Alert = cls.env["anomaly.alert"]
        # In-hours so out-of-hours alerts do not confuse the counts.
        param = cls.env["ir.config_parameter"].sudo()
        param.set_param("sec_surveillance.timezone", "UTC")
        param.set_param("sec_surveillance.out_of_hours_enabled", "False")

    def _threshold(self, **kwargs):
        vals = {
            "model_name": "account.move",
            "field_name": "amount_total",
            "threshold_amount": 50000.0,
            "comparison_mode": "delta",
        }
        vals.update(kwargs)
        return self.Threshold.create(vals)

    def _entry(self, changes, model_name="account.move"):
        return self.Locker.append(
            {
                "user_id": self.env.user.id,
                "user_login": self.env.user.login,
                "model_name": model_name,
                "res_id": 1,
                "record_label": "INV/0001",
                "action_type": "write",
                "timestamp_utc": datetime(2026, 9, 3, 11, 0, 0),
                "field_changes": json.dumps(changes, sort_keys=True),
            }
        )

    def _high_value_count(self):
        return self.Alert.sudo().search_count(
            [("alert_type", "=", "high_value_edit")]
        )

    # --- No defaults shipped -----------------------------------------------
    def test_no_thresholds_ship_by_default(self):
        """An invented figure would look like a decision nobody made."""
        self.assertFalse(
            self.Threshold.search_count([]),
            "Default thresholds were shipped; PRD Section 12 leaves the "
            "figures to the business.",
        )

    def test_coverage_report_says_so_plainly(self):
        report = self.Threshold.coverage_report()
        self.assertFalse(report["any_configured"])
        self.assertIn("no edit will ever be flagged", report["message"].lower())

    def test_nothing_fires_without_a_threshold(self):
        before = self._high_value_count()
        self._entry({"amount_total": {"old": "100", "new": "9999999"}})
        self.assertEqual(self._high_value_count(), before)

    # --- Comparison modes ---------------------------------------------------
    def test_delta_mode_fires_on_a_large_change(self):
        self._threshold(comparison_mode="delta", threshold_amount=50000)
        before = self._high_value_count()
        self._entry({"amount_total": {"old": "1000", "new": "80000"}})
        self.assertGreater(self._high_value_count(), before)

    def test_delta_mode_ignores_a_small_change_to_a_large_number(self):
        """1,000,000 to 1,001,000 is a small delta; that is the point."""
        self._threshold(comparison_mode="delta", threshold_amount=50000)
        before = self._high_value_count()
        self._entry({"amount_total": {"old": "1000000", "new": "1001000"}})
        self.assertEqual(self._high_value_count(), before)

    def test_absolute_mode_fires_on_a_large_new_value(self):
        self._threshold(comparison_mode="absolute", threshold_amount=50000)
        before = self._high_value_count()
        self._entry({"amount_total": {"old": "1000000", "new": "1001000"}})
        self.assertGreater(self._high_value_count(), before)

    def test_increase_mode_ignores_a_decrease(self):
        self._threshold(comparison_mode="increase", threshold_amount=50000)
        before = self._high_value_count()
        self._entry({"amount_total": {"old": "200000", "new": "1000"}})
        self.assertEqual(self._high_value_count(), before)

    def test_increase_mode_fires_on_growth(self):
        self._threshold(comparison_mode="increase", threshold_amount=50000)
        before = self._high_value_count()
        self._entry({"amount_total": {"old": "1000", "new": "200000"}})
        self.assertGreater(self._high_value_count(), before)

    def test_delta_catches_a_decrease_too(self):
        self._threshold(comparison_mode="delta", threshold_amount=50000)
        before = self._high_value_count()
        self._entry({"amount_total": {"old": "200000", "new": "1000"}})
        self.assertGreater(self._high_value_count(), before)

    def test_threshold_boundary_is_inclusive(self):
        self._threshold(comparison_mode="delta", threshold_amount=50000)
        before = self._high_value_count()
        self._entry({"amount_total": {"old": "0", "new": "50000"}})
        self.assertGreater(self._high_value_count(), before)

    # --- Scoping ------------------------------------------------------------
    def test_threshold_applies_only_to_its_model(self):
        self._threshold(model_name="account.move")
        before = self._high_value_count()
        self._entry(
            {"amount_total": {"old": "0", "new": "999999"}},
            model_name="sale.order",
        )
        self.assertEqual(self._high_value_count(), before)

    def test_threshold_applies_only_to_its_field(self):
        self._threshold(field_name="amount_total")
        before = self._high_value_count()
        self._entry({"amount_untaxed": {"old": "0", "new": "999999"}})
        self.assertEqual(self._high_value_count(), before)

    def test_inactive_threshold_does_not_fire(self):
        threshold = self._threshold()
        threshold.active = False
        before = self._high_value_count()
        self._entry({"amount_total": {"old": "0", "new": "999999"}})
        self.assertEqual(self._high_value_count(), before)

    def test_alert_carries_the_configured_severity(self):
        self._threshold(severity="critical")
        self._entry({"amount_total": {"old": "0", "new": "999999"}})
        alert = self.Alert.sudo().search(
            [("alert_type", "=", "high_value_edit")], order="id desc", limit=1
        )
        self.assertEqual(alert.severity, "critical")

    def test_alert_reports_the_old_and_new_values(self):
        self._threshold()
        self._entry({"amount_total": {"old": "1000", "new": "800000"}})
        alert = self.Alert.sudo().search(
            [("alert_type", "=", "high_value_edit")], order="id desc", limit=1
        )
        self.assertIn("1000", alert.reason)
        self.assertIn("800000", alert.reason)

    # --- Robustness ---------------------------------------------------------
    def test_non_numeric_values_are_skipped_quietly(self):
        self._threshold()
        before = self._high_value_count()
        self._entry({"amount_total": {"old": "n/a", "new": "unknown"}})
        self.assertEqual(self._high_value_count(), before)

    def test_malformed_field_changes_do_not_raise(self):
        self._threshold()
        entry = self.Locker.append(
            {
                "user_id": self.env.user.id,
                "user_login": self.env.user.login,
                "model_name": "account.move",
                "res_id": 2,
                "action_type": "write",
                "field_changes": "this is not json",
            }
        )
        self.assertTrue(entry.exists())

    def test_missing_old_value_is_treated_as_zero(self):
        self._threshold(comparison_mode="delta", threshold_amount=50000)
        before = self._high_value_count()
        self._entry({"amount_total": {"old": None, "new": "60000"}})
        self.assertGreater(self._high_value_count(), before)

    def test_values_with_thousands_separators_are_parsed(self):
        self._threshold(comparison_mode="absolute", threshold_amount=50000)
        before = self._high_value_count()
        self._entry({"amount_total": {"old": "0", "new": "1,250,000.00"}})
        self.assertGreater(self._high_value_count(), before)

    # --- Configuration validation -------------------------------------------
    def test_threshold_on_a_non_numeric_field_is_rejected(self):
        """Otherwise the rule looks configured and silently never fires."""
        with self.assertRaises(ValidationError):
            self._threshold(field_name="ref")

    def test_threshold_on_an_unknown_field_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._threshold(field_name="not_a_real_field")

    def test_zero_threshold_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._threshold(threshold_amount=0)

    def test_duplicate_threshold_for_a_field_is_rejected(self):
        self._threshold()
        with self.assertRaises(Exception):
            self._threshold()

    def test_coverage_report_flags_thresholds_without_an_owner(self):
        self._threshold()
        report = self.Threshold.coverage_report()
        self.assertTrue(report["any_configured"])
        self.assertTrue(report["without_owner"])
