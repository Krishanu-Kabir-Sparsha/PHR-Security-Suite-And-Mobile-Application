# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""GET /api/mobile/v1/me/capabilities -- what this deployment can actually do.

The app must not decide its own feature list. Two things vary underneath it and
neither is knowable from the client:

* **Which Odoo modules are installed.** A deployment without ``hr_holidays`` has
  no leave to show. Hard-coding a Leave tab there produces a screen that can only
  ever fail, and the user reads that as a broken app rather than as a module
  their company does not run.
* **What this particular user may see.** Two people on the same deployment have
  different groups, so Approvals is a real screen for one and an empty one for
  the other.

So the server answers both, per user, and the client renders what comes back.
Adding a module in Odoo makes the feature appear in the app with no release.

**This is not an authorisation boundary.** It drives menus. Every endpoint still
authorises independently -- see ``common.authenticated``, which runs the whole
request as the real user under their real record rules. A client that fabricates
a capability gets a nicer-looking menu and the same 403.

Feature keys are a contract with the client's `AppFeature` enum. Add, never
rename: an unknown key is ignored by an older app, but a renamed one silently
removes a feature from every installed copy.
"""

import logging

from odoo import http
from odoo.http import request

from .common import (
    authenticated,
    fail,
    ok,
    request_company,
    request_employee,
    request_token,
)

_logger = logging.getLogger(__name__)

# feature key -> (required module, group that makes it meaningful or None)
#
# The module is what decides whether the *data* exists; the group decides whether
# this user has anything to do there. A feature needs both to be offered.
#
# Groups are deliberately coarse. This picks which menu entries to draw, and a
# fine-grained check here would only duplicate -- and eventually contradict --
# the record rules that do the real work.
#
# **The module names are this deployment's, not stock Odoo's.** Perfect HR runs
# the Open HRMS community stack, where several capabilities come from a
# differently-named module than an Odoo Enterprise deployment would use:
#
#   payslips   hr_payroll_community  (NOT hr_payroll -- Enterprise only)
#   appraisal  oh_appraisal          (NOT hr_appraisal -- Enterprise only)
#
# Naming the Enterprise module would have been silently wrong rather than an
# error: the feature would simply never appear on any Perfect HR deployment,
# with nothing logged anywhere. ``test_capabilities`` checks every name against
# ir.module.module for exactly that reason.
FEATURE_MATRIX = [
    # --- Self-service. Every employee has these; no group required. -------
    ("attendance", "hr_attendance", None),
    ("leave", "hr_holidays", None),
    ("requests", "hr", None),
    ("profile", "hr", None),
    ("payslips", "hr_payroll_community", None),
    ("loans", "ohrms_loan", None),
    ("salary_advance", "ohrms_salary_advance", None),
    ("expenses", "hr_expense", None),
    ("documents", "hr_document_management_v1", None),
    ("assets", "employee_asset_management_agv1", None),
    ("announcements", "hr_reward_warning", None),
    ("appraisal", "oh_appraisal", None),
    ("resignation", "hr_resignation", None),
    ("skills", "hr_skills", None),
    ("timesheet", "hr_timesheet", None),
    # --- Manager and HR surfaces ------------------------------------------
    ("team", "hr", "hr_attendance.group_hr_attendance_manager"),
    ("approvals", "hr_holidays", "hr_holidays.group_hr_holidays_responsible"),
    ("workforce", "hr", "hr.group_hr_user"),
    ("recruitment", "hr_recruitment", "hr_recruitment.group_hr_recruitment_user"),
    (
        "payroll_admin",
        "hr_payroll_community",
        "hr_payroll_community.group_hr_payroll_community_manager",
    ),
    # --- Served by this module itself, so gated on nothing ----------------
    ("security_keys", None, None),
]

# Models whose CRUD the app needs in order to decide what to offer.
#
# Answered by asking Odoo -- ``has_access`` on an empty recordset, which is the
# model-level ir.model.access check -- and never by reading the Plaza access
# matrix. The matrix declares intent; ir.model.access, the record rules and the
# grant exceptions are what actually permit an operation. A button drawn from
# declared intent is a button that 403s, and the user cannot tell that apart
# from the app being broken.
PERMISSION_MODELS = [
    "hr.attendance",
    "hr.leave",
    "hr.leave.allocation",
    "hr.employee",
    "hr.contract",
    "hr.payslip",
    "hr.applicant",
    "hr.expense",
    "hr.loan",
    "salary.advance",
    "hr.resignation",
    "hr.appraisal",
    "hr.announcement",
    "hr.dms.document",
    "eam.asset.allocation",
]

_OPERATIONS = ("read", "create", "write", "unlink")


class MobileCapabilities(http.Controller):
    def _installed_modules(self):
        """Names of installed modules, as a set.

        sudo() because ``ir.module.module`` is readable only by system users and
        this is a question about the deployment, not about the user's data. No
        record content is exposed -- only which modules exist, which the user can
        already infer from the menus they see in the web client.
        """
        modules = (
            request.env["ir.module.module"]
            .sudo()
            .search_read([("state", "=", "installed")], ["name"])
        )
        return {module["name"] for module in modules}

    def _has_group(self, user, xmlid):
        """Group membership, tolerant of a group that does not exist here.

        ``has_group`` raises when the xmlid is unknown, which happens whenever a
        module is absent. That must not 500 the whole capabilities call -- the
        honest answer for an absent group is simply "no".
        """
        if not xmlid:
            return True
        try:
            return user.has_group(xmlid)
        except ValueError:
            return False

    def _permissions(self):
        """Real CRUD per model, as Odoo itself answers it.

        ``browse()`` -- an empty recordset -- makes this the model-level
        ir.model.access check, which is the right question for "may this user
        create leave at all?". Record rules narrow *which* records afterwards
        and are enforced on every actual call; they cannot be summarised here
        without inventing a record to test against.
        """
        permissions = {}
        for model_name in PERMISSION_MODELS:
            # A model from a module this deployment has not installed. Absent
            # rather than all-false: "you may not" and "there is no such thing
            # here" lead to different screens.
            if model_name not in request.env:
                continue
            model = request.env[model_name].browse()
            try:
                permissions[model_name] = {
                    operation: model.has_access(operation)
                    for operation in _OPERATIONS
                }
            except Exception:  # noqa: BLE001 - see below
                # A broken ACL or a model that cannot be browsed must not take
                # the whole capabilities call down with it; the app would then
                # have no menu at all. Withhold the permission instead, which
                # errs towards showing less.
                _logger.warning(
                    "Could not resolve access for %s; withholding", model_name
                )
                permissions[model_name] = {op: False for op in _OPERATIONS}
        return permissions

    def _assignable_roles(self, user):
        """Roles this user may preview, for the role-preview picker.

        Empty for everyone who cannot administer the catalog, which is what
        keeps the picker out of an ordinary employee's app entirely rather than
        showing it and refusing on tap.
        """
        if not (
            self._has_group(user, "sec_plaza_rbac.group_plaza_admin")
            or self._has_group(user, "sec_plaza_rbac.group_security_super_admin")
        ):
            return []

        try:
            roles = (
                request.env["role.plaza_model"]
                .sudo()
                .search([("active", "=", True)], order="sequence, code")
            )
        except KeyError:
            # sec_plaza_rbac absent. No catalog, so nothing to preview.
            return []

        return [
            {
                "code": role.code,
                "name": role.name,
                "approval_tier": role.is_approval_tier,
            }
            for role in roles
        ]

    def _preview_permissions(self, role):
        """What a role's own access would permit, ignoring who is asking.

        Answers "if someone held only this role, what could they do?" — which is
        the question an administrator has when configuring the catalog, and
        which they can otherwise only answer by creating a throwaway user.

        Computed from ``ir.model.access`` for the role's backing group and every
        group that group implies, rather than from the Plaza access lines. The
        lines are declarative; this reports what Odoo would actually allow, so a
        preview that looks wrong is a real finding rather than a typo in the
        catalog.

        Read-only and side-effect free: nothing about the caller's own session
        changes, and the caller's own permissions are unaffected.
        """
        group = role.group_id
        if not group:
            return {model: {op: False for op in _OPERATIONS}
                    for model in PERMISSION_MODELS if model in request.env}

        # trans_implied_ids, NOT implied_ids. The latter is only the groups this
        # one directly implies; Odoo computes the transitive closure separately
        # (res.groups._compute_trans_implied). Using the direct set would
        # under-report a role that inherits through a chain -- Plaza Role ->
        # HR Officer -> HR Employee -- and the preview would show a role as
        # more restricted than it really is, which is the dangerous direction
        # for something an administrator uses to check a configuration.
        groups = group | group.trans_implied_ids| group.implied_ids

        permissions = {}
        for model_name in PERMISSION_MODELS:
            if model_name not in request.env:
                continue
            rules = (
                request.env["ir.model.access"]
                .sudo()
                .search(
                    [
                        ("model_id.model", "=", model_name),
                        ("group_id", "in", groups.ids),
                        ("active", "=", True),
                    ]
                )
            )
            permissions[model_name] = {
                "read": any(rules.mapped("perm_read")),
                "create": any(rules.mapped("perm_create")),
                "write": any(rules.mapped("perm_write")),
                "unlink": any(rules.mapped("perm_unlink")),
            }
        return permissions

    def _roles(self, user):
        """The user's Plaza roles, with what Odoo's ACLs cannot express.

        Approval tier, WebAuthn requirement and the create/approve split are
        properties of the role catalog, not of ir.model.access. The app needs
        them to decide whether to show an approval surface at all, and to tell
        someone why they are being asked to enrol an authenticator.
        """
        # sudo to read the catalog, deliberately and narrowly. An ordinary
        # employee has no read access to role.plaza_model -- the catalog is
        # compliance configuration -- but they are entitled to know which roles
        # they themselves hold and why they are being asked to enrol a key.
        # Only the current user's own roles are ever read here.
        try:
            held = user.sudo().plaza_role_ids
        except AttributeError:
            # sec_plaza_rbac absent or mid-upgrade. The app degrades to
            # permissions-only, which still produces a correct menu because
            # permissions come from Odoo's own check rather than the catalog.
            _logger.warning("plaza_role_ids unavailable; reporting no roles")
            return []

        roles = []
        for role in held:
            capabilities = [
                {
                    "transaction_type": line.transaction_type,
                    "capability": line.capability,
                }
                for line in role.access_line_ids
                if line.transaction_type and line.capability != "none"
            ]
            roles.append(
                {
                    "code": role.code,
                    "name": role.name,
                    "approval_tier": role.is_approval_tier,
                    "requires_webauthn": bool(role.requires_webauthn),
                    "capabilities": capabilities,
                }
            )
        return roles

    def _divergence(self, user, permissions):
        """Where the catalog and reality disagree, for this user.

        The Plaza access matrix is declarative: nothing writes it into
        ir.model.access. So a role can declare create on hr.payslip while the
        backing group carries no such right, or -- more serious -- a user can
        hold rights the catalog never granted them. Neither is detectable
        today, and the monthly review reads the declaration rather than the
        enforcement, so it would sign off on a matrix that does not describe
        the system.

        Reported per user rather than per role because that is the question
        that matters: what can this person actually do, versus what were they
        meant to be able to do.
        """
        try:
            held = user.sudo().plaza_role_ids
        except AttributeError:
            return []

        declared = {}
        for role in held:
            for line in role.access_line_ids:
                # One area covers several record types -- "Leave" is both
                # hr.leave and hr.leave.allocation -- so a line contributes its
                # declaration to each of them. `record_types` replaced the old
                # single `model_name` when permissions became one area and one
                # level; reading the old field here would have silently emptied
                # the divergence report rather than failing loudly.
                for model_name in (line.record_types or "").split(","):
                    model_name = model_name.strip()
                    if not model_name:
                        continue
                    entry = declared.setdefault(
                        model_name, {op: False for op in _OPERATIONS}
                    )
                    entry["read"] = entry["read"] or line.perm_read
                    entry["create"] = entry["create"] or line.perm_create
                    entry["write"] = entry["write"] or line.perm_write
                    entry["unlink"] = entry["unlink"] or line.perm_unlink

        findings = []
        for model_name, actual in permissions.items():
            expected = declared.get(model_name)
            if expected is None:
                # Granted but never declared. This is the direction that
                # matters most: access nobody wrote down and the review will
                # not examine.
                if any(actual.values()):
                    findings.append(
                        {
                            "model": model_name,
                            "kind": "undeclared",
                            "operations": sorted(
                                op for op, allowed in actual.items() if allowed
                            ),
                        }
                    )
                continue

            over = sorted(
                op for op in _OPERATIONS if actual[op] and not expected[op]
            )
            under = sorted(
                op for op in _OPERATIONS if expected[op] and not actual[op]
            )
            if over:
                findings.append(
                    {"model": model_name, "kind": "over_granted", "operations": over}
                )
            if under:
                # Not a security hole, but it means the app would have hidden a
                # feature the catalog says this role should have -- which reads
                # to the user as a missing feature rather than a config gap.
                findings.append(
                    {
                        "model": model_name,
                        "kind": "not_granted",
                        "operations": under,
                    }
                )
        return findings

    def _session_strength(self, user, company):
        """How this session was authenticated, and what else was available.

        Three separate facts, and conflating them would lose the one that
        matters. ``auth_mode`` is what actually happened. ``auth_modes_available``
        is what this account may use in this company -- already intersected with
        the role rule, so an approver sees only the advanced option even in a
        company that permits basic. ``auth_upgrade_available`` is the two
        compared, which is the only question the Settings screen needs to ask
        before deciding whether to offer an upgrade.
        """
        token = request_token()
        current = token.auth_mode if token else "advance"
        try:
            available = user._mobile_auth_modes_for(company)
        except AttributeError:
            # Mid-upgrade, before res_company.py has loaded its inherit.
            _logger.warning(
                "Mobile auth policy unavailable; reporting the current mode "
                "as the only one."
            )
            available = [current]
        return {
            "auth_mode": current,
            "auth_modes_available": available,
            "auth_upgrade_available": current == "basic" and "advance" in available,
        }

    @http.route(
        "/api/mobile/v1/me/capabilities",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def capabilities(self, preview_role=None, **kwargs):
        user = request.env.user
        installed = self._installed_modules()
        params = request.env["ir.config_parameter"].sudo()

        features = []
        for key, module, group in FEATURE_MATRIX:
            if module and module not in installed:
                continue
            if not self._has_group(user, group):
                continue
            features.append(key)

        employee = request_employee()
        company = request_company()

        permissions = self._permissions()
        roles = self._roles(user)
        previewing = None

        if preview_role:
            # Restricted to people who administer the catalog. To anyone else
            # this is a way to enumerate the access model of roles they do not
            # hold, which is reconnaissance rather than a feature.
            if not (
                self._has_group(user, "sec_plaza_rbac.group_plaza_admin")
                or self._has_group(user, "sec_plaza_rbac.group_security_super_admin")
            ):
                return fail(
                    403,
                    "Only a security administrator can preview a role.",
                    code="preview_forbidden",
                    log="role preview refused for %s" % user.login,
                )

            role = (
                request.env["role.plaza_model"]
                .sudo()
                .search([("code", "=", preview_role)], limit=1)
            )
            if not role:
                return fail(
                    404,
                    "That role no longer exists.",
                    code="role_not_found",
                    log="preview of unknown role %r" % preview_role,
                )

            # The preview replaces the permission set wholesale rather than
            # merging with the caller's own. A merge would show the union, and
            # an administrator checking whether a role is too permissive would
            # be looking largely at their own access.
            permissions = self._preview_permissions(role)
            previewing = {
                "code": role.code,
                "name": role.name,
                "approval_tier": role.is_approval_tier,
                "requires_webauthn": bool(role.requires_webauthn),
            }
            _logger.info(
                "Role preview: %s viewed as %s", user.login, role.code
            )

        # The divergence report is shown only to someone who can act on it.
        # To everyone else it is noise about a configuration they cannot see,
        # let alone change.
        show_divergence = self._has_group(
            user, "sec_plaza_rbac.group_plaza_compliance"
        ) or self._has_group(user, "sec_plaza_rbac.group_plaza_admin")

        return ok(
            {
                "features": features,
                "permissions": permissions,
                "roles": roles,
                "divergence": [] if previewing else (
                    self._divergence(user, permissions)
                    if show_divergence
                    else []
                ),
                # Present only while previewing. The app renders a persistent
                # banner off this, because a preview that looks like the real
                # thing is worse than no preview: an administrator could
                # conclude their own access was wrong.
                "previewing_role": previewing,
                # Roles this user may preview. Empty for everyone who cannot.
                "assignable_roles": self._assignable_roles(user),
                # The app cannot show anyone's own HR data without this link, and
                # the absence is an HR data task rather than a fault. Reported
                # here so the app can say so on the first screen instead of
                # letting every request fail with a 404 in turn.
                "has_employee_record": bool(employee),
                # Position and standing. The first half of authorisation is who
                # somebody *is*: a role list means little to the person holding
                # it until it sits next to their own job title and department.
                #
                # Repeated from the sign-in response deliberately. This endpoint
                # is what the app re-reads when it comes back to the foreground,
                # so a promotion or a transfer shows up without signing out --
                # whereas the sign-in payload is a snapshot of one moment.
                "employment": {
                    "employee_code": employee.identification_id or None,
                    "job_position": employee.job_id.name or None,
                    "job_title": employee.job_title or None,
                    "department": employee.department_id.name or None,
                    "manager": employee.parent_id.name or None,
                    "work_location": employee.work_location_id.name or None,
                    "shift": employee.resource_calendar_id.name or None,
                }
                if employee
                else None,
                # Which company this session is operating in, and which others
                # the user could switch to via POST /auth/company. Sent so the
                # app can show the current company in its header rather than
                # leaving somebody with two employments unsure which they are
                # looking at.
                "company": {
                    "id": str(company.id),
                    "name": company.name,
                }
                if company
                else None,
                "companies": [
                    {"id": str(c.id), "name": c.name}
                    for c in user._mobile_login_companies()
                ],
                # How well this session was authenticated, and whether it could
                # be stronger. A basic session is a real reduction, so the app
                # is told plainly rather than left to infer it -- Settings shows
                # it, and offers the upgrade where the company permits one.
                **self._session_strength(user, company),
                # Diagnostics. Shown in More > About so that "which modules does
                # my server have?" is answerable from the phone, without a
                # support round-trip through someone with Odoo backend access.
                "hr_modules_installed": sorted(
                    name for name in installed if name.startswith("hr")
                ),
                # What this server will accept as the mobile app.
                #
                # Reported so the app can hold it against its own signing
                # certificate and say plainly whether they match. Android's
                # refusal in this case is "RP ID cannot be validated", which
                # names neither value and is therefore impossible to act on:
                # the reader cannot tell a stale build from a wrong parameter
                # from a fingerprint typed with one character missing.
                #
                # Not a secret. It is already published, by design, at
                # /.well-known/assetlinks.json.
                "expected_app": {
                    "package": params.get_param(
                        "sec_webauthn.android_package", ""
                    ),
                    "sha256": params.get_param(
                        "sec_webauthn.android_sha256", ""
                    ),
                },
            }
        )
