import '../../../core/networking/api_client.dart';
import '../domain/authenticator_status.dart';

/// Reads WebAuthn enrolment status for the signed-in user.
///
/// Deliberately **uncached**, unlike the dashboard. Two reasons:
///
/// * The screen's whole job is to answer "am I enrolled?", and a two-minute-old
///   yes is worse than a spinner. Someone who has just enrolled in the browser
///   comes back to this screen expecting to see it.
/// * A stale "sufficient: true" would tell a Tier 3 approver they hold two
///   devices when one has been revoked, which is exactly the situation the
///   two-device rule exists to catch.
///
/// It also fails honestly offline rather than serving a remembered answer.
abstract interface class AuthenticatorRepository {
  Future<AuthenticatorStatus> loadStatus();
}

class ApiAuthenticatorRepository implements AuthenticatorRepository {
  ApiAuthenticatorRepository({required ApiClient client}) : _client = client;

  final ApiClient _client;

  /// PROPOSED API: `GET /me/authenticators`
  ///
  /// Auth: bearer token. Scope: always the caller; there is no path parameter,
  /// because one user reading another's authenticator inventory is a
  /// reconnaissance tool, not a feature.
  ///
  /// ```json
  /// {
  ///   "enrolled": 1,
  ///   "required": 2,
  ///   "sufficient": false,
  ///   "configured": true,
  ///   "relying_party": "dev.perfecthr.net",
  ///   "enrol_url": "https://dev.perfecthr.net/webauthn/enroll",
  ///   "requires_web_session": true,
  ///   "devices": [
  ///     {"id": "3", "label": "Work PC", "enrolled_at": "2026-09-09 05:29:30",
  ///      "backed_up": false}
  ///   ]
  /// }
  /// ```
  @override
  Future<AuthenticatorStatus> loadStatus() async {
    final body = await _client.get<Map<String, dynamic>>('/me/authenticators');
    return AuthenticatorStatus.fromJson(body ?? const {});
  }
}

/// Mock for development against a server without the mobile API installed.
class MockAuthenticatorRepository implements AuthenticatorRepository {
  MockAuthenticatorRepository({this.status});

  final AuthenticatorStatus? status;

  /// Matches the state the user is actually in on dev.perfecthr.net: one
  /// device enrolled, two required for the final-approval role.
  static AuthenticatorStatus sample() => AuthenticatorStatus(
        enrolled: 1,
        required_: 2,
        sufficient: false,
        configured: true,
        relyingParty: 'dev.perfecthr.net',
        enrolUrl: 'https://dev.perfecthr.net/webauthn/enroll',
        devices: [
          EnrolledAuthenticator(
            id: '1',
            label: 'Work PC',
            enrolledAt: DateTime(2026, 9, 9, 5, 29, 30),
          ),
        ],
      );

  /// The server has no relying party set, so enrolment cannot start. Worth
  /// being able to render: it is the first thing a new deployment shows.
  static AuthenticatorStatus unconfiguredSample() => const AuthenticatorStatus(
        enrolled: 0,
        required_: 1,
        sufficient: false,
        configured: false,
        devices: [],
      );

  @override
  Future<AuthenticatorStatus> loadStatus() async => status ?? sample();
}
