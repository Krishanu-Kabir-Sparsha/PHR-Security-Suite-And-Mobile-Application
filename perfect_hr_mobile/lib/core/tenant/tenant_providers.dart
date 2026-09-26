import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../config/app_config.dart';
import 'tenant_config.dart';
import 'tenant_repository.dart';

/// Where the chosen workspace is remembered between launches.
///
/// In the keystore rather than SharedPreferences, alongside the tokens. The
/// address itself is not a secret, but the pair "this handset belongs to Acme
/// Ltd" is exactly the sort of inference an unencrypted preferences file hands
/// to anything that can read it, and there is no cost to keeping it with the
/// session it belongs to.
class TenantStore {
  TenantStore({FlutterSecureStorage? storage})
      : _storage = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
            );

  static const String _key = 'perfecthr.workspace';

  final FlutterSecureStorage _storage;

  Future<TenantConfig?> read() async {
    try {
      final raw = await _storage.read(key: _key);
      if (raw == null || raw.isEmpty) return null;
      final decoded = jsonDecode(raw);
      if (decoded is! Map) return null;
      final config = TenantConfig.fromStored(decoded.cast<String, Object?>());
      // A stored record with no address is unusable and would produce a Dio
      // with an empty base URL, which fails on every call with nothing
      // explaining why. Treated as "no workspace chosen", which sends the user
      // to the screen that fixes it.
      return config.baseUrl.isEmpty ? null : config;
    } catch (_) {
      // Unreadable is treated as unset. The remedy — entering the address
      // again — is one the user can reach, where a crash on launch is not.
      return null;
    }
  }

  Future<void> write(TenantConfig config) async {
    try {
      await _storage.write(key: _key, value: jsonEncode(config.toJson()));
    } catch (_) {
      // The session still works for this run; it simply will not be remembered.
      // Failing the sign-in over it would be worse.
    }
  }

  Future<void> clear() async {
    try {
      await _storage.delete(key: _key);
    } catch (_) {
      // Nothing useful to do, and nothing depends on it having succeeded.
    }
  }
}

final tenantStoreProvider = Provider<TenantStore>((ref) => TenantStore());

final tenantRepositoryProvider =
    Provider<TenantRepository>((ref) => HttpTenantRepository());

/// The workspace in force, or null when none has been chosen.
///
/// Seeded from storage before the first frame in `main.dart`, so a returning
/// user does not see the workspace screen flash past on every cold start.
class TenantController extends Notifier<TenantConfig?> {
  @override
  TenantConfig? build() => _seed();

  /// On a dev or QA build, the flavour's own host is assumed so a developer is
  /// not asked for an address on every fresh install. Never on UAT or
  /// production: there is no correct host to guess for a real customer, and
  /// guessing one would send a real password somewhere nobody chose.
  static TenantConfig? _seed() {
    final config = AppConfig.current;
    final seed = config.seedWorkspaceUrl;
    if (seed == null) return null;
    return TenantConfig(
      baseUrl: seed,
      tenantId: seed,
      tenantName: 'Perfect HR (${config.flavor.name})',
    );
  }

  /// Adopt a workspace that has already been resolved against its server.
  Future<void> adopt(TenantConfig config) async {
    state = config;
    await ref.read(tenantStoreProvider).write(config);
  }

  /// Restore the remembered workspace, if there is one.
  Future<TenantConfig?> restore() async {
    final stored = await ref.read(tenantStoreProvider).read();
    if (stored != null) state = stored;
    return state;
  }

  /// Forget the workspace entirely.
  ///
  /// Only for "sign in to a different workspace". An ordinary sign-out keeps
  /// it: making somebody retype their company's address every morning would be
  /// a worse app for no benefit, since the address is not a credential.
  Future<void> forget() async {
    await ref.read(tenantStoreProvider).clear();
    state = _seed();
  }
}

final tenantControllerProvider =
    NotifierProvider<TenantController, TenantConfig?>(TenantController.new);

/// The base URL every API call is made against.
///
/// Watched by the Dio providers, so choosing a workspace rebuilds the client
/// rather than requiring a restart. Empty when no workspace is set, which is a
/// state the router never routes into: the workspace screen comes first.
final apiBaseUrlProvider = Provider<String>((ref) {
  final tenant = ref.watch(tenantControllerProvider);
  return tenant?.apiBaseUrl ?? '';
});

/// The companies a workspace publishes, fetched on demand.
///
/// `family` on the base URL rather than reading the controller, so the sign-in
/// screen can look up a workspace the user is still deciding about without
/// adopting it first.
final tenantCompaniesProvider =
    FutureProvider.family<List<TenantCompany>, String>((ref, baseUrl) {
  if (baseUrl.isEmpty) return Future.value(const []);
  return ref.watch(tenantRepositoryProvider).companies(baseUrl);
});
