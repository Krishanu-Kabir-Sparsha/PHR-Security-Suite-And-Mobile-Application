# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for Locker reconciliation (P4-2, US-4.2 second criterion)."""

import json
import os
import tempfile

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestReconciliation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Target = cls.env["audit.replica.target"]
        cls.Locker = cls.env["audit.locker.entry"]
        cls.Run = cls.env["audit.reconciliation.run"]
        cls.tmpdir = tempfile.mkdtemp(prefix="locker-recon-")
        cls.Target.search([]).write({"active": False})

    def _target(self, name):
        return self.Target.create(
            {
                "name": name,
                "target_type": "append_file",
                "file_path": os.path.join(self.tmpdir, "%s.jsonl" % name),
                "independent_custodian": "Infra team",
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
            }
        )

    def _replicated_target(self, name):
        target = self._target(name)
        self._entry()
        self._entry(res_id=2)
        self.Locker.replicate_pending()
        return target

    # --- The happy path -----------------------------------------------------
    def test_matching_replica_verdict_is_match(self):
        target = self._replicated_target("match")
        run = self.Locker.reconcile_target(target)
        self.assertEqual(run.verdict, "match")
        self.assertEqual(run.missing_in_primary, 0)
        self.assertEqual(run.hash_mismatches, 0)

    def test_match_records_counts(self):
        target = self._replicated_target("counts")
        run = self.Locker.reconcile_target(target)
        self.assertEqual(run.primary_count, run.replica_count)
        self.assertGreater(run.primary_count, 0)

    def test_match_raises_no_alert(self):
        target = self._replicated_target("quiet")
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        self.Locker.reconcile_target(target)
        self.assertEqual(Alert.search_count([]), before)

    # --- Lag is not a mismatch ----------------------------------------------
    def test_unshipped_entries_are_lag_not_mismatch(self):
        target = self._replicated_target("lag")
        self._entry(res_id=3)  # written but not yet shipped
        run = self.Locker.reconcile_target(target)
        self.assertEqual(run.verdict, "lag")
        self.assertGreaterEqual(run.missing_in_replica, 1)

    def test_lag_alerts_only_at_low_severity(self):
        target = self._replicated_target("lag-severity")
        self._entry(res_id=4)
        self.Locker.reconcile_target(target)
        alert = self.env["anomaly.alert"].sudo().search(
            [], order="id desc", limit=1
        )
        self.assertEqual(alert.severity, "low")

    # --- The case that matters most ----------------------------------------
    def test_entries_deleted_from_the_primary_are_detected(self):
        """The signature of a DBA deleting rows: present in replica, absent here."""
        target = self._replicated_target("deleted")
        self.env.flush_all()
        victim = self.Locker.sudo().search([], order="sequence desc", limit=1)
        sequence = victim.sequence
        self.env.cr.execute(
            "DELETE FROM audit_locker_entry WHERE id = %s", (victim.id,)
        )
        self.env.invalidate_all()
        run = self.Locker.reconcile_target(target)
        self.assertEqual(run.verdict, "primary_missing")
        self.assertGreaterEqual(run.missing_in_primary, 1)
        self.assertIn(str(sequence), run.detail)

    def test_primary_deletion_raises_a_critical_alert(self):
        target = self._replicated_target("deleted-alert")
        self.env.flush_all()
        victim = self.Locker.sudo().search([], order="sequence desc", limit=1)
        self.env.cr.execute(
            "DELETE FROM audit_locker_entry WHERE id = %s", (victim.id,)
        )
        self.env.invalidate_all()
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        self.Locker.reconcile_target(target)
        self.assertGreater(Alert.search_count([]), before)
        self.assertEqual(
            Alert.search([], order="id desc", limit=1).severity, "critical"
        )

    def test_primary_deletion_detail_says_preserve_the_replica(self):
        target = self._replicated_target("deleted-advice")
        self.env.flush_all()
        victim = self.Locker.sudo().search([], order="sequence desc", limit=1)
        self.env.cr.execute(
            "DELETE FROM audit_locker_entry WHERE id = %s", (victim.id,)
        )
        self.env.invalidate_all()
        run = self.Locker.reconcile_target(target)
        self.assertIn("Preserve the replica".lower(), run.detail.lower())

    def test_primary_deletion_outranks_lag(self):
        target = self._replicated_target("priority")
        self._entry(res_id=9)  # creates a lag as well
        self.env.flush_all()
        victim = self.Locker.sudo().search(
            [("external_replica_ref", "!=", False)], order="sequence desc", limit=1
        )
        self.env.cr.execute(
            "DELETE FROM audit_locker_entry WHERE id = %s", (victim.id,)
        )
        self.env.invalidate_all()
        run = self.Locker.reconcile_target(target)
        self.assertEqual(run.verdict, "primary_missing")

    # --- Content alteration -------------------------------------------------
    def test_hash_mismatch_is_detected(self):
        target = self._replicated_target("altered")
        self.env.flush_all()
        victim = self.Locker.sudo().search([], order="sequence desc", limit=1)
        self.env.cr.execute(
            "UPDATE audit_locker_entry SET entry_hash = %s WHERE id = %s",
            ("0" * 64, victim.id),
        )
        self.env.invalidate_all()
        run = self.Locker.reconcile_target(target)
        self.assertEqual(run.verdict, "mismatch")
        self.assertGreaterEqual(run.hash_mismatches, 1)

    def test_mismatch_is_critical(self):
        target = self._replicated_target("altered-alert")
        self.env.flush_all()
        victim = self.Locker.sudo().search([], order="sequence desc", limit=1)
        self.env.cr.execute(
            "UPDATE audit_locker_entry SET entry_hash = %s WHERE id = %s",
            ("f" * 64, victim.id),
        )
        self.env.invalidate_all()
        self.Locker.reconcile_target(target)
        self.assertEqual(
            self.env["anomaly.alert"].sudo().search(
                [], order="id desc", limit=1
            ).severity,
            "critical",
        )

    # --- Unverifiable must never read as a pass ----------------------------
    def test_http_target_without_verify_url_is_unverifiable(self):
        target = self.Target.create(
            {
                "name": "Opaque endpoint",
                "target_type": "http",
                "endpoint_url": "https://audit.example.com/locker",
                "shared_secret": "s3cret",
            }
        )
        self.assertFalse(target.readable)
        run = self.Locker.reconcile_target(target)
        self.assertEqual(run.verdict, "unverifiable")
        self.assertIn("not read this run as a pass", run.detail)

    def test_unverifiable_counts_against_a_clean_status(self):
        self.Target.create(
            {
                "name": "Opaque endpoint 2",
                "target_type": "http",
                "endpoint_url": "https://audit.example.com/locker",
                "shared_secret": "s3cret",
            }
        )
        self.Locker.reconcile_all()
        self.assertFalse(self.Locker.reconciliation_status()["clean"])

    def test_unreadable_file_is_an_error_not_a_pass(self):
        target = self._target("gone")
        target.sudo().write({"file_path": "/proc/nonexistent/replica.jsonl"})
        run = self.Locker.reconcile_target(target)
        self.assertEqual(run.verdict, "error")
        self.assertIn("not a pass", run.detail)

    # --- Robustness ---------------------------------------------------------
    def test_duplicate_shipped_entries_are_not_a_mismatch(self):
        """Retries legitimately ship the same entry twice."""
        target = self._replicated_target("duplicates")
        with open(target.file_path, encoding="utf-8") as handle:
            first_line = handle.readline()
        with open(target.file_path, "a", encoding="utf-8") as handle:
            handle.write(first_line)
        run = self.Locker.reconcile_target(target)
        self.assertEqual(run.verdict, "match")

    def test_corrupt_line_does_not_abort_the_comparison(self):
        target = self._replicated_target("corrupt")
        with open(target.file_path, "a", encoding="utf-8") as handle:
            handle.write("this is not json\n")
        run = self.Locker.reconcile_target(target)
        self.assertIn(run.verdict, ("match", "lag"))

    def test_probe_records_are_ignored(self):
        target = self._replicated_target("probe")
        with self.assertRaises(UserError):
            target.action_test()  # writes a sequence 0 probe
        run = self.Locker.reconcile_target(target)
        self.assertEqual(run.verdict, "match")

    # --- Results are evidence ----------------------------------------------
    def test_runs_are_append_only(self):
        target = self._replicated_target("append-only")
        run = self.Locker.reconcile_target(target)
        with self.assertRaises(UserError):
            run.write({"verdict": "match"})
        with self.assertRaises(UserError):
            run.unlink()

    def test_target_records_when_it_was_last_reconciled(self):
        target = self._replicated_target("timestamp")
        self.Locker.reconcile_target(target)
        target.invalidate_recordset()
        self.assertTrue(target.last_reconciled_at)

    # --- Status for the forensic report ------------------------------------
    def test_status_reports_never_run_as_not_clean(self):
        self._target("never-reconciled")
        status = self.Locker.reconciliation_status()
        self.assertFalse(status["clean"])
        self.assertIn(
            "never_run", [t["verdict"] for t in status["targets"]]
        )

    def test_status_clean_after_a_matching_run(self):
        self.Target.search([]).write({"active": False})
        target = self._replicated_target("clean-status")
        self.Locker.reconcile_target(target)
        self.assertTrue(self.Locker.reconciliation_status()["clean"])

    def test_no_target_means_reconciliation_is_impossible_and_alerts(self):
        self.Target.search([]).write({"active": False})
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        runs = self.Locker.reconcile_all()
        self.assertFalse(runs)
        self.assertGreater(Alert.search_count([]), before)

    def test_reconcile_cron_is_active(self):
        cron = self.env.ref("sec_audit_locker.cron_reconcile_locker")
        self.assertTrue(cron.active)
