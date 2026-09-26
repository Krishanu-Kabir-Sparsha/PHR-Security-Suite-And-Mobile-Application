/// Build flavour — Tech-Stack §25.
///
/// The flavour is injected at build time via
/// `--dart-define=FLAVOR=dev|qa|uat|prod`.
enum AppFlavor { dev, qa, uat, prod }

/// Environment configuration resolved once at start-up.
///
/// ## The server address is NOT here any more
///
/// It used to be: each flavour carried an `apiBaseUrl`, and the Dio clients
/// read it at construction. That is wrong for this product and was wrong
/// quietly. Perfect HR gives every customer their own database behind their own
/// hostname (`dbfilter = ^%h$`, so the database name *is* the hostname), which
/// means one build of the app has to reach all of them. A compiled-in address
/// can reach exactly one, and the only way to serve a second customer would
/// have been a second build.
///
/// The workspace now arrives at run time — see `core/tenant/` — and what is
/// left here is what genuinely is fixed at build time: which flavour this is,
/// and therefore what diagnostics are permitted.
class AppConfig {
  const AppConfig({
    required this.flavor,
    this.seedWorkspaceUrl,
  });

  final AppFlavor flavor;

  /// A workspace assumed on this build when none has been chosen yet.
  ///
  /// Set for dev and QA so a developer is not asked for an address on every
  /// fresh install. **Null for UAT and production, deliberately.** There is no
  /// correct host to guess for a real customer, and a guess would mean a real
  /// password posted to a host nobody chose.
  final String? seedWorkspaceUrl;

  /// Dev-only affordances (role switcher, verbose logging, debug banners).
  bool get allowsDevTools => flavor == AppFlavor.dev || flavor == AppFlavor.qa;

  /// Whether verbose request/response logging is permitted.
  /// Never true in production: payload logs can contain HR data
  /// (Instructions §27 — do not leak sensitive HR data to telemetry).
  bool get allowsVerboseLogging => flavor == AppFlavor.dev;

  /// Whether the user may type their own workspace address.
  ///
  /// True everywhere. Even on a seeded dev build, being able to point the app
  /// at a colleague's server is the difference between testing multi-tenancy
  /// and assuming it works.
  bool get allowsWorkspaceEntry => true;

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

  static AppConfig _resolve(AppFlavor flavor) {
    return switch (flavor) {
      // A named dev host so the common case needs no typing. Overridable at
      // build time for anyone running a server somewhere else:
      //   --dart-define=WORKSPACE_URL=https://localhost:8069
      AppFlavor.dev => const AppConfig(
          flavor: AppFlavor.dev,
          seedWorkspaceUrl: String.fromEnvironment(
            'WORKSPACE_URL',
            defaultValue: 'https://dev.perfecthr.net',
          ),
        ),
      AppFlavor.qa => const AppConfig(
          flavor: AppFlavor.qa,
          seedWorkspaceUrl: String.fromEnvironment(
            'WORKSPACE_URL',
            defaultValue: 'https://qa.perfecthr.net',
          ),
        ),
      // No seed. Every real user names their own workspace, because there is
      // no single right answer and a wrong one costs a password.
      AppFlavor.uat => const AppConfig(flavor: AppFlavor.uat),
      AppFlavor.prod => const AppConfig(flavor: AppFlavor.prod),
    };
  }
}
