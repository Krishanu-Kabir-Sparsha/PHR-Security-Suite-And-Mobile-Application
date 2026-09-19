import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/config/app_config.dart';
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

    test('both clients target the configured API base URL', () {
      final container = _containerAsMainDoes();
      addTearDown(container.dispose);

      final expected = AppConfig.current.apiBaseUrl;
      expect(container.read(authDioProvider).options.baseUrl, expected);
      expect(container.read(dioProvider).options.baseUrl, expected);
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
    test('the dev flavour points at a real host, not a placeholder', () {
      // `.example` is reserved by RFC 2606 and can never resolve. If it comes
      // back, the API base URL was reverted and the app is silently on mocks.
      expect(AppConfig.current.apiBaseUrl, isNot(contains('.example')));
      expect(AppConfig.current.apiBaseUrl, startsWith('https://'));
    });
  });
}
