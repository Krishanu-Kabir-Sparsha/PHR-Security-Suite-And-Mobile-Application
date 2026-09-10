# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for Locker immutability and hash-chain tamper evidence (US-4.1)."""

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from ..models.locker_entry import GENESIS_HASH


@tagged("post_install", "-at_install")
class TestLockerChain(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Entry = cls.env["audit.locker.entry"]
        cls.Chain = cls.env["audit.locker.chain"]

    def _append(self, model_name="res.partner", action="write", changes=""):
        return self.Entry.append(
            {
                "user_id": self.env.user.id,
                "user_login": self.env.user.login,
                "source_ip": "10.0.0.1",
                "model_name": model_name,
                "res_id": 1,
                "action_type": action,
                "field_changes": changes,
            }
        )

    # --- Chain mechanics ---------------------------------------------------
    def test_chain_head_exists(self):
        head = self.Chain._get_head()
        self.assertTrue(head)

    def test_entries_are_sequentially_numbered(self):
        first = self._append()
        second = self._append()
        self.assertEqual(second.sequence, first.sequence + 1)

    def test_each_entry_chains_onto_the_previous(self):
        first = self._append()
        second = self._append()
        self.assertEqual(second.prev_hash, first.entry_hash)

    def test_hash_is_deterministic(self):
        entry = self._append()
        vals = {
            "sequence": entry.sequence,
            "timestamp_utc": entry.timestamp_utc,
            "user_login": entry.user_login,
            "source_ip": entry.source_ip,
            "model_name": entry.model_name,
            "res_id": entry.res_id,
            "action_type": entry.action_type,
            "field_changes": entry.field_changes,
        }
        recomputed = self.Entry._compute_entry_hash(vals, entry.prev_hash)
        self.assertEqual(recomputed, entry.entry_hash)

    def test_field_change_order_does_not_affect_the_hash(self):
        """Canonical JSON: otherwise verification fails at random."""
        one = self.Entry._canonical_payload(
            {
                "sequence": 1, "timestamp_utc": "2026-01-01 00:00:00",
                "user_login": "u", "source_ip": "1.1.1.1",
                "model_name": "m", "res_id": 1, "action_type": "write",
                "field_changes": '{"a":1,"b":2}',
            },
            GENESIS_HASH,
        )
        two = self.Entry._canonical_payload(
            {
                "action_type": "write", "field_changes": '{"a":1,"b":2}',
                "model_name": "m", "res_id": 1, "source_ip": "1.1.1.1",
                "user_login": "u", "timestamp_utc": "2026-01-01 00:00:00",
                "sequence": 1,
            },
            GENESIS_HASH,
        )
        self.assertEqual(one, two)

    # --- Immutability ------------------------------------------------------
    def test_entry_cannot_be_written(self):
        entry = self._append()
        with self.assertRaises(UserError):
            entry.write({"model_name": "something.else"})

    def test_entry_cannot_be_written_even_by_sudo(self):
        entry = self._append()
        with self.assertRaises(UserError):
            entry.sudo().write({"source_ip": "8.8.8.8"})

    def test_entry_cannot_be_deleted(self):
        entry = self._append()
        with self.assertRaises(UserError):
            entry.unlink()

    def test_entry_cannot_be_hand_created(self):
        """A hand-made entry would carry no valid chain position."""
        with self.assertRaises(UserError):
            self.Entry.create(
                {
                    "sequence": 999999,
                    "timestamp_utc": "2026-01-01 00:00:00",
                    "user_id": self.env.user.id,
                    "user_login": "forged",
                    "model_name": "res.partner",
                    "action_type": "write",
                    "prev_hash": GENESIS_HASH,
                    "entry_hash": "deadbeef",
                }
            )

    def test_replication_metadata_may_be_written_by_the_replicator(self):
        """Outside the hashed payload by design; learned after the fact."""
        entry = self._append()
        entry.with_context(locker_replication=True).write(
            {"external_replica_ref": "s3://bucket/key", "replicated_at": "2026-01-01 00:00:00"}
        )
        self.assertEqual(entry.external_replica_ref, "s3://bucket/key")

    def test_replication_context_cannot_be_used_to_change_content(self):
        entry = self._append()
        with self.assertRaises(UserError):
            entry.with_context(locker_replication=True).write(
                {"external_replica_ref": "x", "model_name": "forged"}
            )

    # --- Tamper evidence: the actual point --------------------------------
    def test_intact_chain_verifies(self):
        self._append()
        self._append()
        result = self.Entry.verify_chain()
        self.assertTrue(result["intact"], result["reason"])

    def test_content_tampering_via_raw_sql_is_detected(self):
        """The DBA-with-psql scenario the BRD is actually worried about."""
        self._append()
        target = self._append(changes='{"amount":{"old":"100","new":"200"}}')
        self._append()
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE audit_locker_entry SET field_changes = %s WHERE id = %s",
            ('{"amount":{"old":"100","new":"100"}}', target.id),
        )
        self.env.invalidate_all()
        result = self.Entry.verify_chain(raise_anomaly=False)
        self.assertFalse(result["intact"])
        self.assertEqual(result["first_break_sequence"], target.sequence)

    def test_deletion_via_raw_sql_is_detected_as_a_sequence_gap(self):
        self._append()
        target = self._append()
        self._append()
        self.env.flush_all()
        self.env.cr.execute(
            "DELETE FROM audit_locker_entry WHERE id = %s", (target.id,)
        )
        self.env.invalidate_all()
        result = self.Entry.verify_chain(raise_anomaly=False)
        self.assertFalse(result["intact"])
        self.assertIn("Sequence gap", result["reason"])

    def test_broken_chain_raises_a_critical_anomaly(self):
        target = self._append()
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE audit_locker_entry SET user_login = 'someone_else' WHERE id = %s",
            (target.id,),
        )
        self.env.invalidate_all()
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        self.Entry.verify_chain()
        self.assertGreater(Alert.search_count([]), before)
        self.assertEqual(
            Alert.search([], order="id desc", limit=1).severity, "critical"
        )
