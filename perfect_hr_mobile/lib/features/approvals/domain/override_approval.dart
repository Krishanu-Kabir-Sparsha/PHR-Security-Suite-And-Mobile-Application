import 'package:flutter/foundation.dart';
import '../../../core/utilities/server_time.dart';

/// An override waiting on this person, at their tier, right now.
///
/// "At their tier" is doing real work: a Tier 3 approver must not see a request
/// still waiting on Tier 1. The server decides that by asking the record
/// itself, so the tier order cannot drift between the web and the phone.
@immutable
class OverrideApproval {
  const OverrideApproval({
    required this.id,
    required this.reference,
    required this.target,
    required this.requestedBy,
    required this.contextRef,
    this.justification,
    this.reason,
    this.tierName,
    this.submittedAt,
    this.highRisk = false,
  });

  final String id;

  /// Human reference, e.g. `OVR-2026-0041`.
  final String reference;

  /// What would change — the record this override unlocks.
  final String target;

  final String requestedBy;

  /// What the assertion must be bound to: `override.request,<id>`.
  ///
  /// Comes from the server and is echoed back untouched. Never derived here: it
  /// is the binding between a fingerprint and one specific override, and a
  /// client that computed it could bind a confirmation to the wrong thing.
  final String contextRef;

  final String? justification;
  final String? reason;

  /// Which approval step this is, e.g. "Tier 3 — CEO / Owner".
  final String? tierName;

  final DateTime? submittedAt;
  final bool highRisk;

  factory OverrideApproval.fromJson(Map<String, Object?> json) {
    return OverrideApproval(
      id: '${json['id']}',
      reference: '${json['reference'] ?? ''}',
      target: '${json['target'] ?? ''}',
      requestedBy: '${json['requested_by'] ?? ''}',
      contextRef: '${json['context_ref'] ?? ''}',
      justification: json['justification'] as String?,
      reason: json['reason'] as String?,
      tierName: json['tier_name'] as String?,
      submittedAt: parseServerTime(json['submitted_at']),
      highRisk: json['high_risk'] as bool? ?? false,
    );
  }
}

/// The approvals surface, and whether it exists at all here.
///
/// [available] is false when the override module is not installed. Distinct
/// from an empty list on purpose: one means "nothing is waiting on you", the
/// other means "this deployment has no override workflow", and the app hides
/// the entry entirely rather than offering a queue that can never fill.
@immutable
class ApprovalQueue {
  const ApprovalQueue({required this.available, this.requests = const []});

  final bool available;
  final List<OverrideApproval> requests;

  bool get isEmpty => requests.isEmpty;

  static const ApprovalQueue unavailable = ApprovalQueue(available: false);

  factory ApprovalQueue.fromJson(Map<String, Object?> json) {
    final raw = json['requests'];
    return ApprovalQueue(
      available: json['available'] as bool? ?? false,
      requests: raw is List
          ? raw
              .whereType<Map<Object?, Object?>>()
              .map((r) => OverrideApproval.fromJson(r.cast<String, Object?>()))
              .toList()
          : const [],
    );
  }
}
