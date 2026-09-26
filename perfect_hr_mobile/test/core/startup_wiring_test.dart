import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/config/app_config.dart';
import 'package:perfect_hr_mobile/core/tenant/tenant_config.dart';
import 'package:perfect_hr_mobile/core/tenant/tenant_providers.dart';
import 'package:perfect_hr_mobile/core/networking/api_client.dart';
import 'package:perfect_hr_mobile/core/networking/auth_interceptor.dart';
import 'package:perfect_hr_mobile/core/networking/connectivity_service.dart';
import 'package:perfect_hr_mobile/features/authentication/application/auth_providers.dart';

/// Regression test for a launch failure that showed as a black screen.
///
/// Overriding `authTokenStoreProvider` with the real store closed a cycle in
/// the provider graph:
///
///   authTokenStoreProvider -> secureTokenStoreProvider
///     -> authRepositoryProvider -> apiClientProvider -> dioProvider
///       -> authTokenStoreProvider
///
/// Riverpod throws on that while the first frame is being built, so `runApp`
/// was never reached and the app opened to nothing at all. `flutter analyze`
/// cannot see it — the graph only closes at runtime, and only once the
/// override is applied — so it needs a test.
///
/// The fix was to give the auth endpoints their own interceptor-free client
/// (`authApiClientProvider`), which is also independently required: refresh
/// must not travel through the interceptor that triggers refresh.
///
/// These tests build the container exactly as `main()` does. Reading a provider
/// constructs it, which is all it takes to close a cycle, and none of these
/// constructors perform I/O.

ProviderContainer _containerAsMainDoes() {
  return ProviderContainer(
    overrides: [
      // Exactly the override main() applies. This is the subject of the test.
      authTokenStoreProvider.overrideWith(
        (ref) => ref.watch(secureTokenStoreProvider),
      ),
      // Substituted only because the real one reaches a platform MethodChannel,
      // which has no implementation in a unit test. It sits on the same graph
      // path, so the shape under test is unchanged.
      connectivityServiceProvider.overrideWithValue(FakeConnectivityService()),
    ],
  );
}

void main() {
  // connectivity_plus and flutter_secure_storage both resolve platform
  // channels during construction, and those need a binding even when no call
  // is made.
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(AppConfig.initialise);

  group('start-up provider graph', () {
    test('the token store override does not close a cycle', () {
      final container = _containerAsMainDoes();
      addTearDown(container.dispose);

      expect(() => container.read(authTokenStoreProvider), returnsNormally);
    });

    test('the main API client still builds under the override', () {
      // The cycle ran through dioProvider, so this is the read that failed.
      final container = _containerAsMainDoes();
      addTearDown(container.dispose);

      expect(() => container.read(apiClientProvider), returnsNormally);
      expect(() => container.read(dioProvider), returnsNormally);
    });

    test('auth endpoints use a client without the auth interceptor', () {
      final container = _containerAsMainDoes();
      addTearDown(container.dispose);

      final authDio = container.read(authDioProvider);
      final mainDio = container.read(dioProvider);

      // Not the same instance, and the auth one carries no AuthInterceptor:
      // refreshing through the interceptor that triggers refresh would recurse
      // on any 401 from the refresh call itself.
      expect(identical(authDio, mainDio), isFalse);
      expect(
        authDio.interceptors.whereType<AuthInterceptor>(),
        isEmpty,
        reason: 'the auth client must not carry the auth interceptor',
      );
      expect(
        mainDio.interceptors.whereType<AuthInterceptor>(),
        isNotEmpty,
        reason: 'the main client must still attach bearer tokens',
      );
    });

    test('both clients target the resolved workspace', () {
      final container = _containerAsMainDoes();
      addTearDown(container.dispose);

      // The workspace is chosen at run time, so the assertion is that both
      // clients agree with whatever it currently is -- not that it matches a
      // constant. A build where the two disagreed would send authenticated
      // calls to one server and sign-in calls to another.
      final expected = container.read(apiBaseUrlProvider);
      expect(container.read(authDioProvider).options.baseUrl, expected);
      expect(container.read(dioProvider).options.baseUrl, expected);
    });

    test('choosing a workspace repoints both clients', () {
      // The regression this guards: the Dio providers used to read a
      // compiled-in URL at construction, so pointing the app at a different
      // customer changed nothing and every call kept going to the old server
      // -- with the new customer's token attached.
      final container = _containerAsMainDoes();
      addTearDown(container.dispose);

      const workspace = TenantConfig(
        baseUrl: 'https://acme.perfecthr.net',
        tenantId: 'acme.perfecthr.net',
        tenantName: 'Acme Ltd',
      );
      container.read(tenantControllerProvider.notifier).adopt(workspace);

      expect(
        container.read(dioProvider).options.baseUrl,
        'https://acme.perfecthr.net/api/mobile/v1',
      );
      expect(
        container.read(authDioProvider).options.baseUrl,
        'https://acme.perfecthr.net/api/mobile/v1',
      );
    });

    test('the whole graph builds in one pass, as at launch', () {
      // main() reads several of these in sequence. Reading them together is
      // the closest a unit test gets to the real start-up path.
      final container = _containerAsMainDoes();
      addTearDown(container.dispose);

      expect(() {
        container.read(authTokenStoreProvider);
        container.read(authRepositoryProvider);
        container.read(secureTokenStoreProvider);
        container.read(apiClientProvider);
      }, returnsNormally);
    });
  });

  group('configuration', () {
    test('the dev flavour seeds a real host, not a placeholder', () {
      // `.example` is reserved by RFC 2606 and can never resolve. If it comes
      // back, the seed was reverted and the app is silently on mocks.
      final seed = AppConfig.current.seedWorkspaceUrl;
      expect(seed, isNotNull);
      expect(seed, isNot(contains('.example')));
      expect(seed, startsWith('https://'));
    });

    test('a bare company name resolves to a workspace address', () {
      // What somebody reads off an induction email. Rejecting it would make
      // the very first screen of the app the hardest one.
      expect(
        normaliseWorkspaceUrl('acme'),
        'https://acme.perfecthr.net',
      );
    });

    test('a pasted page URL is reduced to its origin', () {
      expect(
        normaliseWorkspaceUrl('https://acme.perfecthr.net/web/login?db=x'),
        'https://acme.perfecthr.net',
      );
    });

    test('an explicit http address is refused for a real host', () {
      // Honouring it quietly would put a password on the wire in clear.
      expect(
        () => normaliseWorkspaceUrl('http://acme.perfecthr.net'),
        throwsA(isA<WorkspaceAddressError>()),
      );
    });

    test('loopback is allowed over http, for a developer', () {
      expect(normaliseWorkspaceUrl('localhost:8069'), 'http://localhost:8069');
    });
  });
}
