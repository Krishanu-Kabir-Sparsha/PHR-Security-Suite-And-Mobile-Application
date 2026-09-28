import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/data/data_providers.dart';
import '../../../core/networking/api_client.dart';
import '../data/subscription_repository.dart';

final subscriptionRepositoryProvider = Provider<SubscriptionRepository>((ref) {
  if (ref.watch(dataSourceModeProvider) == DataSourceMode.mock) {
    return const MockSubscriptionRepository();
  }
  return ApiSubscriptionRepository(client: ref.watch(apiClientProvider));
});

/// The workspace's plan and usage.
///
/// `autoDispose` on purpose. This is read from one screen that an administrator
/// opens occasionally, and the usage figures inside it are measured live on the
/// server — holding the result after the screen closes would only guarantee
/// that the next visit opens on stale numbers.
final workspaceSubscriptionProvider =
    FutureProvider.autoDispose<SubscriptionResult>((ref) {
  return ref.watch(subscriptionRepositoryProvider).load();
});
