import 'package:flutter/foundation.dart';

import 'model_access.dart';

/// A feature the deployment may or may not offer.
///
/// Wire values are a contract with `FEATURE_MATRIX` in the Odoo module's
/// `controllers/capabilities.py`. **Add, never rename.** An unknown key is
/// ignored by an older copy of the app, but a renamed one silently removes a
/// feature from every installed copy at once.
///
/// Module names are **this deployment's**, not stock Odoo's. Perfect HR runs the
/// Open HRMS community stack, so payslips come from `hr_payroll_community` and
/// appraisals from `oh_appraisal` — the Enterprise-only `hr_payroll` and
/// `hr_appraisal` are not installed and never will be. These strings are shown
/// to the user as "needs <module>", so a wrong one sends someone looking in
/// Odoo for an app that does not exist.
enum AppFeature {
  // Self-service.
  attendance('attendance', 'Attendance', 'hr_attendance'),
  leave('leave', 'Leave', 'hr_holidays'),
  requests('requests', 'Requests', 'hr'),
  profile('profile', 'My profile', 'hr'),
  payslips('payslips', 'Payslips', 'hr_payroll_community'),
  loans('loans', 'Loans', 'ohrms_loan'),
  salaryAdvance('salary_advance', 'Salary advance', 'ohrms_salary_advance'),
  expenses('expenses', 'Expenses', 'hr_expense'),
  documents('documents', 'Documents', 'hr_document_management_v1'),
  assets('assets', 'My assets', 'employee_asset_management_agv1'),
  announcements('announcements', 'Announcements', 'hr_reward_warning'),
  appraisal('appraisal', 'Appraisal', 'oh_appraisal'),
  resignation('resignation', 'Resignation', 'hr_resignation'),
  skills('skills', 'Skills', 'hr_skills'),
  timesheet('timesheet', 'Timesheet', 'hr_timesheet'),
  // Manager and HR surfaces.
  team('team', 'My team', 'hr'),
  approvals('approvals', 'Approvals', 'hr_holidays'),
  workforce('workforce', 'Workforce', 'hr'),
  recruitment('recruitment', 'Recruitment', 'hr_recruitment'),
  payrollAdmin('payroll_admin', 'Payroll administration',
      'hr_payroll_community'),
  // Served by the mobile API module itself.
  securityKeys('security_keys', 'Security keys', null);

  const AppFeature(this.wireValue, this.label, this.odooModule);

  final String wireValue;

  /// Name shown to the user when listing what is and is not available.
  final String label;

  /// The Odoo module that provides it, for diagnostics. Null when this module
  /// provides the feature itself.
  final String? odooModule;

  static AppFeature? fromWire(String value) {
    for (final feature in AppFeature.values) {
      if (feature.wireValue == value) return feature;
    }
    // Deliberately null rather than a throw. A newer server may offer features
    // this build has never heard of, and that must not break the app — it
    // simply cannot show them.
    return null;
  }
}

/// What this deployment offers **this user**.
///
/// The app does not decide its own feature list. Which Odoo modules are
/// installed, and which groups the user is in, both vary per deployment and
/// neither is knowable from the client. Hard-coding a Leave tab on a server
/// without `hr_holidays` produces a screen that can only ever fail, and the
/// user reads that as a broken app rather than as a module their company does
/// not run.
///
/// **Not an authorisation boundary.** This draws menus. Every endpoint
/// authorises independently, server-side, against the user's real Odoo groups
/// and record rules — so a tampered client gets a nicer menu and the same 403.
@immutable
class AppCapabilities {
  const AppCapabilities({
    required this.features,
    required this.hasEmployeeRecord,
    this.hrModulesInstalled = const [],
    this.permissions = const {},
    this.roles = const [],
    this.divergence = const [],
    this.previewingRole,
    this.assignableRoles = const [],
    this.expectedPackage,
    this.expectedFingerprint,
  });

  final Set<AppFeature> features;

  /// Real CRUD per Odoo model, from the server's own `has_access` check.
  ///
  /// Three different questions decide whether a control appears, and they are
  /// deliberately separate:
  ///
  ///   [features]    — does this deployment have the module at all?
  ///   [permissions] — may this user perform the operation?
  ///   [roles]       — what duty does the Plaza catalog give them?
  ///
  /// Collapsing them loses information the user needs. "Your company does not
  /// use payroll" and "you are not allowed to see payroll" are different
  /// sentences, and only one of them is worth asking an administrator about.
  final Map<String, ModelAccess> permissions;

  /// The Plaza Model roles the user holds.
  final List<PlazaRole> roles;

  /// Where the catalog and reality disagree. Empty unless the user can act on
  /// it — to anyone else it is noise about a configuration they cannot see.
  final List<DivergenceFinding> divergence;

  /// Set only while previewing another role.
  ///
  /// The app renders a persistent banner off this. A preview that looked like
  /// the real thing would be worse than no preview at all: an administrator
  /// could conclude their own access was wrong and "fix" something that was
  /// never broken.
  final AssignableRole? previewingRole;

  /// Roles this user may preview. Empty for everyone who cannot administer the
  /// catalog, which keeps the picker out of an ordinary employee's app rather
  /// than showing it and refusing on tap.
  final List<AssignableRole> assignableRoles;

  bool get isPreviewing => previewingRole != null;

  /// The app identity this server will accept for passkeys.
  ///
  /// Reported so the app can hold it against its own signing certificate.
  /// Android's refusal when they disagree is "RP ID cannot be validated",
  /// which names neither value — so without this, telling a stale build apart
  /// from a wrong parameter is guesswork.
  ///
  /// Neither is a secret: both are already published at
  /// `/.well-known/assetlinks.json`.
  final String? expectedPackage;
  final String? expectedFingerprint;

  /// Whether an `hr.employee` record is linked to this login.
  ///
  /// Without it there is no "me" to report attendance or leave for, and every
  /// data endpoint answers 404 in turn. Knowing it up front lets the app say so
  /// once, plainly, instead of failing repeatedly.
  final bool hasEmployeeRecord;

  /// Diagnostics: the HR modules present on the server.
  final List<String> hrModulesInstalled;

  bool has(AppFeature feature) => features.contains(feature);

  /// Access to one model, defaulting to none.
  ///
  /// A model the server did not report resolves to [ModelAccess.none] rather
  /// than throwing: a newer app asking an older server about a model it has
  /// never heard of should hide the control, not crash.
  ModelAccess accessTo(String model) =>
      permissions[model] ?? ModelAccess.none;

  bool can(String model, ModelOperation operation) =>
      accessTo(model).allows(operation);

  /// Whether the user approves this class of transaction under any role.
  ///
  /// Distinct from having write access to the underlying model. Odoo's ACL
  /// cannot tell an approval apart from any other write, and the difference is
  /// the whole point of the catalog: a Line Manager writing to `hr.leave` is
  /// approving somebody's request, while an employee writing to it is editing
  /// their own.
  bool approves(TransactionType type) =>
      roles.any((role) => role.canApprove(type));

  /// The highest approval tier held, for the override workflow and for
  /// explaining why a security key is required.
  ApprovalTier get highestTier {
    var highest = ApprovalTier.none;
    for (final role in roles) {
      if (role.approvalTier.index > highest.index) {
        highest = role.approvalTier;
      }
    }
    return highest;
  }

  /// True when any role held obliges the user to enrol an authenticator.
  bool get requiresWebauthn => roles.any((role) => role.requiresWebauthn);

  /// Used before capabilities have loaded, and when the endpoint is missing.
  ///
  /// Assumes nothing is available rather than assuming everything is. An app
  /// that offers a feature it cannot deliver is worse than one that reveals a
  /// feature a moment late.
  static const AppCapabilities unknown = AppCapabilities(
    features: <AppFeature>{},
    hasEmployeeRecord: true,
  );

  factory AppCapabilities.fromJson(Map<String, dynamic> json) {
    final raw = json['features'];
    final features = <AppFeature>{};
    if (raw is List) {
      for (final item in raw) {
        final feature = AppFeature.fromWire('$item');
        if (feature != null) features.add(feature);
      }
    }

    final modules = json['hr_modules_installed'];
    final rawPermissions = json['permissions'];
    final rawRoles = json['roles'];
    final rawDivergence = json['divergence'];
    final rawPreview = json['previewing_role'];
    final rawExpected = json['expected_app'];
    final expected = rawExpected is Map
        ? rawExpected.cast<String, Object?>()
        : const <String, Object?>{};
    final rawAssignable = json['assignable_roles'];

    final permissions = <String, ModelAccess>{};
    if (rawPermissions is Map) {
      rawPermissions.forEach((key, value) {
        if (value is Map) {
          permissions['$key'] =
              ModelAccess.fromJson(value.cast<String, Object?>());
        }
      });
    }

    return AppCapabilities(
      features: features,
      permissions: permissions,
      roles: rawRoles is List
          ? rawRoles
              .whereType<Map<Object?, Object?>>()
              .map((r) => PlazaRole.fromJson(r.cast<String, Object?>()))
              .toList()
          : const [],
      expectedPackage: (expected['package'] as String?)?.trim(),
      expectedFingerprint: (expected['sha256'] as String?)?.trim(),
      previewingRole: rawPreview is Map
          ? AssignableRole.fromJson(rawPreview.cast<String, Object?>())
          : null,
      assignableRoles: rawAssignable is List
          ? rawAssignable
              .whereType<Map<Object?, Object?>>()
              .map((r) => AssignableRole.fromJson(r.cast<String, Object?>()))
              .toList()
          : const [],
      divergence: rawDivergence is List
          ? rawDivergence
              .whereType<Map<Object?, Object?>>()
              .map((d) => DivergenceFinding.fromJson(d.cast<String, Object?>()))
              .toList()
          : const [],
      // Defaults to true: an older server that does not send the field has not
      // told us the record is missing, and assuming it is absent would put a
      // "ask HR to complete your profile" banner in front of everyone.
      hasEmployeeRecord: json['has_employee_record'] as bool? ?? true,
      hrModulesInstalled:
          modules is List ? modules.map((m) => '$m').toList() : const [],
    );
  }
}
