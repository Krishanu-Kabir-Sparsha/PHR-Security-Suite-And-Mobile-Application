import '../../../core/networking/api_client.dart';
import '../../../core/security/second_factor.dart';
import '../domain/override_approval.dart';

/// Reads and acts on override approvals.
///
/// Deliberately **uncached**. An approval queue is a list of things other
/// people are waiting on, and a two-minute-old copy would show an approver a
/// request somebody else has already signed — or hide one that has just
/// arrived. It fails honestly offline rather than serving a remembered answer.
abstract interface class ApprovalsRepository {
  Future<ApprovalQueue> loadQueue();

  /// A challenge bound to one override, and which proof answers it.
  Future<ApprovalChallenge> challengeFor(String requestId);

  /// Approve, sending the proof in the same request.
  ///
  /// Exactly one of [assertion] and [signaturePayload] is sent, chosen by the
  /// method the challenge named.
  Future<void> approve({
    required String requestId,
    Map<String, dynamic>? assertion,
    Map<String, dynamic>? signaturePayload,
  });

  /// Reject. No device needed — see [ApiApprovalsRepository.reject].
  Future<void> reject(String requestId);
}

/// What the server wants signed, and by what.
class ApprovalChallenge {
  const ApprovalChallenge({
    required this.method,
    this.options = const <String, dynamic>{},
    this.deviceChallenge = const <String, dynamic>{},
  });

  final SecondFactorMethod method;

  /// WebAuthn request options, passed to the platform untouched.
  final Map<String, dynamic> options;

  /// `{version, challenge, context_ref, devices}` for the paired-key path.
  final Map<String, dynamic> deviceChallenge;

  /// The nonce to sign.
  String get challengeValue => '${deviceChallenge['challenge'] ?? ''}';

  /// What the signature authorises. Signed alongside the nonce, so a
  /// confirmation given for one override cannot approve another.
  String get contextRef => '${deviceChallenge['context_ref'] ?? ''}';

  factory ApprovalChallenge.fromJson(Map<String, dynamic> json) {
    Map<String, dynamic> asMap(Object? value) =>
        value is Map ? value.cast<String, dynamic>() : const <String, dynamic>{};
    return ApprovalChallenge(
      method: parseSecondFactorMethod(json['method']),
      options: asMap(json['options']),
      deviceChallenge: asMap(json['device_challenge']),
    );
  }
}

class ApiApprovalsRepository implements ApprovalsRepository {
  ApiApprovalsRepository({required ApiClient client}) : _client = client;

  final ApiClient _client;

  /// `GET /me/approvals`
  @override
  Future<ApprovalQueue> loadQueue() async {
    final body = await _client.get<Map<String, dynamic>>('/me/approvals');
    return ApprovalQueue.fromJson(body);
  }

  /// `POST /me/approvals/{id}/challenge`
  @override
  Future<ApprovalChallenge> challengeFor(String requestId) async {
    final body = await _client.post<Map<String, dynamic>>(
      '/me/approvals/$requestId/challenge',
    );
    return ApprovalChallenge.fromJson(body);
  }

  /// `POST /me/approvals/{id}/approve`
  ///
  /// The proof travels with the approval because the server consumes it within
  /// the request that records the decision. It authorises one action once, not
  /// everything the user does for the rest of the day.
  @override
  Future<void> approve({
    required String requestId,
    Map<String, dynamic>? assertion,
    Map<String, dynamic>? signaturePayload,
  }) async {
    await _client.post<Map<String, dynamic>>(
      '/me/approvals/$requestId/approve',
      data: <String, Object?>{
        if (assertion != null) 'assertion': assertion,
        if (signaturePayload != null) 'signature_payload': signaturePayload,
      },
    );
  }

  /// `POST /me/approvals/{id}/reject`
  ///
  /// No device confirmation, deliberately. Strong authentication is required
  /// for approvals because an approval can change a frozen record; a rejection
  /// cannot, and putting a fingerprint prompt between a reviewer and "no" would
  /// discourage the safe answer.
  @override
  Future<void> reject(String requestId) async {
    await _client.post<Map<String, dynamic>>(
      '/me/approvals/$requestId/reject',
    );
  }
}

/// Mock for development and widget tests.
class MockApprovalsRepository implements ApprovalsRepository {
  MockApprovalsRepository({ApprovalQueue? queue}) : _queue = queue ?? sample();

  ApprovalQueue _queue;

  static ApprovalQueue sample() {
    return ApprovalQueue(
      available: true,
      requests: [
        OverrideApproval(
          id: '41',
          reference: 'OVR-2026-0041',
          target: 'Payslip PS-2026-0219',
          requestedBy: 'Nabila Islam',
          contextRef: 'override.request,41',
          reason: 'Correction after payroll close',
          justification: 'Overtime hours were submitted after the cut-off.',
          tierName: 'Tier 3 — CEO / Owner',
          submittedAt: DateTime.now().subtract(const Duration(hours: 3)),
          highRisk: true,
        ),
      ],
    );
  }

  @override
  Future<ApprovalQueue> loadQueue() async => _queue;

  @override
  Future<ApprovalChallenge> challengeFor(String requestId) async =>
      const ApprovalChallenge(
        method: SecondFactorMethod.passkey,
        options: {'challenge': 'mock'},
      );

  @override
  Future<void> approve({
    required String requestId,
    Map<String, dynamic>? assertion,
    Map<String, dynamic>? signaturePayload,
  }) async {
    _remove(requestId);
  }

  @override
  Future<void> reject(String requestId) async => _remove(requestId);

  void _remove(String requestId) {
    _queue = ApprovalQueue(
      available: _queue.available,
      requests: _queue.requests.where((r) => r.id != requestId).toList(),
    );
  }
}
