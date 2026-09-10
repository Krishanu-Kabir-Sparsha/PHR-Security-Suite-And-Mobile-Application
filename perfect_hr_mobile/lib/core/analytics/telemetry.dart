import 'dart:developer' as developer;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config/app_config.dart';

/// Product events tracked by the mobile app.
///
/// Spec: UI-UX Specification §59, Instructions §27.
///
/// A closed enum rather than free-text names, so the event taxonomy stays
/// analysable and a typo cannot silently create a parallel event stream.
enum AnalyticsEvent {
  appOpened('app_opened'),
  signInSucceeded('sign_in_succeeded'),
  signInFailed('sign_in_failed'),
  signedOut('signed_out'),
  attendanceCheckIn('attendance_check_in'),
  attendanceCheckOut('attendance_check_out'),
  attendanceCorrectionSubmitted('attendance_correction_submitted'),
  leaveApplicationSubmitted('leave_application_submitted'),
  requestCreated('request_created'),
  approvalDecided('approval_decided'),
  payslipViewed('payslip_viewed'),
  aiQuerySent('ai_query_sent'),
  aiRecommendationViewed('ai_recommendation_viewed'),
  aiRecommendationAccepted('ai_recommendation_accepted'),
  aiExplainabilityOpened('ai_explainability_opened'),
  learningStarted('learning_started'),
  notificationOpened('notification_opened'),
  screenViewed('screen_viewed');

  const AnalyticsEvent(this.wireName);

  /// Snake_case name sent to the analytics backend.
  ///
  /// Called `wireName` rather than `name` because every Dart enum already has
  /// a `name` getter from the `EnumName` extension; declaring a field with the
  /// same name would shadow it and make `event.name` ambiguous to read.
  final String wireName;
}

/// Telemetry sink.
abstract interface class Telemetry {
  void track(AnalyticsEvent event, {Map<String, Object?> parameters});

  /// Screen view, keyed by Blueprint screen ID (Instructions §20), so product
  /// analytics reads against the specification.
  void trackScreen(String screenId);

  /// Non-fatal error for crash reporting. Pass only the diagnostic string from
  /// [AppFailure.technical] — never a response body.
  void recordError(Object error, StackTrace? stackTrace, {String? reason});
}

/// Rejects parameters that could carry personal or sensitive HR data.
///
/// Instructions §27 forbids sending sensitive HR data to analytics
/// unnecessarily. Enforcing it at the sink rather than at every call site
/// matters because analytics calls get added quickly and reviewed lightly, and
/// a leak here is silent — nothing in the UI reveals that a salary figure was
/// attached to an event.
///
/// The guard is a denylist on parameter *keys* plus a value-shape check for
/// things that look like identifiers regardless of key name.
abstract final class TelemetryGuard {
  static const Set<String> _forbiddenKeyFragments = {
    'name',
    'email',
    'phone',
    'mobile',
    'address',
    'salary',
    'wage',
    'pay',
    'compensation',
    'bank',
    'account',
    'iban',
    'nid',
    'national_id',
    'passport',
    'tin',
    'tax',
    'dob',
    'birth',
    'password',
    'token',
    'secret',
    'otp',
    'reason',
    'comment',
    'note',
    'message',
    'query',
    'answer',
    'diagnosis',
    'medical',
  };

  /// Keys explicitly allowed despite matching a fragment above.
  static const Set<String> _allowlist = {
    // Categorical, non-identifying, and needed for the AI adoption metrics in
    // UI-UX §60: the *category* of an AI query, never its text.
    'query_category',
    'payment_method_type',
  };

  /// Returns the parameters safe to send, dropping the rest.
  ///
  /// Dropping rather than throwing is deliberate: an over-eager analytics call
  /// should lose a dimension, not crash a check-in.
  static Map<String, Object?> sanitise(Map<String, Object?> parameters) {
    final safe = <String, Object?>{};
    parameters.forEach((key, value) {
      if (!isSafeKey(key)) return;
      if (!isSafeValue(value)) return;
      safe[key] = value;
    });
    return safe;
  }

  static bool isSafeKey(String key) {
    final lower = key.toLowerCase();
    if (_allowlist.contains(lower)) return true;
    return !_forbiddenKeyFragments.any(lower.contains);
  }

  /// Only primitives, and only short strings. A long string is almost always
  /// free text — a leave reason, an AI prompt, a comment — and free text is
  /// where personal data hides.
  static bool isSafeValue(Object? value) {
    return switch (value) {
      null => true,
      bool() => true,
      num() => true,
      String s => s.length <= 40,
      _ => false,
    };
  }
}

/// Development sink: logs sanitised events locally, sends nothing.
class DebugTelemetry implements Telemetry {
  const DebugTelemetry();

  @override
  void track(AnalyticsEvent event, {Map<String, Object?> parameters = const {}}) {
    final safe = TelemetryGuard.sanitise(parameters);
    developer.log('${event.wireName} $safe', name: 'PerfectHR.telemetry');
  }

  @override
  void trackScreen(String screenId) {
    developer.log('screen_viewed $screenId', name: 'PerfectHR.telemetry');
  }

  @override
  void recordError(Object error, StackTrace? stackTrace, {String? reason}) {
    developer.log(
      'error ${reason ?? ''} $error',
      name: 'PerfectHR.telemetry',
      stackTrace: stackTrace,
    );
  }
}

/// Discards everything. Used until a backend sink is wired.
class NoopTelemetry implements Telemetry {
  const NoopTelemetry();

  @override
  void track(
    AnalyticsEvent event, {
    Map<String, Object?> parameters = const {},
  }) {}

  @override
  void trackScreen(String screenId) {}

  @override
  void recordError(Object error, StackTrace? stackTrace, {String? reason}) {}
}

/// PENDING: the production sink.
///
/// Firebase Crashlytics and product analytics are declared in `pubspec.yaml`
/// but not yet initialised, because doing so requires `google-services.json`
/// and `GoogleService-Info.plist` from the Perfect HR Firebase project, which
/// are not available (Project State Q9). Until then dev builds log locally and
/// other flavours discard, so no event is silently lost to a misconfigured
/// backend and no HR data leaves the device.
final telemetryProvider = Provider<Telemetry>((ref) {
  return AppConfig.current.allowsVerboseLogging
      ? const DebugTelemetry()
      : const NoopTelemetry();
});
