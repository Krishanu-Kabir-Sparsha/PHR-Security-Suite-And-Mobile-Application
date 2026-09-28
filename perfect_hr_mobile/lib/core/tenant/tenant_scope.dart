/// Which workspace a piece of stored credential material belongs to.
///
/// ## Why this exists
///
/// Perfect HR is multi-tenant, and the tenants are **different customers**.
/// Before this, three things lived in single, unnamespaced slots of the device
/// keystore:
///
/// ```
/// perfecthr.workspace              which tenant
/// perfecthr.auth.session           access + refresh token
/// perfecthr.device.binding/key     the Ed25519 device key
/// ```
///
/// Nothing tied the second and third to the first. So a handset paired to
/// `acme.perfecthr.net` that then changed workspace to `globex.perfecthr.net`
/// would offer **Acme's** device handle, and a signature made with Acme's
/// private key, to Globex — a different company's server. Globex rejects it,
/// but only after it has arrived in their logs.
///
/// Namespacing the storage keys makes that structurally impossible rather than
/// something a future caller has to remember: material stored for one workspace
/// is simply **not found** when the app is pointed at another. There is no
/// comparison anybody can forget to write.
///
/// ## Why the server's `tenant_id` and not the typed address
///
/// People type `dev`, `dev.perfecthr.net` and `https://dev.perfecthr.net/`
/// interchangeably, and the workspace step accepts all three. Keying off the
/// typed string would make those three different scopes, so a user who typed it
/// differently on Tuesday would silently lose their pairing and be asked to
/// pair again for no reason they could see.
///
/// `/tenant/resolve` returns a canonical `tenant_id` — the database name, which
/// under `dbfilter = ^%h$` is the host — and that is what is used here.
library;

import 'package:meta/meta.dart';

import 'tenant_config.dart';

@immutable
class TenantScope {
  const TenantScope(this.value);

  /// The canonical workspace identifier, normalised.
  final String value;

  /// No workspace chosen yet.
  ///
  /// Distinct from a tenant whose id happens to be empty: [isResolved] is what
  /// callers test, and an unresolved scope must never be used to store
  /// anything, because everything written under it would be unreachable the
  /// moment a real workspace was adopted.
  static const TenantScope none = TenantScope('');

  bool get isResolved => value.isNotEmpty;

  /// Derive a scope from a workspace record.
  ///
  /// Prefers the server-reported `tenantId`; falls back to the address the user
  /// entered only when the workspace has not been resolved against a server
  /// yet, which happens on a dev build that seeds its own host.
  factory TenantScope.of(TenantConfig? config) {
    if (config == null) return TenantScope.none;
    final raw = config.tenantId.trim().isNotEmpty
        ? config.tenantId
        : config.baseUrl;
    return TenantScope(_normalise(raw));
  }

  /// Lower-cased host, with scheme, port, path and trailing dot removed.
  ///
  /// `HTTPS://Dev.PerfectHR.net:8069/` and `dev.perfecthr.net` must land on the
  /// same scope or the same handset would hold two unrelated pairings for one
  /// workspace.
  static String _normalise(String raw) {
    var value = raw.trim().toLowerCase();
    if (value.isEmpty) return '';

    final uri = Uri.tryParse(value.contains('://') ? value : 'https://$value');
    if (uri != null && uri.host.isNotEmpty) {
      value = uri.host;
    } else {
      value = value.split('/').first.split(':').first;
    }
    while (value.endsWith('.')) {
      value = value.substring(0, value.length - 1);
    }
    return value;
  }

  /// Namespace a storage key to this workspace.
  ///
  /// The separator is `::` to match [CacheScope], which already namespaces the
  /// offline cache as `tenantId::userId`. Keeping one convention means a key
  /// seen in a keystore dump is attributable without having to know which
  /// subsystem wrote it.
  String key(String base) => isResolved ? '$base::$value' : base;

  @override
  bool operator ==(Object other) =>
      other is TenantScope && other.value == value;

  @override
  int get hashCode => value.hashCode;

  @override
  String toString() => 'TenantScope(${isResolved ? value : "unresolved"})';
}
