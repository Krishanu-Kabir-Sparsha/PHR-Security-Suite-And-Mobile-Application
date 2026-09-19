import '../networking/api_client.dart';
import 'app_capabilities.dart';

/// Reads what this deployment offers the signed-in user.
abstract interface class CapabilitiesRepository {
  /// [previewRole] asks the server to answer as if the user held only that
  /// Plaza role. Refused server-side for anyone who cannot administer the
  /// catalog, so this is a request, not a grant.
  Future<AppCapabilities> load({String? previewRole});
}

class ApiCapabilitiesRepository implements CapabilitiesRepository {
  ApiCapabilitiesRepository({required ApiClient client}) : _client = client;

  final ApiClient _client;

  /// `GET /me/capabilities`
  ///
  /// ```json
  /// {
  ///   "features": ["attendance", "leave", "requests", "security_keys"],
  ///   "has_employee_record": true,
  ///   "hr_modules_installed": ["hr", "hr_attendance", "hr_holidays"]
  /// }
  /// ```
  ///
  /// A failure here is **not** propagated as an error. This call decides which
  /// menu entries exist, so a transient network failure must not empty the app;
  /// it degrades to [AppCapabilities.unknown], which offers nothing extra and
  /// leaves the built-in screens working. A server without this endpoint — an
  /// older deployment of the Odoo module — lands in the same place, which is
  /// what keeps the app installable against both.
  @override
  Future<AppCapabilities> load({String? previewRole}) async {
    try {
      final body = await _client.get<Map<String, dynamic>>(
        '/me/capabilities',
        queryParameters: previewRole == null
            ? null
            : <String, dynamic>{'preview_role': previewRole},
      );
      return AppCapabilities.fromJson(body);
    } catch (_) {
      return AppCapabilities.unknown;
    }
  }
}

/// Everything available. For development against a server without the endpoint.
class MockCapabilitiesRepository implements CapabilitiesRepository {
  MockCapabilitiesRepository({this.capabilities});

  final AppCapabilities? capabilities;

  @override
  Future<AppCapabilities> load({String? previewRole}) async =>
      capabilities ??
      AppCapabilities(
        features: AppFeature.values.toSet(),
        hasEmployeeRecord: true,
        hrModulesInstalled: const [
          'hr',
          'hr_attendance',
          'hr_holidays',
          'hr_payroll',
        ],
      );
}
