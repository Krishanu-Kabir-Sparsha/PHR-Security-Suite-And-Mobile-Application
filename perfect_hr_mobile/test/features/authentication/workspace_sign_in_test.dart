import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/config/app_config.dart';
import 'package:perfect_hr_mobile/core/errors/app_failure.dart';
import 'package:perfect_hr_mobile/core/security/device_key_service.dart';
import 'package:perfect_hr_mobile/core/session/permissions.dart';
import 'package:perfect_hr_mobile/core/session/session_controller.dart';
import 'package:perfect_hr_mobile/core/session/session_state.dart';
import 'package:perfect_hr_mobile/core/session/user_role.dart';
import 'package:perfect_hr_mobile/core/tenant/tenant_config.dart';
import 'package:perfect_hr_mobile/core/tenant/tenant_providers.dart';
import 'package:perfect_hr_mobile/core/tenant/tenant_repository.dart';
import 'package:perfect_hr_mobile/features/authentication/application/auth_providers.dart';
import 'package:perfect_hr_mobile/features/authentication/data/auth_repository.dart';
import 'package:perfect_hr_mobile/features/authentication/data/secure_token_store.dart';
import 'package:perfect_hr_mobile/features/authentication/domain/auth_session.dart';
import 'package:perfect_hr_mobile/features/authentication/domain/sign_in_outcome.dart';
import 'package:perfect_hr_mobile/features/authentication/presentation/login_screen.dart';

/// Workspace, company, method — the three questions that come before the
/// password.
///
/// The rule underneath all of them: **a step with one possible answer is not a
/// question.** A screen that asks something with a single answer teaches people
/// to stop reading it, and then they miss the one that mattered.

// --------------------------------------------------------------------------
// Address parsing
// --------------------------------------------------------------------------

void _addressTests() {
  group('workspace addresses', () {
    test('a bare company name becomes a workspace subdomain', () {
      // What somebody reads off an induction email. Refusing it would make the
      // very first screen of the app the hardest one.
      expect(normaliseWorkspaceUrl('acme'), 'https://acme.perfecthr.net');
      expect(normaliseWorkspaceUrl('  ACME '), 'https://acme.perfecthr.net');
    });

    test('a full address is kept, case-folded', () {
      expect(
        normaliseWorkspaceUrl('ACME.PerfectHR.net'),
        'https://acme.perfecthr.net',
      );
    });

    test('a pasted page URL is reduced to its origin', () {
      // People paste whatever page they were on, which is usually /web/login.
      for (final typed in [
        'https://acme.perfecthr.net/',
        'https://acme.perfecthr.net/web/login',
        'acme.perfecthr.net/odoo?db=acme',
        'https://acme.perfecthr.net/web#menu_id=1',
      ]) {
        expect(normaliseWorkspaceUrl(typed), 'https://acme.perfecthr.net',
            reason: 'failed for $typed');
      }
    });

    test('an explicit port survives', () {
      expect(
        normaliseWorkspaceUrl('https://acme.perfecthr.net:8069'),
        'https://acme.perfecthr.net:8069',
      );
    });

    test('http is refused for a real host', () {
      // Honouring it quietly would put the password on the wire in clear, and
      // the person typing it would have no way to know.
      expect(
        () => normaliseWorkspaceUrl('http://acme.perfecthr.net'),
        throwsA(isA<WorkspaceAddressError>()),
      );
    });

    test('loopback is allowed over http, for a developer', () {
      expect(normaliseWorkspaceUrl('localhost:8069'), 'http://localhost:8069');
      expect(normaliseWorkspaceUrl('127.0.0.1'), 'http://127.0.0.1');
    });

    test('credentials in the authority are refused', () {
      // `evil.test@acme.perfecthr.net` reads as Acme and resolves to evil.test.
      expect(
        () => normaliseWorkspaceUrl('https://evil.test@acme.perfecthr.net'),
        throwsA(isA<WorkspaceAddressError>()),
      );
    });

    test('empty and nonsense are refused rather than guessed at', () {
      for (final typed in ['', '   ', 'https://', '..', '-acme-']) {
        expect(
          () => normaliseWorkspaceUrl(typed),
          throwsA(isA<WorkspaceAddressError>()),
          reason: 'accepted $typed',
        );
      }
    });
  });
}

// --------------------------------------------------------------------------
// Stubs
// --------------------------------------------------------------------------

const _tenant = TenantConfig(
  baseUrl: 'https://acme.perfecthr.net',
  tenantId: 'acme.perfecthr.net',
  tenantName: 'Acme Ltd',
);

AuthSession _session({String authMode = 'advance'}) => AuthSession(
      accessToken: 'access',
      refreshToken: 'refresh',
      expiresAt: DateTime.now().add(const Duration(hours: 1)),
      authMode: authMode,
      user: const SessionUser(
        employeeId: '1',
        displayName: 'Test Person',
        role: UserRole.employee,
        tenantId: 'acme.perfecthr.net',
        tenantName: 'Acme Ltd',
        companyId: '7',
        companyName: 'Acme Operations',
        permissions: PermissionSet.empty,
      ),
    );

class _StubTenants implements TenantRepository {
  _StubTenants({
    this.config = _tenant,
    this.list = const <TenantCompany>[],
    this.resolveError,
  });

  final TenantConfig config;
  final List<TenantCompany> list;
  final Object? resolveError;

  String? resolvedFor;

  @override
  Future<TenantConfig> resolve(String baseUrl) async {
    resolvedFor = baseUrl;
    final thrown = resolveError;
    if (thrown != null) throw thrown;
    return config;
  }

  @override
  Future<List<TenantCompany>> companies(String baseUrl) async => list;
}

class _StubAuth implements AuthRepository {
  _StubAuth({this.outcome});

  final SignInOutcome? outcome;

  String? sentLogin;
  String? sentCompanyId;
  String? sentAuthMode;

  @override
  Future<SignInOutcome> signIn({
    required String login,
    required String password,
    String? deviceLabel,
    String? companyId,
    String? authMode,
  }) async {
    sentLogin = login;
    sentCompanyId = companyId;
    sentAuthMode = authMode;
    return outcome ?? SignInComplete(_session(authMode: authMode ?? 'advance'));
  }

  @override
  Future<AuthSession> completeSignIn({
    required String mfaToken,
    required Map<String, dynamic> assertion,
  }) async =>
      _session();

  @override
  Future<AuthSession> completeSignInWithDevice({
    required String mfaToken,
    required Map<String, dynamic> signaturePayload,
  }) async =>
      _session();

  @override
  Future<AuthSession> switchCompany({
    required String accessToken,
    required String companyId,
  }) async =>
      _session();

  @override
  Future<DevicePairing> pairDevice({
    required String login,
    required String code,
    required String publicKey,
    required String deviceLabel,
    required String platform,
  }) async =>
      throw UnimplementedError();

  @override
  Future<AuthSession> refresh(String refreshToken) async => _session();

  @override
  Future<void> signOut(String accessToken) async {}
}

class _StubDeviceKeys implements DeviceKeyService {
  @override
  Future<bool> get isSupported async => true;
  @override
  Future<DeviceBinding?> get binding async => null;
  @override
  Future<String> generateKeyPair() async => 'public';
  @override
  Future<void> rememberPairing({
    required String publicKey,
    required String handle,
    required String login,
    required String label,
  }) async {}
  @override
  Future<DeviceSignature> sign({
    required String challenge,
    required String contextRef,
    required String reason,
  }) async =>
      const DeviceSignature(
        deviceHandle: 'h',
        challenge: 'c',
        counter: 1,
        signature: 's',
      );
  @override
  Future<void> forget() async {}
}

ProviderContainer _container({
  required _StubAuth auth,
  required _StubTenants tenants,
  TenantConfig? workspace,
}) {
  final container = ProviderContainer(
    overrides: [
      authRepositoryProvider.overrideWithValue(auth),
      tenantRepositoryProvider.overrideWithValue(tenants),
      deviceKeyServiceProvider.overrideWithValue(_StubDeviceKeys()),
      secureTokenStoreProvider.overrideWith(
        (ref) => SecureTokenStore(repository: auth),
      ),
    ],
  );
  if (workspace != null) {
    container.read(tenantControllerProvider.notifier).adopt(workspace);
  }
  return container;
}

/// Scroll the submit button into view, then tap it.
///
/// The sign-in screen scrolls, and with the method picker shown its button
/// sits below an 800x600 test viewport — which is a smaller window than any
/// real handset, but the scroll is what a person would do either way.
Future<void> _tapSubmit(WidgetTester tester, String label) async {
  final button = find.widgetWithText(FilledButton, label);
  await tester.ensureVisible(button);
  await tester.pumpAndSettle();
  await tester.tap(button);
  await tester.pumpAndSettle();
}

Future<void> _pump(WidgetTester tester, ProviderContainer container) async {
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: LoginScreen()),
    ),
  );
  await tester.pumpAndSettle();
}

// --------------------------------------------------------------------------

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    AppConfig.initialise();
    FlutterSecureStorage.setMockInitialValues({});
  });

  _addressTests();

  group('the workspace step', () {
    testWidgets('is shown first when nothing is remembered', (tester) async {
      final container = _container(
        auth: _StubAuth(),
        tenants: _StubTenants(),
        // Cleared, so the dev seed does not stand in for a remembered one.
        workspace: null,
      );
      await container.read(tenantControllerProvider.notifier).forget();
      addTearDown(container.dispose);

      // The dev flavour seeds a workspace, so force the unset state the way a
      // production build starts.
      container.read(tenantControllerProvider.notifier).state = null;
      await _pump(tester, container);

      expect(find.text('Perfect HR address'), findsOneWidget);
      expect(find.text('Password'), findsNothing);
    });

    testWidgets('a password field never appears before the address resolves',
        (tester) async {
      // The whole reason this step exists. A password typed into an app
      // pointed at nothing would be posted to whatever answered.
      final container = _container(auth: _StubAuth(), tenants: _StubTenants());
      addTearDown(container.dispose);
      container.read(tenantControllerProvider.notifier).state = null;
      await _pump(tester, container);

      expect(find.text('Password'), findsNothing);
    });

    testWidgets('an unreachable address is reported, not accepted',
        (tester) async {
      final container = _container(
        auth: _StubAuth(),
        tenants: _StubTenants(
          resolveError: const ServerFailure(
            userMessage: 'That address is not a Perfect HR workspace.',
          ),
        ),
      );
      addTearDown(container.dispose);
      container.read(tenantControllerProvider.notifier).state = null;
      await _pump(tester, container);

      await tester.enterText(find.byType(TextField).first, 'nope.example');
      await tester.tap(find.text('Continue'));
      await tester.pumpAndSettle();

      expect(
        find.text('That address is not a Perfect HR workspace.'),
        findsOneWidget,
      );
      expect(find.text('Password'), findsNothing);
    });

    testWidgets('a remembered workspace skips straight to credentials',
        (tester) async {
      final container = _container(
        auth: _StubAuth(),
        tenants: _StubTenants(),
        workspace: _tenant,
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Password'), findsOneWidget);
      expect(find.text('Acme Ltd'), findsOneWidget);
    });
  });

  group('the company step', () {
    testWidgets('is skipped when the workspace publishes nothing',
        (tester) async {
      // Most tenants. An empty list means "do not ask", and the server places
      // each user in their own company.
      final container = _container(
        auth: _StubAuth(),
        tenants: _StubTenants(),
        workspace: _tenant,
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Password'), findsOneWidget);
    });

    testWidgets('is shown when there is a genuine choice', (tester) async {
      final container = _container(
        auth: _StubAuth(),
        tenants: _StubTenants(
          list: const [
            TenantCompany(id: '1', name: 'Acme Operations'),
            TenantCompany(id: '2', name: 'Acme Logistics'),
          ],
        ),
        workspace: const TenantConfig(
          baseUrl: 'https://acme.perfecthr.net',
          tenantId: 'acme.perfecthr.net',
          tenantName: 'Acme Ltd',
          companyStepRequired: true,
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Acme Operations'), findsOneWidget);
      expect(find.text('Acme Logistics'), findsOneWidget);
      expect(find.text('Password'), findsNothing);
    });

    testWidgets('the chosen company is sent with the credentials',
        (tester) async {
      final auth = _StubAuth();
      final container = _container(
        auth: auth,
        tenants: _StubTenants(
          list: const [
            TenantCompany(id: '1', name: 'Acme Operations'),
            TenantCompany(id: '2', name: 'Acme Logistics'),
          ],
        ),
        workspace: const TenantConfig(
          baseUrl: 'https://acme.perfecthr.net',
          tenantId: 'acme.perfecthr.net',
          tenantName: 'Acme Ltd',
          companyStepRequired: true,
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      await tester.tap(find.text('Acme Logistics'));
      await tester.pumpAndSettle();

      await tester.enterText(
          find.widgetWithText(TextFormField, 'Work email or Employee ID'), 'me');
      await tester.enterText(
          find.widgetWithText(TextFormField, 'Password'), 'secret');
      await _tapSubmit(tester, 'Continue');

      expect(auth.sentCompanyId, '2');
    });
  });

  group('the method step', () {
    testWidgets('is absent when the company permits only one method',
        (tester) async {
      // A toggle with one option is not a choice, and drawing it would invite
      // somebody to look for a difference that is not there.
      final container = _container(
        auth: _StubAuth(),
        tenants: _StubTenants(
          list: const [
            TenantCompany(id: '1', name: 'Acme Operations'),
            TenantCompany(id: '2', name: 'Acme Logistics'),
          ],
        ),
        workspace: const TenantConfig(
          baseUrl: 'https://acme.perfecthr.net',
          tenantId: 'acme.perfecthr.net',
          tenantName: 'Acme Ltd',
          companyStepRequired: true,
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      await tester.tap(find.text('Acme Operations'));
      await tester.pumpAndSettle();

      expect(find.text('How would you like to sign in?'), findsNothing);
    });

    testWidgets('offers both where the company allows both', (tester) async {
      final container = _container(
        auth: _StubAuth(),
        tenants: _StubTenants(
          list: const [
            TenantCompany(
              id: '1',
              name: 'Acme Operations',
              authModes: ['advance', 'basic'],
            ),
            TenantCompany(id: '2', name: 'Acme Logistics'),
          ],
        ),
        workspace: const TenantConfig(
          baseUrl: 'https://acme.perfecthr.net',
          tenantId: 'acme.perfecthr.net',
          tenantName: 'Acme Ltd',
          companyStepRequired: true,
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      await tester.tap(find.text('Acme Operations'));
      await tester.pumpAndSettle();

      expect(find.text('How would you like to sign in?'), findsOneWidget);
      expect(find.text('Advanced'), findsOneWidget);
      expect(find.text('Basic'), findsOneWidget);
    });

    testWidgets('choosing basic says what it costs', (tester) async {
      // Somebody picking the weaker option is entitled to know what they are
      // giving up, in a sentence, at the moment they pick it.
      final container = _container(
        auth: _StubAuth(),
        tenants: _StubTenants(
          list: const [
            TenantCompany(
              id: '1',
              name: 'Acme Operations',
              authModes: ['advance', 'basic'],
            ),
            TenantCompany(id: '2', name: 'Acme Logistics'),
          ],
        ),
        workspace: const TenantConfig(
          baseUrl: 'https://acme.perfecthr.net',
          tenantId: 'acme.perfecthr.net',
          tenantName: 'Acme Ltd',
          companyStepRequired: true,
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      await tester.tap(find.text('Acme Operations'));
      await tester.pumpAndSettle();

      expect(
        find.textContaining('a stolen password is enough to sign in'),
        findsOneWidget,
      );
    });

    testWidgets('the chosen method is sent with the credentials',
        (tester) async {
      final auth = _StubAuth();
      final container = _container(
        auth: auth,
        tenants: _StubTenants(
          list: const [
            TenantCompany(
              id: '1',
              name: 'Acme Operations',
              authModes: ['advance', 'basic'],
            ),
            TenantCompany(id: '2', name: 'Acme Logistics'),
          ],
        ),
        workspace: const TenantConfig(
          baseUrl: 'https://acme.perfecthr.net',
          tenantId: 'acme.perfecthr.net',
          tenantName: 'Acme Ltd',
          companyStepRequired: true,
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      await tester.tap(find.text('Acme Operations'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Basic'));
      await tester.pumpAndSettle();

      await tester.enterText(
          find.widgetWithText(TextFormField, 'Work email or Employee ID'), 'me');
      await tester.enterText(
          find.widgetWithText(TextFormField, 'Password'), 'secret');
      await _tapSubmit(tester, 'Sign in');

      expect(auth.sentAuthMode, 'basic');
      expect(auth.sentCompanyId, '1');
    });
  });

  group('credentials', () {
    testWidgets('an Employee ID is accepted, not only an email',
        (tester) async {
      // Resolved server-side, so the app must not validate for an @ — a badge
      // number would be refused before it ever left the handset.
      final auth = _StubAuth();
      final container = _container(
        auth: auth,
        tenants: _StubTenants(),
        workspace: _tenant,
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      await tester.enterText(
          find.widgetWithText(TextFormField, 'Work email or Employee ID'),
          'EMP-00421');
      await tester.enterText(
          find.widgetWithText(TextFormField, 'Password'), 'secret');
      await _tapSubmit(tester, 'Continue');

      expect(auth.sentLogin, 'EMP-00421');
    });

    testWidgets('the field names the badge as an option', (tester) async {
      final container = _container(
        auth: _StubAuth(),
        tenants: _StubTenants(),
        workspace: _tenant,
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('The number on your ID badge works here.'),
          findsOneWidget);
    });
  });

  group('the session that results', () {
    test('records which proof produced it', () async {
      final auth = _StubAuth();
      final container = _container(auth: auth, tenants: _StubTenants());
      addTearDown(container.dispose);

      await container.read(signInControllerProvider.notifier).signIn(
            login: 'me',
            password: 'secret',
            authMode: 'basic',
          );

      final session = container.read(sessionControllerProvider);
      expect(session, isA<SessionAuthenticated>());
      expect((session as SessionAuthenticated).authMode, 'basic');
      expect(session.isBasicSession, isTrue);
    });

    test('carries the company, separately from the tenant', () async {
      // These were one field until the company step existed, which left a
      // two-company customer unable to say which employment they meant.
      final container = _container(auth: _StubAuth(), tenants: _StubTenants());
      addTearDown(container.dispose);

      await container
          .read(signInControllerProvider.notifier)
          .signIn(login: 'me', password: 'secret');

      final session =
          container.read(sessionControllerProvider) as SessionAuthenticated;
      expect(session.user.tenantId, 'acme.perfecthr.net');
      expect(session.user.companyId, '7');
      expect(session.user.companyName, 'Acme Operations');
    });

    test('the company is part of the navigation signature', () {
      // Otherwise switching company rebuilds nothing and appears to do nothing.
      const a = SessionUser(
        employeeId: '1',
        displayName: 'X',
        role: UserRole.employee,
        tenantId: 't',
        tenantName: 'T',
        companyId: '1',
        companyName: 'One',
      );
      const b = SessionUser(
        employeeId: '1',
        displayName: 'X',
        role: UserRole.employee,
        tenantId: 't',
        tenantName: 'T',
        companyId: '2',
        companyName: 'Two',
      );
      expect(
        const SessionAuthenticated(user: a).navigationSignature,
        isNot(const SessionAuthenticated(user: b).navigationSignature),
      );
    });
  });

  group('attendance at sign-in', () {
    test('a recorded check-in is surfaced', () async {
      final container = _container(auth: _StubAuth(), tenants: _StubTenants());
      addTearDown(container.dispose);

      final attendance = SignInAttendance.fromJson({
        'status': 'recorded',
        'check_in_at': '2026-09-24 09:02:00',
      });
      expect(attendance, isNotNull);
      expect(attendance!.wasRecorded, isTrue);
      expect(attendance.describe, 'You were checked in automatically.');
    });

    test('an approved absence explains itself rather than going quiet', () {
      // Somebody who expected to be checked in and was not needs to know why.
      final attendance = SignInAttendance.fromJson({'status': 'on_leave'});
      expect(attendance!.wasRecorded, isFalse);
      expect(attendance.isWorthExplaining, isTrue);
      expect(attendance.describe, contains('approved leave'));
    });

    test('a company that switched it off says nothing at all', () {
      // Not a failure and not worth a line on the home screen.
      final attendance = SignInAttendance.fromJson({'status': 'disabled'});
      expect(attendance!.isWorthExplaining, isFalse);
      expect(attendance.describe, isEmpty);
    });

    test('is not persisted with the session', () {
      // It describes one moment this morning. Restoring it tomorrow would tell
      // somebody they had just been checked in when they had not.
      final session = _session().copyWith(
        attendance: const SignInAttendance(status: 'recorded'),
      );
      expect(session.attendance, isNotNull);
      expect(session.toJson().containsKey('attendance'), isFalse);
      expect(AuthSession.fromStored(session.toJson()).attendance, isNull);
    });
  });
}
