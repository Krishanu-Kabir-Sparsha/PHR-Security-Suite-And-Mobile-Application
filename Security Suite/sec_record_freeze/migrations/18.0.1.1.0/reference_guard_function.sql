-- Reference rendering of the generated guard function.
-- Generated from models/freeze_sql.py; do not apply by hand.
-- Present so a DBA can review the SQL without reading Python.

CREATE OR REPLACE FUNCTION sec_freeze_guard() RETURNS trigger AS $guard$
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
    IF coalesce(current_setting('sec.freeze_unlock', true), '') = 'granted' THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
    END IF;

    row_data := to_jsonb(OLD);

    -- Resolve the state: either on this row, or on its parent document.
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
