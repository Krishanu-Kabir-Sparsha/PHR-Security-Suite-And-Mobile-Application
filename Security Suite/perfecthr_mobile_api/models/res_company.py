# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Per-company rules for signing in from the mobile app.

WHY THE POLICY LIVES ON res.company
-----------------------------------
The requirement is "rules need to be set for organizations; who logs in with
which company". Half of that Odoo already models, and models well:

    res.users.company_ids   the companies a user may operate in
    res.users.company_id    the one they land in by default

That IS the who-may-log-into-which-company rule, it is already enforced
everywhere else in the product, and it is what an HR administrator already
maintains. Building a second table to say the same thing would create two
sources of truth that drift apart, and the divergence report in
``controllers/capabilities.py`` exists precisely because that has happened
before in this codebase. So sign-in *enforces* ``company_ids`` rather than
re-declaring it.

What Odoo does **not** model is the other half: how strongly a given
organisation wants its people to prove who they are on a phone, and whether
signing in should record attendance. Those are genuinely new, genuinely
per-company, and that is what this file adds.

THE THREE SETTINGS
------------------
``mobile_login_enabled``
    Opt-in, and it controls *disclosure* rather than access. The company
    dropdown on the sign-in screen is drawn before anyone has typed a password,
    so whatever it lists is readable by anybody who knows the tenant URL. A
    tenant with a dozen subsidiaries should not publish that org chart to an
    anonymous caller, so nothing is listed until an administrator says so.

    Leaving every company unticked is a valid configuration, not a broken one:
    the endpoint then returns an empty list, the app skips the company step
    entirely, and each user simply lands in their own default company. Ticking
    is only needed where people must *choose*.

``mobile_auth_policy``
    Which proofs this organisation accepts. ``advance`` is the default because
    it is the behaviour that already shipped, and quietly relaxing an existing
    control on upgrade would be the worst possible default.

``mobile_auto_checkin``
    Whether a completed sign-in also records attendance. Default on, because
    that is the stated requirement, but per-company because attendance feeds
    payroll and not every customer wants it captured this way.

WHAT THIS FILE DELIBERATELY CANNOT DO
-------------------------------------
No setting here can make a sign-in *weaker* than the user's own role requires.
An approver's account is forced to the strong path regardless of what its
company permits -- see ``_mobile_auth_modes_for`` below. A company-level switch
that could downgrade the people who authorise overrides would be a way to turn
FR-5.3 off from a settings page.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Wire values shared with the app. Add, never rename: an unknown mode from a
# newer server degrades to "advance" on an older app, which is the safe
# direction, but a renamed one would silently change what a company permits.
AUTH_MODE_BASIC = "basic"
AUTH_MODE_ADVANCE = "advance"

# Policy -> the modes offered, most secure first. The order is the order the
# app draws the buttons in, and the first entry is the one it preselects.
POLICY_MODES = {
    "advance": [AUTH_MODE_ADVANCE],
    "choice": [AUTH_MODE_ADVANCE, AUTH_MODE_BASIC],
    "basic": [AUTH_MODE_BASIC, AUTH_MODE_ADVANCE],
}


class ResCompany(models.Model):
    _inherit = "res.company"

    mobile_login_enabled = fields.Boolean(
        string="Show in Mobile Sign-in",
        default=False,
        help="List this company in the mobile app's company picker.\n\n"
        "That picker is drawn before anyone signs in, so ticking this makes "
        "the company's name and logo readable by anyone who knows your Perfect "
        "HR address. Tick it only where people genuinely have to choose "
        "between companies. If nothing is ticked, the app skips the step and "
        "each person lands in their own default company, which is the right "
        "setting for most tenants.",
    )
    mobile_auth_policy = fields.Selection(
        selection=[
            ("advance", "Advanced only - fingerprint on a paired device"),
            ("choice", "Let the user choose"),
            ("basic", "Basic by default, advanced still available"),
        ],
        string="Mobile Sign-in Policy",
        default="advance",
        required=True,
        help="How strongly people in this company must prove who they are when "
        "signing in on a phone.\n\n"
        "Advanced asks for a fingerprint and a signature from the paired "
        "handset, so a stolen password alone is not enough. Basic accepts the "
        "password by itself.\n\n"
        "This cannot weaken an approver: anyone holding an approval tier is "
        "always required to use the advanced path, whatever is set here.",
    )
    mobile_auto_checkin = fields.Boolean(
        string="Sign-in Records Attendance",
        default=True,
        help="Check the employee in automatically on their first mobile "
        "sign-in of the day.\n\n"
        "Nothing is recorded if they are already checked in -- from a "
        "fingerprint device, the kiosk or another handset -- or if they are on "
        "approved leave. Checking out is always a deliberate action; signing "
        "out never ends an attendance record.",
    )

    @api.constrains("mobile_login_enabled", "mobile_auth_policy")
    def _check_mobile_policy(self):
        """A listed company must still be reachable by something.

        Cheap guard against the one combination that produces a dead end: a
        company offered in the picker whose policy no user could satisfy. There
        is no such combination today, and this constraint exists so that adding
        a policy value later cannot introduce one silently.
        """
        for company in self:
            if not company.mobile_login_enabled:
                continue
            if company.mobile_auth_policy not in POLICY_MODES:
                raise ValidationError(
                    _(
                        "%(company)s is offered in the mobile sign-in screen "
                        "but its sign-in policy is not one this server "
                        "understands.",
                        company=company.display_name,
                    )
                )

    # ------------------------------------------------------------------
    # Read by the sign-in endpoints
    # ------------------------------------------------------------------
    def _mobile_auth_modes(self):
        """The modes this company permits, most secure first."""
        self.ensure_one()
        return list(POLICY_MODES.get(self.mobile_auth_policy, [AUTH_MODE_ADVANCE]))

    def _mobile_public_payload(self):
        """The company as an anonymous caller may see it.

        Names and a logo URL, and nothing else. No address, no VAT number, no
        employee counts -- this is read before authentication, so every field
        added here is a field published to the internet.
        """
        self.ensure_one()
        return {
            "id": str(self.id),
            "name": self.name,
            # write_date makes the URL change when the logo does, so a cached
            # image cannot outlive a rebrand.
            "logo_url": "/web/image/res.company/%s/logo/128x128?unique=%s"
            % (self.id, int(self.write_date.timestamp()))
            if self.logo
            else None,
            "auth_modes": self._mobile_auth_modes(),
            "auto_checkin": bool(self.mobile_auto_checkin),
        }


class ResUsersMobilePolicy(models.Model):
    """Which companies and which proofs this particular user may sign in with."""

    _inherit = "res.users"

    def _mobile_login_companies(self):
        """Companies this user may sign into, in the app's display order.

        ``company_ids`` is the authority, per the module docstring. Companies
        the user holds but which are archived are dropped: an archived company
        is one the business has stopped operating, and landing in it would
        produce a session whose every record rule points at nothing.
        """
        self.ensure_one()
        return self.sudo().company_ids.filtered("active").sorted("name")

    def _mobile_requires_advance(self):
        """True when this account may not use the basic path, whatever the
        company permits.

        Three grounds, and any one is enough:

        * The user holds a Plaza role marked as an approval tier. Their
          signature authorises other people's overrides, so a password-only
          session for that account is a password-only override in waiting.
        * The role is flagged ``requires_webauthn`` in the catalog.
        * The user is a security administrator or a system administrator.

        Read defensively: ``sec_plaza_rbac`` may be absent or mid-upgrade, and
        the honest answer when the catalog cannot be read is to require the
        stronger proof rather than to assume the weaker one is fine.
        """
        self.ensure_one()
        user = self.sudo()

        for xmlid in (
            "sec_plaza_rbac.group_security_super_admin",
            "sec_plaza_rbac.group_plaza_admin",
            "base.group_system",
        ):
            try:
                if user.has_group(xmlid):
                    return True
            except ValueError:
                # The module providing that group is not installed here.
                continue

        try:
            roles = user.plaza_role_ids
        except AttributeError:
            _logger.warning(
                "plaza_role_ids unavailable while deciding the sign-in mode "
                "for %s; requiring the advanced path.",
                user.login,
            )
            return True

        for role in roles:
            if role.is_approval_tier or role.requires_webauthn:
                return True
        return False

    def _mobile_auth_modes_for(self, company):
        """The modes offered to this user in this company, most secure first.

        The intersection of what the company permits and what the account is
        allowed to use -- never the union. A company set to ``basic`` still
        gets ``advance`` back for an approver, and that is the whole point of
        computing it here rather than letting the app read the company policy
        and decide for itself.
        """
        self.ensure_one()
        modes = company._mobile_auth_modes() if company else [AUTH_MODE_ADVANCE]
        if self._mobile_requires_advance():
            return [AUTH_MODE_ADVANCE]
        return modes
