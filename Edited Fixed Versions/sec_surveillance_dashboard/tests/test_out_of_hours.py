# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for out-of-hours detection (P3-1, US-7.1)."""

from datetime import datetime

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOutOfHours(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Hours = cls.env["sec.business.hours"]
        cls.Param = cls.env["ir.config_parameter"].sudo()
        cls.Param.set_param("sec_surveillance.timezone", "UTC")
        cls.Param.set_param("sec_surveillance.business_start_hour", "9")
        cls.Param.set_param("sec_surveillance.business_end_hour", "18")
        cls.Param.set_param("sec_surveillance.working_days", "1,2,3,4,5")
        cls.Param.set_param("sec_surveillance.out_of_hours_enabled", "True")

    # 2026-09-03 is a Thursday; 2026-09-05 a Saturday.
    def test_midday_weekday_is_in_hours(self):
        self.assertFalse(
            self.Hours.is_out_of_hours(datetime(2026, 9, 3, 12, 0, 0))
        )

    def test_early_morning_is_out_of_hours(self):
        self.assertTrue(
            self.Hours.is_out_of_hours(datetime(2026, 9, 3, 2, 0, 0))
        )

    def test_late_evening_is_out_of_hours(self):
        self.assertTrue(
            self.Hours.is_out_of_hours(datetime(2026, 9, 3, 23, 30, 0))
        )

    def test_boundaries(self):
        self.assertFalse(
            self.Hours.is_out_of_hours(datetime(2026, 9, 3, 9, 0, 0))
        )
        self.assertTrue(
            self.Hours.is_out_of_hours(datetime(2026, 9, 3, 18, 0, 0))
        )

    def test_weekend_is_out_of_hours(self):
        self.assertTrue(
            self.Hours.is_out_of_hours(datetime(2026, 9, 5, 12, 0, 0))
        )

    # --- Timezone handling: the failure that would kill the dashboard ------
    def test_utc_timestamp_is_judged_in_local_time(self):
        """06:00 UTC is midday in Dhaka and must not be flagged there."""
        self.Param.set_param("sec_surveillance.timezone", "Asia/Dhaka")
        self.assertFalse(
            self.Hours.is_out_of_hours(datetime(2026, 9, 3, 6, 0, 0))
        )
        # ...while the same instant is out of hours in UTC.
        self.Param.set_param("sec_surveillance.timezone", "UTC")
        self.assertTrue(
            self.Hours.is_out_of_hours(datetime(2026, 9, 3, 6, 0, 0))
        )

    def test_sunday_to_thursday_week_is_configurable(self):
        self.Param.set_param("sec_surveillance.working_days", "7,1,2,3,4")
        self.assertFalse(
            self.Hours.is_out_of_hours(datetime(2026, 9, 6, 12, 0, 0))
        )  # Sunday
        self.assertTrue(
            self.Hours.is_out_of_hours(datetime(2026, 9, 4, 12, 0, 0))
        )  # Friday
        self.Param.set_param("sec_surveillance.working_days", "1,2,3,4,5")

    def test_unknown_timezone_disables_rather_than_guesses(self):
        self.Param.set_param("sec_surveillance.timezone", "Mars/Olympus")
        self.assertFalse(
            self.Hours.is_out_of_hours(datetime(2026, 9, 3, 3, 0, 0))
        )
        self.Param.set_param("sec_surveillance.timezone", "UTC")

    def test_timezone_falls_back_to_the_company(self):
        self.Param.set_param("sec_surveillance.timezone", "")
        self.env.company.partner_id.tz = "Asia/Dhaka"
        self.assertEqual(self.Hours.timezone(), "Asia/Dhaka")
        self.Param.set_param("sec_surveillance.timezone", "UTC")

    # --- Configuration validation ------------------------------------------
    def test_inverted_hours_are_rejected(self):
        self.Param.set_param("sec_surveillance.business_start_hour", "20")
        self.Param.set_param("sec_surveillance.business_end_hour", "6")
        with self.assertRaises(ValidationError):
            self.Hours.validate_configuration()
        self.Param.set_param("sec_surveillance.business_start_hour", "9")
        self.Param.set_param("sec_surveillance.business_end_hour", "18")

    def test_valid_configuration_passes(self):
        self.assertTrue(self.Hours.validate_configuration())

    def test_detection_can_be_switched_off(self):
        self.Param.set_param("sec_surveillance.out_of_hours_enabled", "False")
        self.assertFalse(self.Hours.enabled())
        self.Param.set_param("sec_surveillance.out_of_hours_enabled", "True")

    # --- Raising from Locker activity --------------------------------------
    def test_out_of_hours_locker_entry_raises_a_low_severity_alert(self):
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([("alert_type", "=", "out_of_hours_edit")])
        self.env["audit.locker.entry"].append(
            {
                "user_id": self.env.user.id,
                "user_login": self.env.user.login,
                "model_name": "sale.order",
                "res_id": 1,
                "record_label": "SO0001",
                "action_type": "write",
                "timestamp_utc": datetime(2026, 9, 3, 2, 30, 0),
            }
        )
        after = Alert.search_count([("alert_type", "=", "out_of_hours_edit")])
        self.assertGreater(after, before)
        alert = Alert.search(
            [("alert_type", "=", "out_of_hours_edit")], order="id desc", limit=1
        )
        self.assertEqual(alert.severity, "low")

    def test_in_hours_entry_raises_nothing(self):
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([("alert_type", "=", "out_of_hours_edit")])
        self.env["audit.locker.entry"].append(
            {
                "user_id": self.env.user.id,
                "user_login": self.env.user.login,
                "model_name": "sale.order",
                "res_id": 2,
                "action_type": "write",
                "timestamp_utc": datetime(2026, 9, 3, 11, 0, 0),
            }
        )
        self.assertEqual(
            Alert.search_count([("alert_type", "=", "out_of_hours_edit")]), before
        )

    def test_unwatched_model_is_not_flagged(self):
        """Flagging every technical model would bury the dashboard."""
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([("alert_type", "=", "out_of_hours_edit")])
        self.env["audit.locker.entry"].append(
            {
                "user_id": self.env.user.id,
                "user_login": self.env.user.login,
                "model_name": "res.partner",
                "res_id": 3,
                "action_type": "write",
                "timestamp_utc": datetime(2026, 9, 3, 2, 30, 0),
            }
        )
        self.assertEqual(
            Alert.search_count([("alert_type", "=", "out_of_hours_edit")]), before
        )

    def test_surveillance_failure_does_not_break_the_locker(self):
        """Auditing must never fail because surveillance did."""
        self.Param.set_param("sec_surveillance.timezone", "Mars/Olympus")
        entry = self.env["audit.locker.entry"].append(
            {
                "user_id": self.env.user.id,
                "user_login": self.env.user.login,
                "model_name": "sale.order",
                "res_id": 4,
                "action_type": "write",
                "timestamp_utc": datetime(2026, 9, 3, 2, 30, 0),
            }
        )
        self.assertTrue(entry.exists())
        self.Param.set_param("sec_surveillance.timezone", "UTC")
