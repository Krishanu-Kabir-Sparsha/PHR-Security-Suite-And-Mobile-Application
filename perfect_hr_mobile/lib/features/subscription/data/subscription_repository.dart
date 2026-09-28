import '../../../core/networking/api_client.dart';
import '../domain/workspace_subscription.dart';

/// What came back from `GET /me/subscription`.
///
/// "Not available" is a first-class answer rather than a null, because two very
/// different situations both produce no plan and they lead to different
/// screens: an on-premise install has no subscription to show, while a failed
/// read means we could not find out. Only the first justifies hiding the
/// section outright.
class SubscriptionResult {
  const SubscriptionResult({required this.available, this.subscription});

  /// Whether this deployment has a subscription at all.
  final bool available;

  final WorkspaceSubscription? subscription;

  static const SubscriptionResult none = SubscriptionResult(available: false);
}

abstract interface class SubscriptionRepository {
  /// Refused server-side with 403 for anyone who does not administer the
  /// workspace, so calling it is a request rather than a grant.
  Future<SubscriptionResult> load();
}

/// `GET /me/subscription`
///
/// ```json
/// {
///   "available": true,
///   "subscription": {
///     "plan_name": "Enterprise", "health": "active",
///     "headline": "Your subscription is active.",
///     "price": {"display": "৳12,000.00 / month"},
///     "usage": {"users": {"used": 18, "limit": 100, "unit": "users"}}
///   }
/// }
/// ```
///
/// Unlike the capabilities read, a failure here **is** propagated. This screen
/// exists only to answer a question, so a plan card quietly showing nothing
/// would be worse than an error: the administrator would conclude their plan
/// had lapsed. The one thing that must never happen is a wrong answer
/// delivered confidently.
class ApiSubscriptionRepository implements SubscriptionRepository {
  ApiSubscriptionRepository({required ApiClient client}) : _client = client;

  final ApiClient _client;

  @override
  Future<SubscriptionResult> load() async {
    final body = await _client.get<Map<String, dynamic>>('/me/subscription');
    final available = body['available'] as bool? ?? false;
    final raw = body['subscription'];
    return SubscriptionResult(
      available: available,
      subscription: raw is Map
          ? WorkspaceSubscription.fromJson(raw.cast<String, Object?>())
          : null,
    );
  }
}

/// A healthy Enterprise plan, for development against a server without the
/// endpoint. Deliberately not near any limit: a mock that is permanently amber
/// teaches the wrong thing about what the warning means.
class MockSubscriptionRepository implements SubscriptionRepository {
  const MockSubscriptionRepository({this.latency = Duration.zero});

  final Duration latency;

  @override
  Future<SubscriptionResult> load() async {
    await Future<void>.delayed(latency);
    return const SubscriptionResult(
      available: true,
      subscription: WorkspaceSubscription(
        health: SubscriptionHealth.active,
        headline: 'Your subscription is active.',
        planName: 'Enterprise',
        planLabel: 'Annual',
        reference: 'SUB-00017',
        statusLabel: 'Active',
        price: SubscriptionPrice(display: '৳12,000.00 / month'),
        startedOn: '2026-01-01',
        renewsOn: '2027-01-01',
        daysLeft: 97,
        users: QuotaUsage(used: 18, limit: 100, unit: 'users', ratio: 0.18),
        storage: QuotaUsage(used: 4.2, limit: 50, unit: 'GB', ratio: 0.084),
        apps: ['Attendances', 'Employees', 'Payroll', 'Time Off'],
        syncedAt: '2026-09-20T10:00:00',
      ),
    );
  }
}
