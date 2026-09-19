import 'package:flutter/foundation.dart';

/// What the signed-in user may do to one Odoo model.
///
/// Supplied by the server from Odoo's own `has_access` check — the same call
/// that decides whether the operation succeeds. It is therefore the only
/// honest basis for enabling a button: anything derived instead from the Plaza
/// access matrix would be *declared* access, and the matrix is declarative —
/// nothing writes it into `ir.model.access`. A button drawn from declared
/// intent is a button that 403s, and a user cannot tell that apart from the app
/// being broken.
///
/// **This is not a security boundary.** Hiding a control protects nothing; the
/// server authorises every call again. It exists so the app does not offer what
/// it cannot deliver.
///
/// Model-level only. Record rules decide *which* records afterwards, and are
/// enforced on every real call — so "can create leave" here never means "can
/// create leave for anyone".
@immutable
class ModelAccess {
  const ModelAccess({
    this.read = false,
    this.create = false,
    this.write = false,
    this.unlink = false,
  });

  final bool read;
  final bool create;
  final bool write;
  final bool unlink;

  /// Nothing permitted. Also what an unknown model resolves to, so a caller
  /// asking about a model the server did not report gets a refusal rather than
  /// an exception.
  static const ModelAccess none = ModelAccess();

  bool allows(ModelOperation operation) => switch (operation) {
        ModelOperation.read => read,
        ModelOperation.create => create,
        ModelOperation.write => write,
        ModelOperation.unlink => unlink,
      };

  factory ModelAccess.fromJson(Map<String, Object?> json) {
    return ModelAccess(
      read: json['read'] as bool? ?? false,
      create: json['create'] as bool? ?? false,
      write: json['write'] as bool? ?? false,
      unlink: json['unlink'] as bool? ?? false,
    );
  }

  Map<String, Object?> toJson() => {
        'read': read,
        'create': create,
        'write': write,
        'unlink': unlink,
      };
}

enum ModelOperation { read, create, write, unlink }

/// Odoo model names the app gates on.
///
/// Constants rather than literals at call sites: a typo in a model name would
/// resolve to [ModelAccess.none] and silently disable a feature, with nothing
/// to notice it by.
abstract final class OdooModels {
  static const String attendance = 'hr.attendance';
  static const String leave = 'hr.leave';
  static const String leaveAllocation = 'hr.leave.allocation';
  static const String employee = 'hr.employee';
  static const String contract = 'hr.contract';
  static const String payslip = 'hr.payslip';
  static const String applicant = 'hr.applicant';
  static const String expense = 'hr.expense';
  static const String loan = 'hr.loan';
  static const String salaryAdvance = 'salary.advance';
  static const String resignation = 'hr.resignation';
  static const String appraisal = 'hr.appraisal';
  static const String announcement = 'hr.announcement';
  static const String document = 'hr.dms.document';
  static const String assetAllocation = 'eam.asset.allocation';
}

/// Which class of business transaction a role may originate or approve.
///
/// Mirrors `TRANSACTION_TYPES` in `sec_plaza_rbac/models/plaza_role.py`.
enum TransactionType {
  saleOrder('sale_order'),
  purchaseOrder('purchase_order'),
  customerInvoice('customer_invoice'),
  vendorBill('vendor_bill'),
  vendorPayment('vendor_payment'),
  journalEntry('journal_entry'),
  stockMove('stock_move'),
  masterData('master_data'),
  leaveRequest('leave_request'),
  attendanceRecord('attendance_record'),
  payrollRun('payroll_run'),
  employeeMaster('employee_master'),
  recruitment('recruitment');

  const TransactionType(this.wireValue);

  final String wireValue;

  static TransactionType? fromWire(String? value) {
    for (final type in TransactionType.values) {
      if (type.wireValue == value) return type;
    }
    return null;
  }
}

/// Whether a role originates a transaction or signs it off.
///
/// `createApprove` on one role is a segregation-of-duties violation by
/// definition and is rejected when the role is saved, so it should never arrive
/// here. It is modelled anyway: silently dropping a value the server sent would
/// hide exactly the condition the control exists to surface.
enum RoleCapability {
  none('none'),
  create('create'),
  approve('approve'),
  createApprove('create_approve');

  const RoleCapability(this.wireValue);

  final String wireValue;

  static RoleCapability fromWire(String? value) => RoleCapability.values
      .firstWhere((c) => c.wireValue == value, orElse: () => RoleCapability.none);
}

/// One duty a role carries: a transaction class and what it may do with it.
@immutable
class RoleDuty {
  const RoleDuty({required this.transactionType, required this.capability});

  final TransactionType? transactionType;
  final RoleCapability capability;

  factory RoleDuty.fromJson(Map<String, Object?> json) {
    return RoleDuty(
      transactionType: TransactionType.fromWire(
        json['transaction_type'] as String?,
      ),
      capability: RoleCapability.fromWire(json['capability'] as String?),
    );
  }
}

/// Where a role sits in the multi-party override workflow.
enum ApprovalTier {
  none('none', 'Not an approver'),
  tier1('tier_1', 'Tier 1 — Department Head'),
  tier2('tier_2', 'Tier 2 — Compliance / Legal Lead'),
  tier3('tier_3', 'Tier 3 — CEO / Owner');

  const ApprovalTier(this.wireValue, this.label);

  final String wireValue;
  final String label;

  static ApprovalTier fromWire(String? value) => ApprovalTier.values
      .firstWhere((t) => t.wireValue == value, orElse: () => ApprovalTier.none);

  bool get isApprover => this != ApprovalTier.none;
}

/// A Plaza Model role the user holds.
///
/// Carries what Odoo's ACLs cannot express: the approval tier, whether the role
/// obliges its holder to enrol a security key, and the create/approve split
/// that the segregation-of-duties checker is built on.
@immutable
class PlazaRole {
  const PlazaRole({
    required this.code,
    required this.name,
    this.approvalTier = ApprovalTier.none,
    this.requiresWebauthn = false,
    this.duties = const [],
  });

  final String code;
  final String name;
  final ApprovalTier approvalTier;
  final bool requiresWebauthn;
  final List<RoleDuty> duties;

  bool canApprove(TransactionType type) => duties.any(
        (d) =>
            d.transactionType == type &&
            (d.capability == RoleCapability.approve ||
                d.capability == RoleCapability.createApprove),
      );

  factory PlazaRole.fromJson(Map<String, Object?> json) {
    final duties = json['capabilities'];
    return PlazaRole(
      code: '${json['code'] ?? ''}',
      name: '${json['name'] ?? ''}',
      approvalTier: ApprovalTier.fromWire(json['approval_tier'] as String?),
      requiresWebauthn: json['requires_webauthn'] as bool? ?? false,
      duties: duties is List
          ? duties
              .whereType<Map<Object?, Object?>>()
              .map((d) => RoleDuty.fromJson(d.cast<String, Object?>()))
              .toList()
          : const [],
    );
  }
}

/// A place where the Plaza catalog and Odoo's real permissions disagree.
///
/// Nothing detects this today. The catalog is declarative, so a role can
/// declare access the backing group does not carry, and — the direction that
/// matters — a user can hold access the catalog never granted. The monthly
/// review reads the declaration, so it would sign off on a matrix that does not
/// describe the system.
///
/// Only sent to users who can act on it; everyone else receives an empty list.
@immutable
class DivergenceFinding {
  const DivergenceFinding({
    required this.model,
    required this.kind,
    this.operations = const [],
  });

  final String model;

  /// `undeclared`, `over_granted` or `not_granted`.
  final String kind;

  final List<String> operations;

  /// Whether this finding means somebody can do more than was written down.
  bool get isExcessAccess => kind == 'undeclared' || kind == 'over_granted';

  String get summary => switch (kind) {
        'undeclared' =>
          'Granted but not in the catalog: ${operations.join(', ')}',
        'over_granted' =>
          'More than the catalog declares: ${operations.join(', ')}',
        'not_granted' =>
          'Declared but not granted: ${operations.join(', ')}',
        _ => operations.join(', '),
      };

  factory DivergenceFinding.fromJson(Map<String, Object?> json) {
    final operations = json['operations'];
    return DivergenceFinding(
      model: '${json['model'] ?? ''}',
      kind: '${json['kind'] ?? ''}',
      operations: operations is List
          ? operations.map((o) => '$o').toList()
          : const [],
    );
  }
}

/// A role an administrator may preview, from the Plaza catalog.
@immutable
class AssignableRole {
  const AssignableRole({
    required this.code,
    required this.name,
    this.approvalTier = ApprovalTier.none,
  });

  final String code;
  final String name;
  final ApprovalTier approvalTier;

  factory AssignableRole.fromJson(Map<String, Object?> json) {
    return AssignableRole(
      code: '${json['code'] ?? ''}',
      name: '${json['name'] ?? ''}',
      approvalTier: ApprovalTier.fromWire(json['approval_tier'] as String?),
    );
  }
}
