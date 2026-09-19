import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/data_providers.dart';
import '../networking/api_client.dart';
import '../session/session_controller.dart';
import 'app_capabilities.dart';
import 'model_access.dart';
import 'capabilities_repository.dart';

final capabilitiesRepositoryProvider = Provider<CapabilitiesRepository>((ref) {
  if (ref.watch(dataSourceModeProvider) == DataSourceMode.mock) {
    return MockCapabilitiesRepository();
  }
  return ApiCapabilitiesRepository(client: ref.watch(apiClientProvider));
});

/// The Plaza role currently being previewed, or null for the real session.
///
/// Held here rather than inside the notifier so that selecting a role simply
/// invalidates the capability read — one code path builds capabilities, whether
/// they are the user's own or a preview.
final previewRoleProvider = StateProvider<String?>((ref) => null);

/// What the server offers this user.
///
/// Keyed on the session, so signing in as somebody else re-reads it rather than
/// carrying the previous user's menu over. Deliberately not cached to disk: a
/// stale capability set would either hide a feature that was just enabled or
/// offer one that was just removed, and the read is small.
final capabilitiesProvider =
    AsyncNotifierProvider<CapabilitiesNotifier, AppCapabilities>(
  CapabilitiesNotifier.new,
);

class CapabilitiesNotifier extends AsyncNotifier<AppCapabilities> {
  @override
  Future<AppCapabilities> build() async {
    // Re-read whenever the principal changes.
    ref.watch(activeUserProvider);
    if (ref.read(activeUserProvider) == null) return AppCapabilities.unknown;
    return ref
        .watch(capabilitiesRepositoryProvider)
        .load(previewRole: ref.watch(previewRoleProvider));
  }

  Future<void> reload() async {
    state = const AsyncValue<AppCapabilities>.loading().copyWithPrevious(state);
    state = await AsyncValue.guard(
      () => ref.read(capabilitiesRepositoryProvider).load(
            previewRole: ref.read(previewRoleProvider),
          ),
    );
  }
}

/// The resolved capability set, falling back to [AppCapabilities.unknown].
///
/// Most callers want this rather than the AsyncValue: a menu cannot render a
/// spinner per entry, and "not yet known" and "not available" lead to the same
/// screen. Screens that need to distinguish the two watch
/// [capabilitiesProvider] directly.
final resolvedCapabilitiesProvider = Provider<AppCapabilities>((ref) {
  return ref.watch(capabilitiesProvider).valueOrNull ??
      AppCapabilities.unknown;
});

/// Whether a given feature should be offered.
final hasFeatureProvider = Provider.family<bool, AppFeature>((ref, feature) {
  return ref.watch(resolvedCapabilitiesProvider).has(feature);
});

/// Whether the user may perform an operation on a model, per the server.
///
/// The basis for enabling any control that writes. Reads the same answer Odoo
/// gives when the call is actually made, so a button this enables will not
/// 403 — and a button it disables was never going to succeed.
final canProvider =
    Provider.family<bool, ({String model, ModelOperation operation})>(
  (ref, query) {
    return ref
        .watch(resolvedCapabilitiesProvider)
        .can(query.model, query.operation);
  },
);

/// Whether the user approves this class of transaction under any Plaza role.
///
/// Not the same as write access to the model. Odoo's ACL cannot tell an
/// approval apart from any other write, and that distinction is what the role
/// catalog exists to carry: a Line Manager writing to `hr.leave` is approving
/// somebody's request; an employee writing to it is editing their own.
final approvesProvider = Provider.family<bool, TransactionType>((ref, type) {
  return ref.watch(resolvedCapabilitiesProvider).approves(type);
});

/// The Plaza roles the user holds, for the profile and role-preview surfaces.
final plazaRolesProvider = Provider<List<PlazaRole>>((ref) {
  return ref.watch(resolvedCapabilitiesProvider).roles;
});

/// Catalog-versus-reality findings. Empty unless the user can act on them.
final divergenceProvider = Provider<List<DivergenceFinding>>((ref) {
  return ref.watch(resolvedCapabilitiesProvider).divergence;
});

/// The role being previewed, or null when the session is the user's own.
final previewingRoleProvider = Provider<AssignableRole?>((ref) {
  return ref.watch(resolvedCapabilitiesProvider).previewingRole;
});

/// Roles this user may preview. Empty for anyone who cannot administer them.
final assignableRolesProvider = Provider<List<AssignableRole>>((ref) {
  return ref.watch(resolvedCapabilitiesProvider).assignableRoles;
});
