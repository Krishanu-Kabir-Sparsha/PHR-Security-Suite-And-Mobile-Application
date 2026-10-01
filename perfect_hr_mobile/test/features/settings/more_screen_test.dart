import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/capabilities/app_capabilities.dart';
import 'package:perfect_hr_mobile/core/capabilities/capabilities_repository.dart';
import 'package:perfect_hr_mobile/core/capabilities/capability_providers.dart';
import 'package:perfect_hr_mobile/core/capabilities/model_access.dart';
import 'package:perfect_hr_mobile/core/config/app_config.dart';
import 'package:perfect_hr_mobile/core/tenant/tenant_config.dart';
import 'package:perfect_hr_mobile/core/tenant/tenant_providers.dart';
import 'package:perfect_hr_mobile/core/data/data_providers.dart';
import 'package:perfect_hr_mobile/core/session/permissions.dart';
import 'package:perfect_hr_mobile/core/session/session_controller.dart';
import 'package:perfect_hr_mobile/core/session/session_state.dart';
import 'package:perfect_hr_mobile/core/session/user_role.dart';
import 'package:perfect_hr_mobile/core/theme/app_theme.dart';
import 'package:perfect_hr_mobile/features/authentication/application/auth_providers.dart';
import 'package:perfect_hr_mobile/features/authentication/data/auth_repository.dart';
import 'package:perfect_hr_mobile/features/authentication/data/secure_token_store.dart';
import 'package:perfect_hr_mobile/features/authentication/domain/auth_session.dart';
import 'package:perfect_hr_mobile/features/authentication/domain/sign_in_outcome.dart';
import 'package:perfect_hr_mobile/features/settings/presentation/more_screen.dart';

/// SET-01 More.
///
/// This screen carries the only sign-out in the app, so its tests are about
/// whether a session can actually be ended — not about layout. Until it existed
/// a signed-in user had no way out of a session at all, which on a shared or
/// lost phone is a security defect rather than a missing convenience.

class _StubAuthRepository implements AuthRepository {
  int signOutCount = 0;
  Object? signOutError;

  @override
  Future<SignInOutcome> signIn({
    required String login,
    required String password,
    String? deviceLabel,
    String? companyId,
    String? authMode,
    Map<String, Object?>? position,
  }) async {
    throw UnimplementedError();
  }

  @override
  Future<AuthSession> completeSignIn({
    required String mfaToken,
    required Map<String, dynamic> assertion,
    Map<String, Object?>? position,
  }) async {
    throw UnimplementedError();
  }

  @override
  Future<AuthSession> completeSignInWithDevice({
    required String mfaToken,
    required Map<String, dynamic> signaturePayload,
    Map<String, Object?>? position,
  }) async {
    throw UnimplementedError();
  }

  @override
  Future<AuthSession> switchCompany({
    required String accessToken,
    required String companyId,
  }) async {
    throw UnimplementedError();
  }

  @override
  Future<DevicePairing> pairDevice({
    required String login,
    required String code,
    required String publicKey,
    required String deviceLabel,
    required String platform,
  }) async {
    throw UnimplementedError();
  }

  @override
  Future<AuthSession> refresh(String refreshToken) async {
    throw UnimplementedError();
  }

  @override
  Future<void> signOut(String accessToken) async {
    signOutCount++;
    final error = signOutError;
    if (error != null) throw error;
  }
}

SessionUser _user({Employment? employment}) {
  return SessionUser(
    employeeId: '42',
    displayName: 'Krishanu Kabir',
    role: UserRole.superAdmin,
    tenantId: '1',
    tenantName: 'Perfect HR',
    jobTitle: 'Platform Administrator',
    permissions: PermissionSet.empty,
    employment: employment,
  );
}

ProviderContainer _container(
  _StubAuthRepository repository, {
  AppCapabilities? capabilities,
  bool admin = false,
  Employment? employment,
}) {
  final container = ProviderContainer(
    overrides: [
      authRepositoryProvider.overrideWithValue(repository),
      // Otherwise the Modules card reaches the network on every pump.
      capabilitiesRepositoryProvider.overrideWithValue(
        MockCapabilitiesRepository(
          capabilities: capabilities ??
              AppCapabilities(
                // One built (securityKeys), one the server offers but the app
                // has not caught up with (requests), and everything else
                // absent — so all three groups have something in them.
                features: const {AppFeature.securityKeys, AppFeature.requests},
                hasEmployeeRecord: true,
                // An ordinary employee by default. The server sends neither
                // the module list nor the flag to anyone else, so the stub
                // only carries them when `admin` is asked for.
                isWorkspaceAdmin: admin,
                hrModulesInstalled:
                    admin ? const ['hr', 'hr_attendance'] : const [],
              ),
        ),
      ),
      // A real store over mocked platform storage. The point of these tests is
      // that sign-out reaches the store and the server, so substituting the
      // store itself would leave exactly that untested.
      secureTokenStoreProvider.overrideWith(
        (ref) => SecureTokenStore(repository: repository),
      ),
    ],
  );
  container
      .read(sessionControllerProvider.notifier)
      .establish(_user(employment: employment));
  return container;
}

Future<void> _pump(WidgetTester tester, ProviderContainer container) async {
  tester.view.physicalSize = const Size(1200, 3000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);

  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: MaterialApp(theme: AppTheme.light(), home: const MoreScreen()),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    AppConfig.initialise();
    FlutterSecureStorage.setMockInitialValues({});
  });

  group('identity', () {
    testWidgets('shows the signed-in user, not a placeholder', (tester) async {
      final container = _container(_StubAuthRepository());
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Krishanu Kabir'), findsOneWidget);
      expect(find.text('Platform Administrator'), findsOneWidget);
      // Tenant and role together: on a multi-company Odoo the company a token
      // was issued against determines what every other screen shows.
      expect(find.textContaining('Perfect HR'), findsWidgets);
    });
  });

  group('sign out', () {
    testWidgets('is reachable from the screen', (tester) async {
      // Regression: there was no sign-out anywhere in the app, because it was
      // planned for this screen and this screen was a placeholder.
      final container = _container(_StubAuthRepository());
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Sign out'), findsOneWidget);
    });

    testWidgets('asks before ending the session', (tester) async {
      final repository = _StubAuthRepository();
      final container = _container(repository);
      addTearDown(container.dispose);
      await _pump(tester, container);

      await tester.tap(find.text('Sign out'));
      await tester.pumpAndSettle();

      expect(find.byType(AlertDialog), findsOneWidget);
      expect(find.text('Cancel'), findsOneWidget);

      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();

      // Cancelling must leave the session entirely alone, including the
      // server-side revocation.
      expect(repository.signOutCount, 0);
      expect(
        container.read(sessionControllerProvider),
        isA<SessionAuthenticated>(),
      );
    });

    testWidgets('confirming clears the session', (tester) async {
      final repository = _StubAuthRepository();
      final container = _container(repository);
      addTearDown(container.dispose);
      await _pump(tester, container);

      await tester.tap(find.text('Sign out'));
      await tester.pumpAndSettle();
      // Two matches now: the tile behind the dialog and the dialog's button.
      await tester.tap(find.widgetWithText(FilledButton, 'Sign out'));
      await tester.pumpAndSettle();

      expect(
        container.read(sessionControllerProvider),
        isA<SessionUnauthenticated>(),
        reason: 'the router redirects to Welcome off the back of this state',
      );
    });

    testWidgets('clears the session even if the server call fails',
        (tester) async {
      // The local clear is the part that protects a device being handed to
      // someone else. A server that is unreachable must not be able to keep a
      // user signed in on the phone.
      final repository = _StubAuthRepository()
        ..signOutError = Exception('network down');
      final container = _container(repository);
      addTearDown(container.dispose);
      await _pump(tester, container);

      await tester.tap(find.text('Sign out'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Sign out'));
      await tester.pumpAndSettle();

      expect(
        container.read(sessionControllerProvider),
        isA<SessionUnauthenticated>(),
      );
    });
  });

  group('security key enrolment', () {
    testWidgets('exposes a way into SET-02', (tester) async {
      // SET-02 has been implemented and working for some time, but its route is
      // /more/security — so while More was a placeholder the entire device
      // enrolment flow was unreachable from inside the app.
      final container = _container(_StubAuthRepository());
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Security & devices'), findsOneWidget);
    });
  });

  group('employment', () {
    testWidgets('shows position, standing and how long they have been here',
        (tester) async {
      // Who somebody IS, as distinct from what they may do. A role list reads
      // as jargon until it sits beside a job title and a department.
      final container = _container(
        _StubAuthRepository(),
        employment: const Employment(
          employeeCode: 'EMP-00421',
          jobPosition: 'Senior Officer',
          department: 'Finance',
          employeeType: 'Permanent',
          joinedOn: '2019-03-01',
          statusLabel: 'Active',
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('EMP-00421'), findsOneWidget);
      expect(find.text('Senior Officer'), findsOneWidget);
      expect(find.text('Permanent'), findsOneWidget);
      expect(find.text('Active'), findsOneWidget);
      // Formatted, not echoed back as an ISO string.
      expect(find.text('March 1, 2019'), findsOneWidget);
    });

    testWidgets('no joining date is a missing row, never a guess',
        (tester) async {
      // THE regression guard. This used to be filled from the date the
      // employee RECORD was created, so every employee of a company that
      // migrated into Perfect HR read as having joined on the migration date.
      // Tenure drives leave accrual, probation and gratuity.
      final container = _container(
        _StubAuthRepository(),
        employment: const Employment(
          employeeCode: 'EMP-00421',
          jobPosition: 'Senior Officer',
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Joined'), findsNothing);
    });

    testWidgets('a promotion shows up without signing out', (tester) async {
      // The session payload is a snapshot of one moment and sessions last
      // thirty days. Capabilities are re-read on every foreground refresh, so
      // the fresher copy has to win -- otherwise somebody promoted in January
      // goes on reading their old job title until they sign out.
      final container = _container(
        _StubAuthRepository(),
        employment: const Employment(jobPosition: 'Officer'),
        capabilities: const AppCapabilities(
          features: {AppFeature.securityKeys},
          hasEmployeeRecord: true,
          employment: Employment(jobPosition: 'Senior Officer'),
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Senior Officer'), findsOneWidget);
      expect(find.text('Officer'), findsNothing);
    });
  });

  group('about', () {
    testWidgets('names the workspace the app is talking to', (tester) async {
      final container = _container(_StubAuthRepository());
      addTearDown(container.dispose);
      container.read(tenantControllerProvider.notifier).adopt(
            const TenantConfig(
              baseUrl: 'https://acme.perfecthr.net',
              tenantId: 'acme.perfecthr.net',
              tenantName: 'Acme Ltd',
            ),
          );
      await _pump(tester, container);

      // The workspace NAME is what a person recognises and is shown to
      // everyone. The host is a deployment fact and now sits behind the
      // administrator gate, so an ordinary employee must not see it.
      expect(find.text('Acme Ltd'), findsWidgets);
      expect(find.text('acme.perfecthr.net'), findsNothing);
    });

    testWidgets('an administrator also gets the address', (tester) async {
      // The other side of the same gate. Withholding this from the person
      // rolling the app out would cost them the fastest way to confirm which
      // workspace a handset is actually pointed at.
      final container = _container(_StubAuthRepository(), admin: true);
      addTearDown(container.dispose);
      container.read(tenantControllerProvider.notifier).adopt(
            const TenantConfig(
              baseUrl: 'https://acme.perfecthr.net',
              tenantId: 'acme.perfecthr.net',
              tenantName: 'Acme Ltd',
            ),
          );
      await _pump(tester, container);

      expect(find.text('Technical details'), findsOneWidget);
      expect(find.text('acme.perfecthr.net'), findsOneWidget);
    });

    testWidgets('says plainly when the data is not live', (tester) async {
      // "Is what I am looking at real?" was unanswerable in the last build: a
      // dev role switch silently moved a real-looking session onto sample data.
      final container = _container(_StubAuthRepository());
      addTearDown(container.dispose);
      await _pump(tester, container);

      // Live is the unremarkable case and is no longer stated: a row that is
      // always there is one nobody reads, which is precisely what made the
      // sample-data warning easy to miss.
      expect(find.text('Sample data (development)'), findsNothing);

      container.read(dataSourceModeProvider.notifier).useMocks();
      await tester.pumpAndSettle();

      // Shown to EVERYONE, admin or not. A real session quietly sitting on
      // fabricated figures is the one thing on this screen that could lead
      // somebody to act on a number that is not real.
      expect(find.text('Sample data (development)'), findsOneWidget);
    });
  });

  group('modules', () {
    testWidgets('separates what is built from what the server merely has',
        (tester) async {
      // Three states, three different actions. "Attendance" being on the
      // server but not in the app is app work; a module that is not installed
      // is Odoo work, and no amount of app work will surface it.
      final container = _container(_StubAuthRepository());
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Ready to use'), findsOneWidget);
      expect(
        find.text('Your company has these, coming to the app soon'),
        findsOneWidget,
      );
      expect(find.text('Not part of your workspace'), findsOneWidget);

      // Reported by the server, but no screen for it yet.
      expect(find.text('Requests'), findsOneWidget);
      // Still listed, so nothing is silently omitted -- but named as the
      // feature, not as the Odoo module behind it. "needs ohrms_loan" sent an
      // employee looking in a backend they cannot open for something they
      // cannot install.
      expect(find.text('Loans'), findsOneWidget);
      expect(find.textContaining('ohrms_loan'), findsNothing);
    });

    testWidgets('an administrator sees which module is missing',
        (tester) async {
      // The gate again. For the person who can actually install it, the
      // module name is the single most useful thing on the row.
      final container = _container(_StubAuthRepository(), admin: true);
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.textContaining('needs ohrms_loan'), findsOneWidget);
    });

    testWidgets('lists the HR modules for an administrator only',
        (tester) async {
      // Withheld by the SERVER for everyone else, not merely hidden here --
      // a payload that reaches the handset is in logs, in crash reports and
      // in whatever a proxy kept. This asserts the app half of that contract.
      final ordinary = _container(_StubAuthRepository());
      addTearDown(ordinary.dispose);
      await _pump(tester, ordinary);
      expect(find.text('hr, hr_attendance'), findsNothing);

      final admin = _container(_StubAuthRepository(), admin: true);
      addTearDown(admin.dispose);
      await _pump(tester, admin);
      expect(find.text('hr, hr_attendance'), findsOneWidget);
    });

    testWidgets('warns when no employee record is linked', (tester) async {
      // Without that link every data endpoint answers 404 in turn. Saying it
      // once, with the remedy, beats failing repeatedly.
      final container = _container(
        _StubAuthRepository(),
        capabilities: const AppCapabilities(
          features: {AppFeature.securityKeys},
          hasEmployeeRecord: false,
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(
        find.textContaining('not linked to your employee file'),
        findsOneWidget,
      );
    });

    testWidgets('says so when the module list could not be read',
        (tester) async {
      // An older server without the endpoint, or a call that failed. An empty
      // card would read as "your server has nothing".
      final container = _container(
        _StubAuthRepository(),
        capabilities: AppCapabilities.unknown,
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(
        find.textContaining("couldn't check what your workspace includes"),
        findsOneWidget,
      );
    });
  });

  group('roles', () {
    testWidgets('names the duty, not just the role', (tester) async {
      // A role is the answer to most "why can't I do X?" questions, and the
      // create/approve split is the thing the SoD control exists to protect.
      final container = _container(
        _StubAuthRepository(),
        capabilities: const AppCapabilities(
          features: {AppFeature.securityKeys},
          hasEmployeeRecord: true,
          roles: [
            PlazaRole(
              code: 'HR_LINE_MANAGER',
              name: 'Line Manager',
              approvalTier: ApprovalTier.tier1,
              requiresWebauthn: true,
              duties: [
                RoleDuty(
                  transactionType: TransactionType.leaveRequest,
                  capability: RoleCapability.approve,
                ),
              ],
            ),
          ],
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Line Manager'), findsOneWidget);
      expect(find.text('HR_LINE_MANAGER'), findsOneWidget);
      expect(find.text('Approves · Leave requests'), findsOneWidget);
    });

    testWidgets('explains why a security key is demanded', (tester) async {
      // An unexplained demand to enrol a key is one people ignore.
      final container = _container(
        _StubAuthRepository(),
        capabilities: const AppCapabilities(
          features: {AppFeature.securityKeys},
          hasEmployeeRecord: true,
          roles: [
            PlazaRole(
              code: 'HR_MANAGER',
              name: 'HR Manager',
              approvalTier: ApprovalTier.tier2,
              requiresWebauthn: true,
            ),
          ],
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.textContaining('requires a registered security key'),
          findsOneWidget);
      expect(find.textContaining('Tier 2'), findsOneWidget);
    });
  });

  group('access review', () {
    testWidgets('puts excess access above a mere configuration gap',
        (tester) async {
      // "Granted but never written down" needs chasing. "Declared but not
      // granted" only means a feature will be missing. Merging them would bury
      // the first under the second.
      final container = _container(
        _StubAuthRepository(),
        capabilities: const AppCapabilities(
          features: {AppFeature.securityKeys},
          hasEmployeeRecord: true,
          divergence: [
            DivergenceFinding(
              model: 'hr.payslip',
              kind: 'undeclared',
              operations: ['read', 'write'],
            ),
          ],
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('ACCESS REVIEW'), findsOneWidget);
      expect(find.text('MORE ACCESS THAN DECLARED'), findsOneWidget);
      expect(find.textContaining('hr.payslip'), findsOneWidget);
    });

    testWidgets('renders nothing when there is nothing to review',
        (tester) async {
      // The server withholds findings from everyone outside compliance, so an
      // empty section header would be noise about a thing they cannot see.
      final container = _container(_StubAuthRepository());
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('ACCESS REVIEW'), findsNothing);
    });
  });

  group('role preview', () {
    testWidgets('is absent for someone who cannot administer roles',
        (tester) async {
      // The server sends an empty role list to everyone else; showing the
      // picker and refusing on tap would be worse than not showing it.
      final container = _container(_StubAuthRepository());
      addTearDown(container.dispose);
      await _pump(tester, container);

      // _SectionHeader uppercases its title, so the assertion is on the tile.
      expect(find.text('Preview a role'), findsNothing);
      expect(find.text('VIEW AS ROLE'), findsNothing);
    });

    testWidgets('is offered to a catalog administrator', (tester) async {
      final container = _container(
        _StubAuthRepository(),
        capabilities: const AppCapabilities(
          features: {AppFeature.securityKeys},
          hasEmployeeRecord: true,
          assignableRoles: [
            AssignableRole(code: 'HR_MANAGER', name: 'HR Manager'),
          ],
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('VIEW AS ROLE'), findsOneWidget);
      expect(find.text('Preview a role'), findsOneWidget);
    });

    testWidgets('says whose access is on screen while previewing',
        (tester) async {
      // A preview that looks like the real thing is worse than none: an
      // administrator could conclude their own access was wrong.
      final container = _container(
        _StubAuthRepository(),
        capabilities: const AppCapabilities(
          features: {AppFeature.securityKeys},
          hasEmployeeRecord: true,
          previewingRole:
              AssignableRole(code: 'HR_EMPLOYEE', name: 'Employee'),
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.textContaining('Previewing: Employee'), findsOneWidget);
    });
  });
}
