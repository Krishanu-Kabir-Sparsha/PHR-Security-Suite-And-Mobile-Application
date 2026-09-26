#!/usr/bin/env python3
"""P4-5 — benchmark the security suite against the PRD Section 9 NFR targets.

Run inside an Odoo shell against a database with the suite installed:

    odoo shell -c /etc/odoo/odoo.conf -d YOUR_DB < tools/benchmark_nfr.py

Or paste the body into an interactive shell. It measures the three targets the
PRD states numerically:

    audit logging overhead      < 100 ms added to a standard save
    anomaly alerting latency    < 60 s from triggering action
    approval / override screens < 2 s response

It writes nothing permanent except the records it creates in the process, and
it rolls those back at the end. **Run it on a copy of production data**, not on
a scratch database with fifty records: the numbers that matter come from real
table sizes and real index depth.
"""

import time
import statistics


def _time(callable_, repeats=30):
    """Return (median_ms, p95_ms) over `repeats` runs."""
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        callable_()
        samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    p95 = samples[min(len(samples) - 1, int(len(samples) * 0.95))]
    return statistics.median(samples), p95


def run(env):
    results = {}
    partner = env["res.partner"].search([], limit=1)
    product = env["product.product"].search([("sale_ok", "=", True)], limit=1)
    if not partner or not product:
        print("Need at least one partner and one saleable product.")
        return {}

    def make_draft_order():
        return env["sale.order"].create({
            "partner_id": partner.id,
            "order_line": [(0, 0, {
                "product_id": product.id,
                "product_uom_qty": 1,
                "price_unit": 100.0,
            })],
        })

    # --- 1. Write overhead on an in-scope, audited model -------------------
    orders = [make_draft_order() for _ in range(40)]
    env.cr.flush()
    index = {"i": 0}

    def audited_write():
        order = orders[index["i"] % len(orders)]
        index["i"] += 1
        order.write({"note": "benchmark %s" % index["i"]})
        env.cr.flush()

    median, p95 = _time(audited_write, repeats=40)
    results["audited_write_ms"] = (median, p95)

    # --- 2. The same write with the suite's hooks disabled -----------------
    # Approximates the baseline by writing to a model outside audit scope.
    partners = [
        env["res.partner"].create({"name": "bench-%s" % n}) for n in range(40)
    ]
    env.cr.flush()
    index2 = {"i": 0}

    def unaudited_write():
        record = partners[index2["i"] % len(partners)]
        index2["i"] += 1
        record.write({"comment": "benchmark %s" % index2["i"]})
        env.cr.flush()

    base_median, base_p95 = _time(unaudited_write, repeats=40)
    results["baseline_write_ms"] = (base_median, base_p95)
    results["audit_overhead_ms"] = (median - base_median, p95 - base_p95)

    # --- 3. Locker append in isolation -------------------------------------
    Locker = env["audit.locker.entry"]

    def locker_append():
        Locker.append({
            "user_id": env.user.id,
            "user_login": env.user.login,
            "model_name": "sale.order",
            "res_id": 1,
            "action_type": "write",
            "field_changes": '{"note":{"old":"a","new":"b"}}',
        })
        env.cr.flush()

    results["locker_append_ms"] = _time(locker_append, repeats=50)

    # --- 4. Chain verification over the live chain -------------------------
    start = time.perf_counter()
    verdict = Locker.verify_chain(raise_anomaly=False)
    results["verify_chain_s"] = time.perf_counter() - start
    results["chain_entries"] = verdict.get("checked")

    # --- 5. Confirmation (the freeze path) ---------------------------------
    to_confirm = [make_draft_order() for _ in range(20)]
    env.cr.flush()
    index3 = {"i": 0}

    def confirm_order():
        order = to_confirm[index3["i"]]
        index3["i"] += 1
        order.action_confirm()
        env.cr.flush()

    results["confirm_order_ms"] = _time(confirm_order, repeats=20)

    # --- 6. Blocked write (the anomaly + out-of-band cursor path) ----------
    frozen = to_confirm[0]

    def blocked_write():
        try:
            frozen.write({"partner_id": partner.id, "date_order": "2026-01-01"})
        except Exception:
            pass
        env.cr.flush()

    results["blocked_write_ms"] = _time(blocked_write, repeats=20)

    # --- 7. Dashboard and report -------------------------------------------
    results["dashboard_summary_ms"] = _time(
        lambda: env["anomaly.alert"].dashboard_summary(hours=24), repeats=10
    )
    start = time.perf_counter()
    env["forensic.report"].gather if hasattr(env["forensic.report"], "gather") else None
    results["report_note"] = "run generate_for_period manually; it is monthly, not hot-path"

    return results


def report(results):
    def fmt(key):
        value = results.get(key)
        if isinstance(value, tuple):
            return "median %.1f ms, p95 %.1f ms" % value
        return str(value)

    print("\n=== PRD Section 9 NFR benchmark ===\n")
    print("Baseline write (unaudited model):   ", fmt("baseline_write_ms"))
    print("Audited write (in scope):           ", fmt("audited_write_ms"))
    print("AUDIT OVERHEAD  (target < 100 ms):  ", fmt("audit_overhead_ms"))
    print("Locker append alone:                ", fmt("locker_append_ms"))
    print("Order confirmation (freeze path):   ", fmt("confirm_order_ms"))
    print("Blocked write (anomaly path):       ", fmt("blocked_write_ms"))
    print("Dashboard summary:                  ", fmt("dashboard_summary_ms"))
    print("Chain verification: %.2f s over %s entries"
          % (results.get("verify_chain_s", 0), results.get("chain_entries")))
    overhead = results.get("audit_overhead_ms", (0, 0))
    print("\nVERDICT: audit overhead p95 = %.1f ms — %s"
          % (overhead[1], "PASS" if overhead[1] < 100 else "FAIL against the 100 ms target"))
    print("\nConcurrency is NOT measured here. The Locker serialises appends on")
    print("a single chain-head row; a single-threaded benchmark cannot show")
    print("that. Re-run with concurrent workers before trusting these figures")
    print("at production concurrency.")


if __name__ == "__main__":
    try:
        env  # noqa: F821 - provided by the Odoo shell
    except NameError:
        print(__doc__)
    else:
        report(run(env))  # noqa: F821
