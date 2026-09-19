import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/capabilities/app_capabilities.dart';
import 'package:perfect_hr_mobile/core/capabilities/model_access.dart';

/// Role-based operation, as projected from the Security Suite.
///
/// Two sources feed this and they answer different questions:
///
///   permissions  Odoo's own `has_access` — may this user do it *at all*?
///   roles        the Plaza catalog — what *duty* does the role carry?
///
/// The second cannot be derived from the first. Odoo's ACL cannot tell an
/// approval apart from any other write, and that distinction is the whole point
/// of the catalog: a Line Manager writing to hr.leave is approving somebody's
/// request; an employee writing to it is editing their own.

void main() {
  group('model permissions', () {
    test('reads CRUD exactly as the server reported it', () {
      final capabilities = AppCapabilities.fromJson({
        'features': ['leave'],
        'permissions': {
          'hr.leave': {
            'read': true,
            'create': true,
            'write': true,
            'unlink': false,
          },
        },
      });

      expect(capabilities.can(OdooModels.leave, ModelOperation.create), isTrue);
      expect(capabilities.can(OdooModels.leave, ModelOperation.unlink), isFalse);
    });

    test('an unreported model is refused, not an error', () {
      // A newer app asking an older server about a model it has never heard of
      // must hide the control rather than crash.
      final capabilities = AppCapabilities.fromJson({'features': <dynamic>[]});

      expect(capabilities.accessTo('hr.payslip'), ModelAccess.none);
      expect(
        capabilities.can('hr.payslip', ModelOperation.read),
        isFalse,
      );
    });

    test('the unknown fallback permits nothing', () {
      // Used before the call returns and when it fails. Defaulting to "allowed"
      // would draw buttons that 403.
      for (final operation in ModelOperation.values) {
        expect(
          AppCapabilities.unknown.can(OdooModels.attendance, operation),
          isFalse,
        );
      }
    });
  });

  group('plaza roles', () {
    AppCapabilities withRoles(List<Map<String, Object?>> roles) {
      return AppCapabilities.fromJson({
        'features': <dynamic>[],
        'roles': roles,
      });
    }

    test('reads the duty split the catalog declares', () {
      final capabilities = withRoles([
        {
          'code': 'HR_LINE_MANAGER',
          'name': 'Line Manager',
          'approval_tier': 'tier_1',
          'requires_webauthn': true,
          'capabilities': [
            {'transaction_type': 'leave_request', 'capability': 'approve'},
          ],
        },
      ]);

      expect(capabilities.approves(TransactionType.leaveRequest), isTrue);
      expect(capabilities.approves(TransactionType.payrollRun), isFalse);
      expect(capabilities.highestTier, ApprovalTier.tier1);
      expect(capabilities.requiresWebauthn, isTrue);
    });

    test('a create capability is not an approval capability', () {
      // The Payroll Officer prepares payroll and must never be shown the
      // control that confirms it — that separation is the single highest-value
      // one in the HR catalog, because a payroll run moves money to people.
      final capabilities = withRoles([
        {
          'code': 'PAYROLL_OFFICER',
          'name': 'Payroll Officer',
          'approval_tier': 'none',
          'capabilities': [
            {'transaction_type': 'payroll_run', 'capability': 'create'},
          ],
        },
      ]);

      expect(capabilities.approves(TransactionType.payrollRun), isFalse);
      expect(capabilities.highestTier, ApprovalTier.none);
      expect(capabilities.requiresWebauthn, isFalse);
    });

    test('takes the highest tier across several roles', () {
      final capabilities = withRoles([
        {'code': 'A', 'name': 'A', 'approval_tier': 'tier_1'},
        {'code': 'B', 'name': 'B', 'approval_tier': 'tier_2'},
      ]);

      expect(capabilities.highestTier, ApprovalTier.tier2);
    });

    test('keeps a create_approve role visible rather than dropping it', () {
      // The role model rejects this combination on save, so it should never
      // arrive. Silently discarding it would hide exactly the condition the
      // segregation-of-duties control exists to surface.
      final capabilities = withRoles([
        {
          'code': 'BROKEN',
          'name': 'Broken',
          'capabilities': [
            {
              'transaction_type': 'payroll_run',
              'capability': 'create_approve',
            },
          ],
        },
      ]);

      expect(capabilities.approves(TransactionType.payrollRun), isTrue);
    });

    test('survives a role payload with fields missing', () {
      final capabilities = withRoles([
        {'code': 'X', 'name': 'X'},
      ]);

      expect(capabilities.roles.single.approvalTier, ApprovalTier.none);
      expect(capabilities.roles.single.duties, isEmpty);
    });
  });

  group('divergence', () {
    test('separates excess access from a mere configuration gap', () {
      // "Granted but never written down" is a finding someone must act on.
      // "Declared but not granted" only means a feature will be missing.
      final capabilities = AppCapabilities.fromJson({
        'features': <dynamic>[],
        'divergence': [
          {
            'model': 'hr.payslip',
            'kind': 'undeclared',
            'operations': ['read', 'write'],
          },
          {
            'model': 'hr.leave',
            'kind': 'not_granted',
            'operations': ['create'],
          },
        ],
      });

      final excess =
          capabilities.divergence.where((d) => d.isExcessAccess).toList();
      expect(excess, hasLength(1));
      expect(excess.single.model, 'hr.payslip');
      expect(excess.single.summary, contains('not in the catalog'));
    });

    test('is empty for a user who cannot act on it', () {
      // The server withholds it from everyone outside compliance, so the app
      // must render nothing rather than an empty section header.
      final capabilities = AppCapabilities.fromJson({'features': <dynamic>[]});
      expect(capabilities.divergence, isEmpty);
    });
  });
}
