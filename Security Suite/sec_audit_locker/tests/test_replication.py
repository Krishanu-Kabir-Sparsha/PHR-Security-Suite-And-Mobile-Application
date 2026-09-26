# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for external Locker replication (P4-1, US-4.2, BRD FR-4.3)."""

import json
import os
import tempfile
from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from ..models import replication


@tagged("post_install", "-at_install")
class TestReplication(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Target = cls.env["audit.replica.target"]
        cls.Locker = cls.env["audit.locker.entry"]
        cls.tmpdir = tempfile.mkdtemp(prefix="locker-replica-")

    def _file_target(self, name="Test file target"):
        return self.Target.create(
            {
                "name": name,
                "target_type": "append_file",
                "file_path": os.path.join(self.tmpdir, "%s.jsonl" % name.replace(" ", "-")),
                "independent_custodian": "Infrastructure team",
            }
        )

    def _entry(self, res_id=1):
        return self.Locker.append(
            {
                "user_id": self.env.user.id,
                "user_login": self.env.user.login,
                "model_name": "sale.order",
                "res_id": res_id,
                "action_type": "write",
                "field_changes": '{"partner_id":{"old":"1","new":"2"}}',
            }
        )

    # --- The unconfigured case must be loud --------------------------------
    def test_no_target_is_reported_as_unhealthy_not_as_zero_backlog(self):
        """'Nothing pending' is true and misleading when nothing is configured."""
        self.Target.search([]).write({"active": False})
        status = self.Locker.replication_status()
        self.assertFalse(status["configured"])
        self.assertFalse(status["healthy"])
        self.assertIn("FR-4.3 is not met", status["message"])

    def test_replicate_without_a_target_ships_nothing(self):
        self.Target.search([]).write({"active": False})
        self._entry()
        result = self.Locker.replicate_pending()
        self.assertEqual(result["shipped"], 0)

    def test_backlog_cron_alerts_when_unconfigured(self):
        self.Target.search([]).write({"active": False})
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        self.Locker.cron_check_replication_backlog()
        self.assertGreater(Alert.search_count([]), before)
        self.assertEqual(
            Alert.search([], order="id desc", limit=1).severity, "critical"
        )

    # --- Append-only file target -------------------------------------------
    def test_entries_are_written_to_the_file(self):
        target = self._file_target("write-test")
        self._entry()
        result = self.Locker.replicate_pending()
        self.assertGreaterEqual(result["shipped"], 1)
        with open(target.file_path, encoding="utf-8") as handle:
            lines = [line for line in handle if line.strip()]
        self.assertTrue(lines)
        json.loads(lines[0])

    def test_replicated_payload_carries_both_hashes(self):
        """Without the hashes the replica cannot verify the chain itself."""
        target = self._file_target("hash-test")
        self._entry()
        self.Locker.replicate_pending()
        with open(target.file_path, encoding="utf-8") as handle:
            record = json.loads(handle.readline())
        self.assertIn("entry_hash", record)
        self.assertIn("prev_hash", record)
        self.assertIn("sequence", record)

    def test_shipping_appends_rather_than_overwrites(self):
        target = self._file_target("append-test")
        self._entry()
        self.Locker.replicate_pending()
        self._entry(res_id=2)
        self.Locker.replicate_pending()
        with open(target.file_path, encoding="utf-8") as handle:
            lines = [line for line in handle if line.strip()]
        self.assertGreaterEqual(len(lines), 2)

    def test_entries_are_marked_replicated(self):
        self._file_target("mark-test")
        entry = self._entry()
        self.Locker.replicate_pending()
        entry.invalidate_recordset()
        self.assertTrue(entry.external_replica_ref)
        self.assertTrue(entry.replicated_at)

    def test_replication_is_idempotent(self):
        self._file_target("idempotent-test")
        self._entry()
        first = self.Locker.replicate_pending()
        second = self.Locker.replicate_pending()
        self.assertGreaterEqual(first["shipped"], 1)
        self.assertEqual(second["shipped"], 0)

    # --- Failure handling ---------------------------------------------------
    def test_failed_shipping_leaves_entries_pending_for_retry(self):
        """Marking them replicated on failure would lose them silently."""
        target = self._file_target("fail-test")
        entry = self._entry()
        with patch.object(
            type(target), "_ship_append_file", side_effect=OSError("disk gone")
        ):
            result = self.Locker.replicate_pending()
        self.assertEqual(result["shipped"], 0)
        entry.invalidate_recordset()
        self.assertFalse(entry.external_replica_ref)

    def test_total_failure_raises_a_critical_anomaly(self):
        target = self._file_target("alert-test")
        self._entry()
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        with patch.object(
            type(target), "_ship_append_file", side_effect=OSError("disk gone")
        ):
            self.Locker.replicate_pending()
        self.assertGreater(Alert.search_count([]), before)
        self.assertEqual(
            Alert.search([], order="id desc", limit=1).severity, "critical"
        )

    def test_failure_is_recorded_on_the_target(self):
        target = self._file_target("error-record-test")
        self._entry()
        with patch.object(
            type(target), "_ship_append_file", side_effect=OSError("disk gone")
        ):
            self.Locker.replicate_pending()
        target.invalidate_recordset()
        self.assertIn("disk gone", target.last_error or "")
        self.assertTrue(target.last_error_at)

    def test_one_working_target_still_records_the_entry(self):
        """Patching the class would break both targets, so the failing one is
        made to fail by configuration instead."""
        self._file_target("good-target")
        bad = self._file_target("bad-target")
        bad.sudo().write({"file_path": "/proc/definitely/not/writable"})
        entry = self._entry()
        result = self.Locker.replicate_pending()
        self.assertGreaterEqual(result["shipped"], 1)
        self.assertTrue(result.get("failures"))
        entry.invalidate_recordset()
        self.assertTrue(entry.external_replica_ref)

    # --- Configuration validation -------------------------------------------
    def test_http_target_must_be_https(self):
        with self.assertRaises(ValidationError) as caught:
            self.Target.create(
                {
                    "name": "Insecure",
                    "target_type": "http",
                    "endpoint_url": "http://audit.example.com/locker",
                    "shared_secret": "s3cret",
                }
            )
        self.assertIn("HTTPS", str(caught.exception))

    def test_http_target_requires_a_shared_secret(self):
        with self.assertRaises(ValidationError):
            self.Target.create(
                {
                    "name": "Unsigned",
                    "target_type": "http",
                    "endpoint_url": "https://audit.example.com/locker",
                }
            )

    def test_file_target_requires_a_path(self):
        with self.assertRaises(ValidationError):
            self.Target.create({"name": "Pathless", "target_type": "append_file"})

    # --- Status reporting ---------------------------------------------------
    def test_status_reports_pending_count(self):
        self._file_target("status-test")
        self.Locker.replicate_pending()
        self._entry(res_id=99)
        status = self.Locker.replication_status()
        self.assertTrue(status["configured"])
        self.assertGreaterEqual(status["pending"], 1)

    def test_status_lists_the_custodian(self):
        self._file_target("custodian-test")
        status = self.Locker.replication_status()
        custodians = [t["custodian"] for t in status["targets"]]
        self.assertIn("Infrastructure team", custodians)

    def test_status_healthy_when_drained(self):
        self._file_target("drained-test")
        self._entry()
        self.Locker.replicate_pending()
        status = self.Locker.replication_status()
        self.assertEqual(status["pending"], 0)
        self.assertTrue(status["healthy"])

    def test_batch_size_limits_a_single_run(self):
        self._file_target("batch-test")
        for index in range(5):
            self._entry(res_id=200 + index)
        result = self.Locker.replicate_pending(limit=2)
        self.assertLessEqual(result["shipped"], 2)

    # --- Test button --------------------------------------------------------
    def test_target_test_writes_a_probe_and_reports(self):
        target = self._file_target("probe-test")
        with self.assertRaises(UserError) as caught:
            target.action_test()
        self.assertIn("probe record was written", str(caught.exception))
        self.assertTrue(os.path.exists(target.file_path))

    def test_target_test_reports_failure_clearly(self):
        target = self._file_target("probe-fail")
        target.sudo().write({"file_path": "/proc/definitely/not/writable"})
        with self.assertRaises(UserError) as caught:
            target.action_test()
        self.assertIn("failed", str(caught.exception).lower())
