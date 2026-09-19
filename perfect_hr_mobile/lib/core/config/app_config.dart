/// Build flavour — Tech-Stack §25.
///
/// Endpoints must never be hard-coded into the application. The flavour is
/// injected at build time via `--dart-define=FLAVOR=dev|qa|uat|prod`.
enum AppFlavor { dev, qa, uat, prod }

/// Environment configuration resolved once at start-up.
class AppConfig {
  const AppConfig({
    required this.flavor,
    required this.apiBaseUrl,
    required this.keycloakBaseUrl,
    required this.keycloakRealm,
    required this.keycloakClientId,
  });

  final AppFlavor flavor;

  /// APISIX gateway base URL. All traffic goes through the gateway —
  /// Instructions §7 forbids direct service or database access.
  final String apiBaseUrl;

  final String keycloakBaseUrl;
  final String keycloakRealm;
  final String keycloakClientId;

  /// Dev-only affordances (role switcher, verbose logging, debug banners).
  bool get allowsDevTools => flavor == AppFlavor.dev || flavor == AppFlavor.qa;

  /// Whether verbose request/response logging is permitted.
  /// Never true in production: payload logs can contain HR data
  /// (Instructions §27 — do not leak sensitive HR data to telemetry).
  bool get allowsVerboseLogging => flavor == AppFlavor.dev;

  static AppConfig? _current;

  static AppConfig get current {
    final config = _current;
    assert(
      config != null,
      'AppConfig.initialise() must be called from main() before use.',
    );
    return config ?? _resolve(AppFlavor.dev);
  }

  /// Called from `main()` before `runApp`.
  static AppConfig initialise({String? flavorName}) {
    final flavor = _parseFlavor(
      flavorName ?? const String.fromEnvironment('FLAVOR', defaultValue: 'dev'),
    );
    return _current = _resolve(flavor);
  }

  static AppFlavor _parseFlavor(String value) {
    return AppFlavor.values.firstWhere(
      (f) => f.name == value.toLowerCase(),
      orElse: () => AppFlavor.dev,
    );
  }

  /// PLACEHOLDER HOSTS — Project State Q5.
  /// Real APISIX and Keycloak coordinates are not yet available. These follow
  /// the naming convention in Tech-Stack §25 and must be confirmed before the
  /// authentication task (Task 3) integrates against a live realm.
  static AppConfig _resolve(AppFlavor flavor) {
    return switch (flavor) {
      AppFlavor.dev => const AppConfig(
          flavor: AppFlavor.dev,
          apiBaseUrl: 'https://dev.perfecthr.net/api/mobile/v1',
          keycloakBaseUrl: 'https://id-dev.perfecthr.example',
          keycloakRealm: 'perfect-hr',
          keycloakClientId: 'perfect-hr-mobile',
        ),
      AppFlavor.qa => const AppConfig(
          flavor: AppFlavor.qa,
          apiBaseUrl: 'https://api-qa.perfecthr.example/api/v1',
          keycloakBaseUrl: 'https://id-qa.perfecthr.example',
          keycloakRealm: 'perfect-hr',
          keycloakClientId: 'perfect-hr-mobile',
        ),
      AppFlavor.uat => const AppConfig(
          flavor: AppFlavor.uat,
          apiBaseUrl: 'https://api-uat.perfecthr.example/api/v1',
          keycloakBaseUrl: 'https://id-uat.perfecthr.example',
          keycloakRealm: 'perfect-hr',
          keycloakClientId: 'perfect-hr-mobile',
        ),
      AppFlavor.prod => const AppConfig(
          flavor: AppFlavor.prod,
          apiBaseUrl: 'https://api.perfecthr.example/api/v1',
          keycloakBaseUrl: 'https://id.perfecthr.example',
          keycloakRealm: 'perfect-hr',
          keycloakClientId: 'perfect-hr-mobile',
        ),
    };
  }
}
