/// The workspace's own Perfect HR plan, as an administrator reads it.
///
/// Everything here describes the *employer's* relationship with Perfect HR —
/// what they pay, when it renews, how close they are to their limits. None of
/// it is about the person holding the phone, which is why the server refuses
/// the whole payload to anyone who does not administer the workspace.
library;

import 'package:flutter/foundation.dart';

/// How the service is doing, in one word the UI styles on.
///
/// Severity order matters: a suspended trial reports as [suspended], not
/// [trial]. Telling somebody their workspace is fine while their staff cannot
/// sign in is the single worst thing this screen could do.
enum SubscriptionHealth {
  active('active'),
  trial('trial'),
  renewing('renewing'),
  setup('setup'),
  suspended('suspended'),
  ended('ended'),

  /// A server that sent a word this build does not know.
  ///
  /// Treated as informational rather than alarming: a newer server inventing a
  /// state must not make an older app shout about it.
  unknown('unknown');

  const SubscriptionHealth(this.wireValue);

  final String wireValue;

  static SubscriptionHealth fromWire(String? value) {
    for (final health in SubscriptionHealth.values) {
      if (health.wireValue == value) return health;
    }
    return SubscriptionHealth.unknown;
  }

  /// Whether this state needs the administrator to do something.
  ///
  /// Drives the colour of the header, so it is deliberately narrow: an amber
  /// banner that is up every day is one nobody reads.
  bool get needsAttention =>
      this == SubscriptionHealth.suspended || this == SubscriptionHealth.ended;
}

/// One usage line: how much is used, how much the plan allows.
@immutable
class QuotaUsage {
  const QuotaUsage({
    required this.used,
    required this.unit,
    this.limit,
    this.unlimited = false,
    this.ratio,
    this.nearLimit = false,
  });

  /// Measured live in the tenant, never read from the plan snapshot — which
  /// would report provisioning-day figures forever.
  final double used;

  /// Null when the plan sets no cap.
  final double? limit;

  /// `users` or `GB`.
  final String unit;

  final bool unlimited;

  /// Already clamped to 1.0 by the server, so a company over its limit gets a
  /// full bar rather than one that overflows its track.
  final double? ratio;

  /// Advisory only. **Nothing in Perfect HR blocks work on a quota.** A company
  /// that could not record attendance because it was near a storage limit would
  /// have been failed by its software, not by its plan.
  final bool nearLimit;

  /// "18 of 100 users", or "2.4 GB used" where the plan sets no cap.
  String get display {
    final usedText = _number(used);
    if (unlimited || limit == null) {
      return unit == 'users' ? '$usedText users' : '$usedText $unit used';
    }
    return '$usedText of ${_number(limit!)} $unit';
  }

  static String _number(double value) =>
      value == value.roundToDouble() ? value.round().toString() : value.toStringAsFixed(1);

  factory QuotaUsage.fromJson(Map<String, Object?> json) => QuotaUsage(
        used: (json['used'] as num?)?.toDouble() ?? 0,
        limit: (json['limit'] as num?)?.toDouble(),
        unit: json['unit'] as String? ?? '',
        unlimited: json['unlimited'] as bool? ?? false,
        ratio: (json['ratio'] as num?)?.toDouble(),
        nearLimit: json['near_limit'] as bool? ?? false,
      );
}

/// What the plan costs, formatted by the server.
///
/// The currency here is a symbol rather than a code, and the phone has no
/// locale rule that turns a bare symbol and a double into the string a
/// Bangladeshi customer expects. So the formatting decision is made once, on
/// the server, and the app prints what it is given.
@immutable
class SubscriptionPrice {
  const SubscriptionPrice({required this.display, this.amount, this.currency});

  final String display;
  final double? amount;
  final String? currency;

  factory SubscriptionPrice.fromJson(Map<String, Object?> json) =>
      SubscriptionPrice(
        display: json['display'] as String? ?? '',
        amount: (json['amount'] as num?)?.toDouble(),
        currency: json['currency'] as String?,
      );
}

@immutable
class WorkspaceSubscription {
  const WorkspaceSubscription({
    required this.health,
    required this.headline,
    this.planName,
    this.planLabel,
    this.reference,
    this.isTrial = false,
    this.statusLabel,
    this.price,
    this.startedOn,
    this.renewsOn,
    this.daysLeft,
    this.users,
    this.storage,
    this.apps = const [],
    this.manageUrl,
    this.upgradeUrl,
    this.syncedAt,
  });

  final SubscriptionHealth health;

  /// The sentence the screen prints, composed by the server.
  ///
  /// Sent alongside [health] so the phone never has to infer severity from
  /// English, and never has to assemble the sentence itself — which would put
  /// the same wording in two places and let them drift.
  final String headline;

  final String? planName;
  final String? planLabel;
  final String? reference;
  final bool isTrial;
  final String? statusLabel;
  final SubscriptionPrice? price;

  final String? startedOn;

  /// The trial's end date on a trial, the next invoice date on a paid plan.
  /// The server picks which, because reading the invoice date on a trial would
  /// promise months that are not there.
  final String? renewsOn;
  final int? daysLeft;

  final QuotaUsage? users;
  final QuotaUsage? storage;

  /// Installed applications by their display names — "Attendances", never
  /// `hr_attendance`. This answers "does our plan cover what we need?", and a
  /// module name answers a different question than the one asked.
  final List<String> apps;

  /// Deep links back to the customer portal. Null where the server did not
  /// send them, and then the buttons are simply not drawn.
  final String? manageUrl;
  final String? upgradeUrl;

  /// When the plan facts were last written into this workspace.
  ///
  /// Shown because these come from a snapshot rather than a live call: saying
  /// when a figure was last confirmed is the difference between a stale number
  /// and a wrong one.
  final String? syncedAt;

  factory WorkspaceSubscription.fromJson(Map<String, Object?> json) {
    final rawUsage = json['usage'];
    final usage = rawUsage is Map ? rawUsage.cast<String, Object?>() : const {};
    final rawPrice = json['price'];
    final rawApps = json['apps'];

    QuotaUsage? quota(String key) {
      final value = usage[key];
      return value is Map ? QuotaUsage.fromJson(value.cast<String, Object?>()) : null;
    }

    return WorkspaceSubscription(
      health: SubscriptionHealth.fromWire(json['health'] as String?),
      headline: json['headline'] as String? ?? '',
      planName: json['plan_name'] as String?,
      planLabel: json['plan_label'] as String?,
      reference: json['reference'] as String?,
      isTrial: json['is_trial'] as bool? ?? false,
      statusLabel: json['status_label'] as String?,
      price: rawPrice is Map
          ? SubscriptionPrice.fromJson(rawPrice.cast<String, Object?>())
          : null,
      startedOn: json['started_on'] as String?,
      renewsOn: json['renews_on'] as String?,
      daysLeft: (json['days_left'] as num?)?.toInt(),
      users: quota('users'),
      storage: quota('storage'),
      apps: rawApps is List ? rawApps.map((a) => '$a').toList() : const [],
      manageUrl: json['manage_url'] as String?,
      upgradeUrl: json['upgrade_url'] as String?,
      syncedAt: json['synced_at'] as String?,
    );
  }
}
