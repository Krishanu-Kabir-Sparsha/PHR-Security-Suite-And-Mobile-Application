import 'package:flutter/foundation.dart';

import '../../../core/utilities/server_time.dart';

/// An employee asking a manager to accept a check-in made away from work.
///
/// This exists because the location rule, under ENFORCE, refuses the punch
/// outright. A rule with no way out would make the first genuine site visit a
/// lost day's pay, and that pressure lands on the employee rather than on
/// whoever drew the radius.
///
/// What it is **not** is self-service. Nothing is recorded until somebody other
/// than the subject agrees. The earlier design let the employee type a sentence
/// and be let through, which made the radius a prompt rather than a control.
enum OffsiteRequestState {
  pending('pending'),
  approved('approved'),
  rejected('rejected'),

  /// A state this build does not know. Rendered as "sent" rather than as an
  /// error: a newer server adding a state must not make an older app tell
  /// somebody their request has failed.
  unknown('unknown');

  const OffsiteRequestState(this.wireValue);

  final String wireValue;

  static OffsiteRequestState fromWire(String? value) {
    for (final state in OffsiteRequestState.values) {
      if (state.wireValue == value) return state;
    }
    return OffsiteRequestState.unknown;
  }

  bool get isOpen => this == OffsiteRequestState.pending;
}

@immutable
class OffsiteRequest {
  const OffsiteRequest({
    required this.id,
    required this.state,
    this.requestedAt,
    this.reason,
    this.distanceMetres,
    this.locationName,
    this.decidedAt,
    this.manager,
  });

  final String id;
  final OffsiteRequestState state;

  /// When the employee tried to check in.
  ///
  /// Shown rather than the submission time, because this is what gets recorded
  /// as the check-in if a manager approves. An employee who sees the approval
  /// time here would reasonably expect their day to start then.
  final DateTime? requestedAt;

  final String? reason;
  final int? distanceMetres;
  final String? locationName;
  final DateTime? decidedAt;

  /// Who is expected to decide. Null where the employee record names no
  /// manager, in which case HR decides and the app says so.
  final String? manager;

  factory OffsiteRequest.fromJson(Map<String, Object?> json) => OffsiteRequest(
        id: '${json['id'] ?? ''}',
        state: OffsiteRequestState.fromWire(json['state'] as String?),
        requestedAt: parseServerTime(json['requested_at']),
        reason: json['reason'] as String?,
        distanceMetres: (json['distance_m'] as num?)?.toInt(),
        locationName: json['location_name'] as String?,
        decidedAt: parseServerTime(json['decided_at']),
        manager: json['manager'] as String?,
      );

  Map<String, Object?> toJson() => {
        'id': id,
        'state': state.wireValue,
        'requested_at': serialiseInstant(requestedAt),
        'reason': reason,
        'distance_m': distanceMetres,
        'location_name': locationName,
        'decided_at': serialiseInstant(decidedAt),
        'manager': manager,
      };
}
