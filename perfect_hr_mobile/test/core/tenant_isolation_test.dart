import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/security/device_key_service.dart';
import 'package:perfect_hr_mobile/core/session/session_state.dart';
import 'package:perfect_hr_mobile/core/session/user_role.dart';
import 'package:perfect_hr_mobile/core/session/permissions.dart';
import 'package:perfect_hr_mobile/core/tenant/tenant_config.dart';
import 'package:perfect_hr_mobile/core/tenant/tenant_scope.dart';
import 'package:perfect_hr_mobile/features/authentication/data/auth_repository.dart';
import 'package:perfect_hr_mobile/features/authentication/data/secure_token_store.dart';
import 'package:perfect_hr_mobile/features/authentication/domain/auth_session.dart';

/// Credential material must not cross a workspace boundary.
///
/// Perfect HR tenants are **different customers**. Before this, the session
/// token and the Ed25519 device key lived in single unnamespaced slots, so a
/// handset paired to `acme.perfecthr.net` that changed workspace to
/// `globex.perfecthr.net` would offer Acme's device handle — and a signature
/// made with Acme's private key — to Globex's server. Globex rejects it, but
/// only after it has arrived in their logs.
///
/// These tests assert the property that makes it impossible: material stored
/// under one scope is **not found** under another. Not "is compared and
/// rejected" — not found, so there is no check a future caller can omit.

const _acme = TenantConfig(
  baseUrl: 'https://acme.perfecthr.net',
  tenantId: 'acme.perfecthr.net',
  tenantName: 'Acme Ltd',
);

const _globex = TenantConfig(
  baseUrl: 'https://globex.perfecthr.net',
  tenantId: 'globex.perfecthr.net',
  tenantName: 'Globex Inc',
);

/// Never called. Every test here exercises storage, not the network, and a
/// repository that threw would prove the refresh path was not being reached.
class _UnusedRepository implements AuthRepository {
  @override
  dynamic noSuchMethod(Invocation invocation) =>
      throw StateError('The network must not be reached in these tests.');
}

AuthSession _session(String token) => AuthSession(
      accessToken: token,
      refreshToken: '$token-refresh',
      expiresAt: DateTime.now().add(const Duration(hours: 1)),
      user: const SessionUser(
        employeeId: '42',
        displayName: 'Karim Hossain',
        role: UserRole.employee,
        tenantId: 'acme.perfecthr.net',
        tenantName: 'Acme Ltd',
        permissions: PermissionSet.empty,
      ),
    );

SecureTokenStore _store(TenantConfig? config) => SecureTokenStore(
      repository: _UnusedRepository(),
      scope: TenantScope.of(config),
    );

LocalAuthDeviceKeyService _keys(TenantConfig? config) =>
    LocalAuthDeviceKeyService(scope: TenantScope.of(config));

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => FlutterSecureStorage.setMockInitialValues({}));

  group('the scope key itself', () {
    test('one workspace typed several ways is one scope', () {
      // The workspace step accepts all of these. Keying off the typed string
      // would make them different scopes, so somebody who typed it differently
      // on Tuesday would silently lose their pairing.
      const variants = [
        'acme.perfecthr.net',
        'ACME.PerfectHR.net',
        'https://acme.perfecthr.net',
        'https://acme.perfecthr.net/',
        'acme.perfecthr.net:8069',
        'acme.perfecthr.net.',
      ];
      for (final variant in variants) {
        expect(
          TenantScope.of(TenantConfig(
            baseUrl: variant,
            tenantId: variant,
            tenantName: 'Acme',
          )).value,
          'acme.perfecthr.net',
          reason: '$variant should normalise to the same scope',
        );
      }
    });

    test('two workspaces are two scopes', () {
      expect(TenantScope.of(_acme), isNot(TenantScope.of(_globex)));
    });

    test('no workspace is unresolved, and namespaces nothing', () {
      // An unresolved scope must not be used to store anything: everything
      // written under it would become unreachable the moment a real workspace
      // was adopted.
      expect(TenantScope.of(null).isResolved, isFalse);
      expect(TenantScope.none.key('perfecthr.auth.session'),
          'perfecthr.auth.session');
    });

    test('a resolved scope namespaces the key', () {
      expect(
        TenantScope.of(_acme).key('perfecthr.auth.session'),
        'perfecthr.auth.session::acme.perfecthr.net',
      );
    });
  });

  group('the session token', () {
    test("one workspace's token is invisible to another", () async {
      // THE test. If this fails, a bearer token minted by one customer's
      // server is being transmitted to another customer's server.
      await _store(_acme).write(_session('acme-token'));

      expect(await _store(_globex).read(), isNull);
      expect((await _store(_acme).read())?.accessToken, 'acme-token');
    });

    test('signing out of one workspace leaves the other intact', () async {
      await _store(_acme).write(_session('acme-token'));
      await _store(_globex).write(_session('globex-token'));

      await _store(_acme).clear();

      expect(await _store(_acme).read(), isNull);
      expect((await _store(_globex).read())?.accessToken, 'globex-token');
    });

    test('an existing install keeps its session on upgrade', () async {
      // Adoption. The unscoped slot predates namespacing, and there was only
      // ever one workspace, so it belongs to whichever one is configured now.
      // Signing everybody out on upgrade would be a worse answer.
      FlutterSecureStorage.setMockInitialValues({
        'perfecthr.auth.session': _encoded('legacy-token'),
      });

      expect((await _store(_acme).read())?.accessToken, 'legacy-token');
    });

    test('adoption moves the value rather than copying it', () async {
      // A legacy value left behind would be adopted a second time by whatever
      // workspace was configured next -- which is the original bug wearing a
      // migration as a disguise.
      FlutterSecureStorage.setMockInitialValues({
        'perfecthr.auth.session': _encoded('legacy-token'),
      });

      await _store(_acme).read();

      expect(await _store(_globex).read(), isNull);
    });

    test('clearing also removes a legacy value never adopted', () async {
      // Signed out before the first read. Leaving it would strand a thirty-day
      // refresh token on disk with nothing that ever reads it again.
      FlutterSecureStorage.setMockInitialValues({
        'perfecthr.auth.session': _encoded('legacy-token'),
      });

      await _store(_acme).clear();

      expect(await _store(_acme).read(), isNull);
      expect(await _store(_globex).read(), isNull);
    });
  });

  group('the device key', () {
    Future<void> pair(TenantConfig config, String handle) async {
      final keys = _keys(config);
      final publicKey = await keys.generateKeyPair();
      expect(publicKey, isNotEmpty);
      await keys.rememberPairing(
        publicKey: publicKey,
        handle: handle,
        login: 'karim@example.internal',
        label: 'Pixel 8',
      );
    }

    test('a pairing at one workspace is not offered to another', () async {
      // The reachable half of the original defect. Pairing creates no session,
      // so nothing stops somebody pairing at Acme and then changing workspace
      // -- and the app would then sign Globex's challenge with Acme's key.
      await pair(_acme, 'acme-handle');

      expect(await _keys(_globex).binding, isNull);
      expect((await _keys(_acme).binding)?.handle, 'acme-handle');
    });

    test('two workspaces can hold separate pairings', () async {
      await pair(_acme, 'acme-handle');
      await pair(_globex, 'globex-handle');

      expect((await _keys(_acme).binding)?.handle, 'acme-handle');
      expect((await _keys(_globex).binding)?.handle, 'globex-handle');
    });

    test('forgetting one pairing leaves the other', () async {
      await pair(_acme, 'acme-handle');
      await pair(_globex, 'globex-handle');

      await _keys(_acme).forget();

      expect(await _keys(_acme).binding, isNull);
      expect((await _keys(_globex).binding)?.handle, 'globex-handle');
    });

    test('an already-paired handset is not asked to pair again', () async {
      FlutterSecureStorage.setMockInitialValues({
        'perfecthr.device.binding': '{"handle":"old-handle",'
            '"login":"karim@example.internal","label":"Pixel 8","counter":3}',
        'perfecthr.device.privatekey': 'c2VlZC1ieXRlcw',
      });

      final binding = await _keys(_acme).binding;

      expect(binding?.handle, 'old-handle');
      // The counter survives. Restarting it at zero would look to the server
      // like a replay and get the device refused.
      expect(binding?.counter, 3);
    });

    test('a legacy binding with no private key is NOT adopted', () async {
      // Both halves move or neither does. A binding whose key failed to come
      // with it would present a handle the device can no longer sign for,
      // which the server reads as a cloned key.
      FlutterSecureStorage.setMockInitialValues({
        'perfecthr.device.binding': '{"handle":"orphan","login":"x",'
            '"label":"y","counter":0}',
      });

      expect(await _keys(_acme).binding, isNull);
    });

    test('an adopted pairing does not reappear under the next workspace',
        () async {
      FlutterSecureStorage.setMockInitialValues({
        'perfecthr.device.binding': '{"handle":"old-handle","login":"x",'
            '"label":"y","counter":0}',
        'perfecthr.device.privatekey': 'c2VlZC1ieXRlcw',
      });

      await _keys(_acme).binding;

      expect(await _keys(_globex).binding, isNull);
    });
  });
}

/// A stored session blob, as [SecureTokenStore.write] would have left it.
String _encoded(String token) {
  final buffer = StringBuffer()
    ..write('{"access_token":"$token",')
    ..write('"refresh_token":"$token-refresh",')
    ..write('"expires_at":"')
    ..write(DateTime.now().add(const Duration(hours: 1)).toUtc().toIso8601String())
    ..write('","enrolment_required":false,"auth_mode":"advance",')
    ..write('"user":{"employee_id":"42","display_name":"Karim Hossain",')
    ..write('"role":"employee","tenant_id":"acme.perfecthr.net",')
    ..write('"tenant_name":"Acme Ltd","permissions":[]}}');
  return buffer.toString();
}
