import 'package:flutter/foundation.dart';

/// The workspace this installation of the app talks to.
///
/// ## Why the app cannot ship with a server address
///
/// Perfect HR provisions every customer as its own PostgreSQL database behind
/// its own hostname, and the server runs `dbfilter = ^%h$` — the database name
/// is *exactly* the hostname. So the tenant identifier and the address are the
/// same string, and one build of the app has to be able to reach all of them.
///
/// An earlier version resolved `AppConfig.apiBaseUrl` at construction, which
/// meant a build could only ever reach one customer. That is the assumption
/// this type removes.
///
/// ## What "resolved" means
///
/// Nothing is stored until `GET /tenant/resolve` has answered on that host. A
/// person who mistypes their company's address is told so before the password
/// field is drawn, rather than having their password posted to whatever did
/// answer.
@immutable
class TenantConfig {
  const TenantConfig({
    required this.baseUrl,
    required this.tenantId,
    required this.tenantName,
    this.logoUrl,
    this.brandColor,
    this.companyStepRequired = false,
    this.companyCount = 0,
    this.advanceAvailable = true,
    this.minimumAppVersion,
  });

  /// Origin only — `https://acme.perfecthr.net`, never with a path.
  ///
  /// The `/api/mobile/v1` suffix is appended where the Dio base URL is built,
  /// so this stays usable for the image URLs the server returns as absolute
  /// paths (`/web/image/...`).
  final String baseUrl;

  /// The server's own name for itself, which under host-based dbfilter is the
  /// database name. Held so a support conversation can name the workspace
  /// exactly rather than approximately.
  final String tenantId;

  /// Shown on the sign-in screen, so somebody sees "Daffodil Group" rather
  /// than a URL echoed back at them.
  final String tenantName;

  final String? logoUrl;
  final String? brandColor;

  /// True only when the workspace publishes more than one company. One company
  /// is not a choice, and an unpublished list is not one either — in both cases
  /// the step is skipped and the server places the user in their own company.
  final bool companyStepRequired;
  final int companyCount;

  /// False when this server cannot verify a device signature at all, so the
  /// app must not offer a sign-in method that could never complete.
  final bool advanceAvailable;

  final String? minimumAppVersion;

  /// Absolute URL for a path the server returned relative, e.g. a logo.
  String absolute(String path) {
    if (path.startsWith('http://') || path.startsWith('https://')) return path;
    return '$baseUrl${path.startsWith('/') ? '' : '/'}$path';
  }

  /// What Dio's `baseUrl` is set to.
  String get apiBaseUrl => '$baseUrl/api/mobile/v1';

  factory TenantConfig.fromJson(String baseUrl, Map<String, Object?> json) {
    return TenantConfig(
      baseUrl: baseUrl,
      tenantId: json['tenant_id'] as String? ?? baseUrl,
      tenantName: json['tenant_name'] as String? ?? baseUrl,
      logoUrl: json['logo_url'] as String?,
      brandColor: json['brand_color'] as String?,
      companyStepRequired: json['company_step_required'] as bool? ?? false,
      companyCount: (json['company_count'] as num?)?.toInt() ?? 0,
      // Defaults to true, so a server too old to report it keeps the behaviour
      // it has always had rather than silently losing the strong path.
      advanceAvailable: json['advance_available'] as bool? ?? true,
      minimumAppVersion: json['minimum_app_version'] as String?,
    );
  }

  Map<String, Object?> toJson() => {
        'base_url': baseUrl,
        'tenant_id': tenantId,
        'tenant_name': tenantName,
        'logo_url': logoUrl,
        'brand_color': brandColor,
        'company_step_required': companyStepRequired,
        'company_count': companyCount,
        'advance_available': advanceAvailable,
        'minimum_app_version': minimumAppVersion,
      };

  factory TenantConfig.fromStored(Map<String, Object?> json) {
    return TenantConfig(
      baseUrl: json['base_url'] as String? ?? '',
      tenantId: json['tenant_id'] as String? ?? '',
      tenantName: json['tenant_name'] as String? ?? '',
      logoUrl: json['logo_url'] as String?,
      brandColor: json['brand_color'] as String?,
      companyStepRequired: json['company_step_required'] as bool? ?? false,
      companyCount: (json['company_count'] as num?)?.toInt() ?? 0,
      advanceAvailable: json['advance_available'] as bool? ?? true,
      minimumAppVersion: json['minimum_app_version'] as String?,
    );
  }
}

/// One company as the sign-in screen sees it.
@immutable
class TenantCompany {
  const TenantCompany({
    required this.id,
    required this.name,
    this.logoUrl,
    this.authModes = const ['advance'],
    this.autoCheckin = true,
  });

  final String id;
  final String name;
  final String? logoUrl;

  /// Which sign-in methods this company permits, most secure first. The server
  /// has already intersected this with anything the account itself requires,
  /// so the app renders it without further reasoning.
  final List<String> authModes;

  final bool autoCheckin;

  bool get allowsBasic => authModes.contains('basic');
  bool get allowsAdvance => authModes.contains('advance');

  /// True when there is a genuine choice to put in front of somebody. One
  /// permitted method is not a choice, and showing two buttons where only one
  /// works is how a sign-in screen teaches people to distrust it.
  bool get offersChoice => authModes.length > 1;

  factory TenantCompany.fromJson(Map<String, Object?> json) {
    final modes = (json['auth_modes'] as List?)
            ?.map((m) => '$m')
            .where((m) => m == 'basic' || m == 'advance')
            .toList() ??
        const <String>[];
    return TenantCompany(
      id: '${json['id'] ?? ''}',
      name: json['name'] as String? ?? '',
      logoUrl: json['logo_url'] as String?,
      // Falls back to the strong method rather than to an empty list. An empty
      // list would render a company nobody could sign into; assuming the
      // stronger option is the safe direction to be wrong in.
      authModes: modes.isEmpty ? const ['advance'] : modes,
      autoCheckin: json['auto_checkin'] as bool? ?? true,
    );
  }
}

/// Raised when what somebody typed cannot be turned into a workspace address.
class WorkspaceAddressError implements Exception {
  const WorkspaceAddressError(this.message);
  final String message;

  @override
  String toString() => message;
}

/// Turn what a person actually types into an origin the app can call.
///
/// People do not type URLs carefully on a phone keyboard, and every one of
/// these is a real thing somebody will enter:
///
///     acme                          -> https://acme.perfecthr.net
///     acme.perfecthr.net            -> https://acme.perfecthr.net
///     ACME.PerfectHR.net            -> https://acme.perfecthr.net
///     https://acme.perfecthr.net/   -> https://acme.perfecthr.net
///     acme.perfecthr.net/web/login  -> https://acme.perfecthr.net
///     https://acme.perfecthr.net:8069 -> https://acme.perfecthr.net:8069
///
/// The bare-label case matters most: it is what somebody reads off an induction
/// email, and rejecting it would make the very first screen of the app the
/// hardest one.
///
/// Forces `https` for any real host. The only thing exempt is a loopback
/// address, because a developer running a local server has no certificate and
/// there is nothing to protect on the loopback interface. Downgrading a real
/// host would put a password on the wire in clear, so an explicit `http://`
/// for anything else is refused rather than quietly honoured.
String normaliseWorkspaceUrl(String input, {String defaultDomain = 'perfecthr.net'}) {
  var value = input.trim();
  if (value.isEmpty) {
    throw const WorkspaceAddressError('Enter your Perfect HR address.');
  }

  // Strip a scheme if present, remembering whether it was explicitly http.
  var explicitlyInsecure = false;
  if (value.startsWith('https://')) {
    value = value.substring(8);
  } else if (value.startsWith('http://')) {
    explicitlyInsecure = true;
    value = value.substring(7);
  }

  // Everything after the authority is not ours to keep: people paste the page
  // they happened to be on, which is usually /web/login or /odoo.
  final slash = value.indexOf('/');
  if (slash >= 0) value = value.substring(0, slash);
  value = value.split('?').first.split('#').first.trim();

  if (value.isEmpty) {
    throw const WorkspaceAddressError('Enter your Perfect HR address.');
  }

  // Credentials in the authority are never legitimate here and would be sent
  // to whatever host follows them.
  if (value.contains('@')) {
    throw const WorkspaceAddressError(
      'That does not look like a Perfect HR address.',
    );
  }

  var host = value.toLowerCase();
  var port = '';
  final colon = host.lastIndexOf(':');
  if (colon > 0) {
    port = host.substring(colon);
    host = host.substring(0, colon);
    if (int.tryParse(port.substring(1)) == null) {
      throw const WorkspaceAddressError(
        'That does not look like a Perfect HR address.',
      );
    }
  }

  final isLoopback =
      host == 'localhost' || host == '127.0.0.1' || host == '::1';

  // A bare label becomes a subdomain of the product's own domain. Not applied
  // to loopback, and not applied to anything already carrying a dot.
  if (!host.contains('.') && !isLoopback) {
    if (!RegExp(r'^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$').hasMatch(host)) {
      throw const WorkspaceAddressError(
        'That does not look like a Perfect HR address.',
      );
    }
    host = '$host.$defaultDomain';
  }

  if (!isLoopback &&
      !RegExp(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$')
          .hasMatch(host)) {
    throw const WorkspaceAddressError(
      'That does not look like a Perfect HR address.',
    );
  }

  if (explicitlyInsecure && !isLoopback) {
    throw const WorkspaceAddressError(
      'Perfect HR addresses must start with https, so your password is never '
      'sent unprotected. Remove "http://" and try again.',
    );
  }

  final scheme = isLoopback ? 'http' : 'https';
  return '$scheme://$host$port';
}
