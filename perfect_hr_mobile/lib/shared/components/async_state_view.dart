import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/errors/app_failure.dart';
import 'ux_states.dart';

/// Renders an [AsyncValue] through the six global UX states.
///
/// Spec: Screen & Wireframe Blueprint §52, Instructions §24 and §45.
///
/// This is the glue that makes complete state handling the default rather than
/// something each screen must remember. A screen supplies only its loaded
/// content; loading, empty, error, offline and permission-denied are derived
/// from the failure type via [AppFailure.uxState].
///
/// ```dart
/// AsyncStateView<List<LeaveRequest>>(
///   value: ref.watch(myLeaveRequestsProvider),
///   onRetry: () => ref.invalidate(myLeaveRequestsProvider),
///   isEmpty: (requests) => requests.isEmpty,
///   emptyTitle: 'No pending HR requests',
///   emptyMessage: "You're all caught up.",
///   builder: (requests) => LeaveRequestList(requests: requests),
/// )
/// ```
class AsyncStateView<T> extends StatelessWidget {
  const AsyncStateView({
    required this.value,
    required this.builder,
    this.onRetry,
    this.isEmpty,
    this.emptyTitle = 'Nothing here yet',
    this.emptyMessage,
    this.emptyActionLabel,
    this.onEmptyAction,
    this.loadingLabel,
    this.loadingCardCount = 3,
    this.loading,
    this.onGoBack,
    super.key,
  });

  final AsyncValue<T> value;
  final Widget Function(T data) builder;

  /// Invoked by the error and offline states. Typically `ref.invalidate(...)`.
  final VoidCallback? onRetry;

  /// Determines whether loaded data should render as the empty state.
  final bool Function(T data)? isEmpty;

  final String emptyTitle;
  final String? emptyMessage;
  final String? emptyActionLabel;
  final VoidCallback? onEmptyAction;

  final String? loadingLabel;
  final int loadingCardCount;

  /// Overrides the default skeleton, for screens with a distinctive layout.
  final Widget? loading;

  final VoidCallback? onGoBack;

  @override
  Widget build(BuildContext context) {
    return value.when(
      skipLoadingOnRefresh: true,
      skipLoadingOnReload: true,
      loading: () =>
          loading ??
          AppLoadingState(cardCount: loadingCardCount, label: loadingLabel),
      error: (error, stackTrace) => _buildFailure(asAppFailure(error, stackTrace)),
      data: (data) {
        if (isEmpty?.call(data) ?? false) {
          return AppEmptyState(
            title: emptyTitle,
            message: emptyMessage,
            actionLabel: emptyActionLabel,
            onAction: onEmptyAction,
          );
        }
        return builder(data);
      },
    );
  }

  Widget _buildFailure(AppFailure failure) {
    return switch (failure.uxState) {
      FailureUxState.offline => AppOfflineState(
          message: failure.userMessage,
          onRetry: failure.isRetryable ? onRetry : null,
        ),
      FailureUxState.permissionDenied => AppPermissionDeniedState(
          message: failure.userMessage,
          onGoBack: onGoBack,
        ),
      FailureUxState.empty => AppEmptyState(
          title: emptyTitle,
          message: failure.userMessage,
          actionLabel: emptyActionLabel,
          onAction: onEmptyAction,
        ),
      FailureUxState.error => AppErrorState(
          message: failure.userMessage,
          onRetry: failure.isRetryable ? onRetry : null,
        ),
    };
  }
}
