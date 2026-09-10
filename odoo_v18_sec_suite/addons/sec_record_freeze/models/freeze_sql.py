# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Database-level enforcement of the record freeze.

Implements BRD FR-3.2's second half and the parallel-constraint criterion of
PRD US-3.1: "A parallel PostgreSQL-level constraint (trigger or rule) rejects
UPDATE/DELETE on frozen record IDs even if the ORM layer is bypassed."

What this actually buys you, stated precisely, because it is easy to oversell:

- It stops writes that never pass through Odoo: someone at a ``psql`` prompt,
  a stray migration script, a reporting tool with write credentials, a bug in
  our own ORM override.
- It does **not** stop a PostgreSQL superuser. A superuser can
  ``ALTER TABLE ... DISABLE TRIGGER`` or drop the function outright. BRD
  Section 8.2 is already candid about this, and the answer there is the right
  one: replicate the evidence outside the DBA's control (P4-1) and remove
  standing production access (P0-1). This layer raises the bar; it does not
  close the hole.
- It is *evidence-generating* even when bypassed: disabling a trigger is a DDL
  event, and a trigger that has vanished between reconciliation runs is a
  finding. ``verify_triggers()`` below exists for exactly that check.

Two design constraints discovered while building P1-4, both of which shape
this code:

1. **Never block all UPDATEs on a frozen row.** Odoo writes to confirmed
   documents constantly. The trigger compares OLD and NEW on the protected
   columns only, and uses IS DISTINCT FROM so that a recompute writing an
   unchanged value passes.
2. **Only real stored columns can be guarded.** The rule's protected field
   list contains one2many fields such as ``order_line`` and ``line_ids``,
   which are not columns at all. Those are filtered out here; they remain
   protected at the ORM layer, and their child rows are guarded by the line
   models' own triggers.
"""

import logging

from odoo import _, api, models

_logger = logging.getLogger(__name__)

GUARD_FUNCTION = "sec_freeze_guard"
TRIGGER_PREFIX = "sec_freeze_trg_"

# A session that sets this to 'granted' bypasses the trigger. Set only by the
# override engine (P2-8) after three validated approvals, and only for the
# duration of one transaction via SET LOCAL.
#
# Note honestly: anyone who can open a psql session can also set it. That is
# not a flaw in the design so much as a restatement of the superuser problem
# above. Against the ORM-bypass cases this layer targets — stray scripts,
# reporting tools, our own bugs — it holds.
UNLOCK_GUC = "sec.freeze_unlock"

GUARD_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION {function}() RETURNS trigger AS $guard$
DECLARE
    frozen_states  text[] := string_to_array(TG_ARGV[0], ',');
    protected_cols text[] := string_to_array(TG_ARGV[1], ',');
    parent_table   text   := TG_ARGV[2];
    parent_fk      text   := TG_ARGV[3];
    row_data       jsonb;
    state_val      text;
    parent_id      bigint;
    col            text;
BEGIN
    -- Explicit, transaction-scoped unlock granted by the override engine.
    IF coalesce(current_setting('{guc}', true), '') = 'granted' THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
    END IF;

    -- INSERT has no OLD row; the parent is read from NEW instead.
    IF TG_OP = 'INSERT' THEN
        row_data := to_jsonb(NEW);
    ELSE
        row_data := to_jsonb(OLD);
    END IF;

    -- Resolve the state: either on this row, or on its parent document.
    IF TG_OP = 'INSERT' AND parent_table = '' THEN
        -- Documents are created in draft and confirmed afterwards, so a
        -- direct INSERT in a frozen state is normal during data import and is
        -- not blocked. Child rows are a different matter, below.
        RETURN NEW;
    END IF;

    IF parent_table = '' THEN
        state_val := row_data ->> 'state';
    ELSE
        parent_id := (row_data ->> parent_fk)::bigint;
        IF parent_id IS NULL THEN
            IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
        END IF;
        EXECUTE format('SELECT state FROM %I WHERE id = $1', parent_table)
            INTO state_val USING parent_id;
    END IF;

    -- Not frozen: nothing to do. This is also the path taken by the write
    -- that performs the confirmation itself, since OLD.state is still draft.
    IF state_val IS NULL OR NOT (state_val = ANY(frozen_states)) THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'SEC_FREEZE: deletion of frozen % row id=% is not permitted',
            TG_TABLE_NAME, OLD.id
            USING ERRCODE = 'check_violation';
    END IF;

    -- P4-4: adding a child row to a frozen parent changes the parent just as
    -- surely as editing it. The ORM layer refuses this too.
    IF TG_OP = 'INSERT' THEN
        RAISE EXCEPTION
            'SEC_FREEZE: rows cannot be added to frozen % (parent state=%)',
            parent_table, state_val
            USING ERRCODE = 'check_violation';
    END IF;

    -- UPDATE: refuse only if a protected column actually changes value.
    FOREACH col IN ARRAY protected_cols LOOP
        IF (to_jsonb(NEW) ->> col) IS DISTINCT FROM (row_data ->> col) THEN
            RAISE EXCEPTION
                'SEC_FREEZE: column %.% cannot be changed on frozen row id=% '
                '(state=%). Use the multi-party override workflow.',
                TG_TABLE_NAME, col, OLD.id, state_val
                USING ERRCODE = 'check_violation';
        END IF;
    END LOOP;

    RETURN NEW;
END;
$guard$ LANGUAGE plpgsql;
"""


class FreezeRuleSql(models.Model):
    """Adds database-trigger management to the freeze rule model."""

    _inherit = "sec.freeze.rule"

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------
    def _table_name(self):
        """Physical table for this rule's model, or None if not installed."""
        self.ensure_one()
        model = self.env.get(self.model_name)
        return model._table if model is not None else None

    def _existing_columns(self, table):
        """Columns that physically exist on the table."""
        self.env.cr.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s",
            (table,),
        )
        return {row[0] for row in self.env.cr.fetchall()}

    def _guardable_columns(self):
        """Protected fields that are real, stored columns on this table.

        One2many and non-stored computed fields are dropped: there is nothing
        to guard at the column level. They stay protected by the ORM layer.
        """
        self.ensure_one()
        table = self._table_name()
        if not table:
            return []
        physical = self._existing_columns(table)
        model = self.env[self.model_name]
        guardable = []
        for name in sorted(self.protected_field_set()):
            field = model._fields.get(name)
            if field is None or not field.store:
                continue
            column = field.name
            if field.type == "many2one":
                column = field.name  # Odoo stores m2o as <name> integer column
            if column in physical:
                guardable.append(column)
        return guardable

    def _parent_spec(self):
        """(parent_table, fk_column) for line models, or ('', '')."""
        self.ensure_one()
        path = (self.state_field_path or "state").split(".")
        if len(path) == 1:
            return "", ""
        fk_name = path[0]
        model = self.env.get(self.model_name)
        if model is None:
            return "", ""
        field = model._fields.get(fk_name)
        if field is None or field.type != "many2one":
            return "", ""
        parent_model = self.env.get(field.comodel_name)
        if parent_model is None:
            return "", ""
        return parent_model._table, fk_name

    # ------------------------------------------------------------------
    # Trigger lifecycle
    # ------------------------------------------------------------------
    @api.model
    def _install_guard_function(self):
        self.env.cr.execute(
            GUARD_FUNCTION_SQL.format(function=GUARD_FUNCTION, guc=UNLOCK_GUC)
        )

    def _trigger_name(self):
        self.ensure_one()
        return "%s%s" % (TRIGGER_PREFIX, self._table_name())

    def _install_trigger(self):
        """(Re)create this rule's trigger. Returns a short status string."""
        self.ensure_one()
        table = self._table_name()
        if not table:
            return "skipped: model %s not installed" % self.model_name
        columns = self._guardable_columns()
        if not columns:
            return "skipped: no guardable columns for %s" % self.model_name
        parent_table, parent_fk = self._parent_spec()
        trigger = self._trigger_name()
        states = ",".join(sorted(self.frozen_state_set()))

        self.env.cr.execute(
            "DROP TRIGGER IF EXISTS %s ON %s"
            % (trigger, table)  # identifiers, not user input
        )
        self.env.cr.execute(
            """
            CREATE TRIGGER {trigger}
            BEFORE INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION {function}(%s, %s, %s, %s)
            """.format(trigger=trigger, table=table, function=GUARD_FUNCTION),
            (states, ",".join(columns), parent_table, parent_fk),
        )
        _logger.info(
            "Installed freeze trigger %s on %s guarding %d column(s)",
            trigger,
            table,
            len(columns),
        )
        return "installed on %s guarding %d column(s)" % (table, len(columns))

    def _drop_trigger(self):
        self.ensure_one()
        table = self._table_name()
        if not table:
            return
        self.env.cr.execute(
            "DROP TRIGGER IF EXISTS %s ON %s" % (self._trigger_name(), table)
        )

    @api.model
    def sync_all_triggers(self):
        """Bring database triggers into line with the rule configuration.

        Called from the post-init hook, from ``write()`` on a rule, and safe to
        call by hand after changing a protected field list.
        """
        self._install_guard_function()
        results = {}
        for rule in self.sudo().search([]):
            if rule.enforcement_active:
                results[rule.model_name] = rule._install_trigger()
            else:
                rule._drop_trigger()
                results[rule.model_name] = "dropped: enforcement inactive"
        return results

    @api.model
    def drop_all_triggers(self):
        """Remove every trigger this module installed.

        Wired to the uninstall hook. Leaving triggers behind after uninstall
        would leave a database enforcing rules whose configuration no longer
        exists — effectively unmaintainable and, on the wrong table, business
        stopping.
        """
        for rule in self.sudo().search([]):
            rule._drop_trigger()
        self.env.cr.execute("DROP FUNCTION IF EXISTS %s()" % GUARD_FUNCTION)
        _logger.warning("All record-freeze database triggers removed")

    @api.model
    def verify_triggers(self):
        """Report which expected triggers are actually present.

        A trigger that has disappeared is a finding, not a glitch: dropping one
        is a deliberate act. Intended to be called by the daily reconciliation
        job in P4-2 and reported in the monthly forensic report.
        """
        expected = {}
        for rule in self.sudo().search([("enforcement_active", "=", True)]):
            table = rule._table_name()
            if table and rule._guardable_columns():
                expected[rule._trigger_name()] = table

        self.env.cr.execute(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal "
            "AND tgname LIKE %s",
            (TRIGGER_PREFIX + "%",),
        )
        present = {row[0] for row in self.env.cr.fetchall()}
        missing = sorted(set(expected) - present)
        unexpected = sorted(present - set(expected))

        if missing:
            self.env["sec.anomaly.mixin"]._raise_anomaly(
                alert_type="frozen_record_write_attempt",
                name=_("Record freeze database trigger(s) missing"),
                reason=_(
                    "Expected freeze trigger(s) are absent from the database: "
                    "%(missing)s. Dropping a trigger is a deliberate act and "
                    "means frozen records on those tables are currently "
                    "editable by direct SQL.",
                    missing=", ".join(missing),
                ),
                severity="critical",
            )
        return {
            "expected": expected,
            "present": sorted(present),
            "missing": missing,
            "unexpected": unexpected,
            "healthy": not missing,
        }

    def write(self, vals):
        """Keep triggers in step with configuration changes."""
        result = super().write(vals)
        if {"protected_fields", "frozen_states", "enforcement_active",
                "state_field_path", "model_name"} & set(vals):
            self.sudo().sync_all_triggers()
        return result


def post_init_hook(env):
    """Install the guard function and all triggers on module install."""
    env["sec.freeze.rule"].sync_all_triggers()


def uninstall_hook(env):
    """Remove every trigger and the guard function on uninstall."""
    env["sec.freeze.rule"].drop_all_triggers()
