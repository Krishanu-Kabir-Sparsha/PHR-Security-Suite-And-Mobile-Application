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

  /// A challenge for the device the user already holds, or null when they hold
  /// none.
  ///
  /// Adding a second device requires proving control of the first, in the same
  /// request that stores the new one. A first enrolment needs no such proof,
  /// and null says so — which is what decides whether the user sees one prompt
  /// or two.
  Future<Map<String, dynamic>?> stepUpChallenge();

  /// Creation options for a new credential, from the server.
  Future<Map<String, dynamic>> enrolmentOptions();

  /// Register the new credential. [assertion] is the step-up, when there was
  /// one, and travels in the same request on purpose.
  Future<AuthenticatorStatus> completeEnrolment({
    required Map<String, dynamic> credential,
    required String deviceLabel,
    Map<String, dynamic>? assertion,
  });
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
    return AuthenticatorStatus.fromJson(body);
  }

  /// `POST /me/authenticators/step-up`
  @override
  Future<Map<String, dynamic>?> stepUpChallenge() async {
    final body = await _client.post<Map<String, dynamic>>(
      '/me/authenticators/step-up',
    );
    if (body['required'] != true) return null;
    final options = body['options'];
    return options is Map ? options.cast<String, dynamic>() : null;
  }

  /// `POST /me/authenticators/options`
  @override
  Future<Map<String, dynamic>> enrolmentOptions() async {
    return _client.post<Map<String, dynamic>>('/me/authenticators/options');
  }

  /// `POST /me/authenticators/verify`
  ///
  /// The credential and the step-up assertion go together. A marker set by a
  /// separate call would already be gone by the time this one arrived, which is
  /// exactly why adding a second device used to be impossible.
  @override
  Future<AuthenticatorStatus> completeEnrolment({
    required Map<String, dynamic> credential,
    required String deviceLabel,
    Map<String, dynamic>? assertion,
  }) async {
    final body = await _client.post<Map<String, dynamic>>(
      '/me/authenticators/verify',
      data: <String, Object?>{
        'credential': credential,
        'device_label': deviceLabel,
        if (assertion != null) 'assertion': assertion,
      },
    );
    // The verify response carries the new counts but not the device list, so
    // the screen re-reads rather than rendering a half-populated status.
    return loadStatus().catchError((_) => AuthenticatorStatus.fromJson(body));
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

  @override
  Future<Map<String, dynamic>?> stepUpChallenge() async => null;

  @override
  Future<Map<String, dynamic>> enrolmentOptions() async =>
      const {'challenge': 'mock'};

  @override
  Future<AuthenticatorStatus> completeEnrolment({
    required Map<String, dynamic> credential,
    required String deviceLabel,
    Map<String, dynamic>? assertion,
  }) async =>
      status ?? sample();
}
