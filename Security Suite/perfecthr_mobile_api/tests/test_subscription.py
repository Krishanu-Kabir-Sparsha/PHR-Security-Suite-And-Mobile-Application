# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The workspace's own plan, as the app reads it.

Three properties are worth holding onto.

**Absent is a normal answer.** An on-premise install has no subscription
snapshot, and the right response is "there is no plan here", not an empty plan
card that reads as a fault.

**Limits come from the snapshot, usage is measured now.** Taking usage from the
snapshot would report provisioning-day figures forever, which is the kind of
number that looks right and never is.

**Nothing blocks work.** A quota is advisory. A company that cannot record
attendance because it is near a storage limit has been failed by its software,
not by its plan.
"""

import json

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSubscriptionSnapshot(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Snapshot = self.env["perfecthr.mobile.subscription"]
        self.params = self.env["ir.config_parameter"].sudo()

    def _write(self, **overrides):
        info = {
            "package_name": "Enterprise",
            "tier_level": "enterprise",
            "billing_plan_label": "Annual",
            "state": "active",
            "is_trial": False,
            "date_start": "2026-01-01",
            "date_next_invoice": "2027-01-01",
            "currency": "৳",
            "monthly_price": 12000.0,
            "storage_limit_gb": 50.0,
            "user_limit": 100,
            "subscription_ref": "SUB-00017",
            "manage_url": "https://perfecthr.net/my/subscriptions/17",
            "upgrade_url": "https://perfecthr.net/my/subscriptions/17/upgrade",
            "synced_at": "2026-09-20T10:00:00",
        }
        info.update(overrides)
        self.params.set_param("saas.subscription_info", json.dumps(info))
        return info

    # -- absence ---------------------------------------------------------
    def test_no_snapshot_is_not_an_error(self):
        """An on-premise install simply has no plan to talk about."""
        self.params.set_param("saas.subscription_info", "")
        self.assertIsNone(self.Snapshot.overview())

    def test_a_corrupt_snapshot_reads_as_absent(self):
        """Broken configuration must not take the Settings screen down.

        Logged loudly, because it should never happen -- but answered as "no
        subscription", since a 500 here costs the administrator the whole
        screen and tells them less than an empty one would.
        """
        self.params.set_param("saas.subscription_info", "{not json at all")
        self.assertIsNone(self.Snapshot.overview())

    def test_a_json_list_is_rejected_like_corruption(self):
        """Valid JSON of the wrong shape is still not a snapshot."""
        self.params.set_param("saas.subscription_info", "[1, 2, 3]")
        self.assertIsNone(self.Snapshot.overview())

    # -- the plan --------------------------------------------------------
    def test_plan_facts_come_through(self):
        self._write()
        view = self.Snapshot.overview()
        self.assertEqual(view["plan_name"], "Enterprise")
        self.assertEqual(view["reference"], "SUB-00017")
        self.assertEqual(view["status_label"], "Active")
        self.assertFalse(view["is_trial"])

    def test_price_is_formatted_once_on_the_server(self):
        """The currency here is a symbol, not a code.

        The phone has no locale rule that turns a bare symbol and a float into
        the string a Bangladeshi customer expects, so the formatting decision
        is made once, here, and the app prints what it is given.
        """
        self._write()
        self.assertEqual(
            self.Snapshot.overview()["price"]["display"],
            "৳12,000.00 / month",
        )

    def test_a_free_plan_reports_no_price_rather_than_zero(self):
        """Nothing costing nothing is a missing row, not a row saying 0.00."""
        self._write(monthly_price=0.0)
        self.assertIsNone(self.Snapshot.overview()["price"])

    # -- which date counts -----------------------------------------------
    def test_a_trial_counts_down_to_its_own_end_date(self):
        """Reading the invoice date on a trial would promise months that are
        not there -- the single most misleading thing this screen could say."""
        self._write(
            is_trial=True,
            trial_end_date="2026-09-29",
            date_next_invoice="2027-01-01",
        )
        view = self.Snapshot.overview()
        self.assertEqual(view["renews_on"], "2026-09-29")
        self.assertEqual(view["health"], "trial")

    def test_a_paid_plan_counts_down_to_the_invoice(self):
        self._write()
        self.assertEqual(self.Snapshot.overview()["renews_on"], "2027-01-01")

    # -- health ----------------------------------------------------------
    def test_suspension_outranks_a_trial(self):
        """The worst true thing is the one worth leading with.

        A suspended trial that reported itself as a trial would tell somebody
        their workspace was fine while their staff could not sign in.
        """
        self._write(is_trial=True, state="suspended", trial_end_date="2026-12-01")
        self.assertEqual(self.Snapshot.overview()["health"], "suspended")

    def test_an_expired_plan_says_so(self):
        self._write(state="expired")
        self.assertEqual(self.Snapshot.overview()["health"], "ended")

    def test_a_healthy_plan_far_from_renewal_is_simply_active(self):
        self._write(date_next_invoice="2099-01-01")
        view = self.Snapshot.overview()
        self.assertEqual(view["health"], "active")

    # -- quotas ----------------------------------------------------------
    def test_usage_is_measured_live_not_read_from_the_snapshot(self):
        """The snapshot carries limits only.

        There is at least one active internal user in any database running
        this test -- the one running it -- so a zero here would mean the count
        came from the snapshot, which carries no usage at all.
        """
        self._write()
        users = self.Snapshot.overview()["usage"]["users"]
        self.assertGreater(users["used"], 0)
        self.assertEqual(users["limit"], 100)

    def test_a_zero_limit_means_unlimited_not_full(self):
        """The arithmetic trap. A plan with no seat cap must not divide by
        zero, and must not render as a bar pinned at 100%."""
        self._write(user_limit=0, storage_limit_gb=0)
        usage = self.Snapshot.overview()["usage"]
        for quota in (usage["users"], usage["storage"]):
            self.assertTrue(quota["unlimited"])
            self.assertIsNone(quota["limit"])
            self.assertIsNone(quota["ratio"])
            self.assertFalse(quota["near_limit"])

    def test_being_over_a_limit_is_reported_but_never_blocks(self):
        """A company past its seat count keeps working.

        The ratio is clamped so the bar cannot overflow its track, the warning
        is raised, and nothing anywhere returns a refusal.
        """
        self._write(user_limit=1)
        users = self.Snapshot.overview()["usage"]["users"]
        self.assertTrue(users["near_limit"])
        self.assertLessEqual(users["ratio"], 1.0)

    def test_apps_are_named_the_way_a_person_would_name_them(self):
        """Display names, never module names.

        This list answers "does our plan cover what we need?", and
        hr_attendance answers a different question than the one asked.
        """
        self._write()
        apps = self.Snapshot.overview()["apps"]
        self.assertTrue(all("_" not in name for name in apps), apps)

    # -- staleness -------------------------------------------------------
    def test_the_snapshot_reports_when_it_was_written(self):
        """Saying when a figure was last confirmed is the difference between
        a stale number and a wrong one."""
        self._write()
        self.assertEqual(self.Snapshot.overview()["synced_at"], "2026-09-20T10:00:00")


@tagged("post_install", "-at_install")
class TestSubscriptionVisibility(TransactionCase):
    """Who may read the plan.

    This is a real authorisation boundary, not a menu hint. What a company pays
    and when it renews are facts about the employer's commercial relationship
    with its vendor, and a phone is read over shoulders far more often than a
    desktop is.
    """

    def setUp(self):
        super().setUp()
        self.staff = self.env["res.users"].create(
            {
                "name": "Ordinary Staff",
                "login": "ordinary.staff@example.internal",
                "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )

    def test_an_ordinary_employee_may_not(self):
        self.assertFalse(self.staff._may_view_subscription())

    def test_a_system_administrator_may(self):
        self.staff.groups_id = [(4, self.env.ref("base.group_system").id)]
        self.assertTrue(self.staff._may_view_subscription())

    def test_an_hr_manager_may(self):
        self.staff.groups_id = [(4, self.env.ref("hr.group_hr_manager").id)]
        self.assertTrue(self.staff._may_view_subscription())

    def test_an_absent_group_is_a_no_not_a_crash(self):
        """sec_plaza_rbac may be missing or mid-upgrade.

        The honest answer for a group that does not exist here is "no"; a
        ValueError would take the whole Settings screen with it.
        """
        original = type(self.staff)._SUBSCRIPTION_GROUPS
        try:
            type(self.staff)._SUBSCRIPTION_GROUPS = ("no_such_module.no_such_group",)
            self.assertFalse(self.staff._may_view_subscription())
        finally:
            type(self.staff)._SUBSCRIPTION_GROUPS = original
