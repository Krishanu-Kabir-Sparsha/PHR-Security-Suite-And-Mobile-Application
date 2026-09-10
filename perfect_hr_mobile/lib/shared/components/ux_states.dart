import 'package:flutter/material.dart';

import '../../core/theme/app_dimensions.dart';
import '../../core/theme/app_motion.dart';
import '../extensions/theme_context.dart';

/// The six global UX states every major screen must define.
///
/// Spec: Screen & Wireframe Blueprint §52, UI-UX Specification §46–48,
/// Instructions §24 and §45. A feature is not complete until loading, empty,
/// error, offline and permission-denied are all handled.
///
/// State 2 (Loaded) is the screen's own content and has no widget here.

// ---------------------------------------------------------------------------
// State 1 — Loading
// ---------------------------------------------------------------------------

/// Animated skeleton block. Blueprint §52 requires skeletons rather than
/// blank screens or bare spinners.
class AppSkeleton extends StatefulWidget {
  const AppSkeleton({
    this.width,
    this.height = 16,
    this.radius = AppRadius.xs,
    super.key,
  });

  /// A skeleton line of text at the given width fraction of its parent.
  const AppSkeleton.line({double height = 14, Key? key})
      : this(height: height, key: key);

  /// A skeleton block sized for a card.
  const AppSkeleton.card({Key? key})
      : this(height: 120, radius: AppRadius.md, key: key);

  final double? width;
  final double height;
  final double radius;

  @override
  State<AppSkeleton> createState() => _AppSkeletonState();
}

class _AppSkeletonState extends State<AppSkeleton>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: AppMotion.shimmer,
  );

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // Honour the platform reduced-motion preference (Instructions §26).
    final reduce = MediaQuery.maybeDisableAnimationsOf(context) ?? false;
    if (reduce) {
      _controller.stop();
    } else if (!_controller.isAnimating) {
      _controller.repeat(reverse: true);
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    return ExcludeSemantics(
      child: AnimatedBuilder(
        animation: _controller,
        builder: (context, _) {
          return Container(
            width: widget.width,
            height: widget.height,
            decoration: BoxDecoration(
              color: Color.lerp(
                palette.skeletonBase,
                palette.skeletonHighlight,
                _controller.value,
              ),
              borderRadius: BorderRadius.circular(widget.radius),
            ),
          );
        },
      ),
    );
  }
}

/// Default loading state: a card-shaped skeleton stack.
class AppLoadingState extends StatelessWidget {
  const AppLoadingState({this.cardCount = 3, this.label, super.key});

  final int cardCount;

  /// Announced to screen readers, e.g. "Loading your attendance".
  final String? label;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      liveRegion: true,
      label: label ?? 'Loading',
      child: Padding(
        padding: AppSpacing.page,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const AppSkeleton(width: 160, height: 20),
            const SizedBox(height: AppSpacing.lg),
            for (var i = 0; i < cardCount; i++) ...[
              const AppSkeleton.card(),
              const SizedBox(height: AppSpacing.md),
            ],
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// States 3–6 — Empty / Error / Offline / Permission Restricted
// ---------------------------------------------------------------------------

/// Shared layout for the four message states.
class _MessageState extends StatelessWidget {
  const _MessageState({
    required this.icon,
    required this.iconColor,
    required this.iconBackground,
    required this.title,
    this.message,
    this.primaryLabel,
    this.onPrimary,
    this.secondaryLabel,
    this.onSecondary,
  });

  final IconData icon;
  final Color iconColor;
  final Color iconBackground;
  final String title;
  final String? message;
  final String? primaryLabel;
  final VoidCallback? onPrimary;
  final String? secondaryLabel;
  final VoidCallback? onSecondary;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.lg,
          vertical: AppSpacing.xl,
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              padding: const EdgeInsets.all(AppSpacing.md),
              decoration: BoxDecoration(
                color: iconBackground,
                shape: BoxShape.circle,
              ),
              child: Icon(icon, size: AppSizes.iconLg, color: iconColor),
            ),
            const SizedBox(height: AppSpacing.md),
            Text(
              title,
              style: context.text.titleMedium,
              textAlign: TextAlign.center,
            ),
            if (message != null) ...[
              const SizedBox(height: AppSpacing.xs),
              Text(
                message!,
                style: context.text.bodySmall,
                textAlign: TextAlign.center,
              ),
            ],
            if (onPrimary != null && primaryLabel != null) ...[
              const SizedBox(height: AppSpacing.lg),
              SizedBox(
                width: 220,
                child: FilledButton(
                  onPressed: onPrimary,
                  child: Text(primaryLabel!),
                ),
              ),
            ],
            if (onSecondary != null && secondaryLabel != null) ...[
              const SizedBox(height: AppSpacing.xs),
              TextButton(onPressed: onSecondary, child: Text(secondaryLabel!)),
            ],
          ],
        ),
      ),
    );
  }
}

/// State 3 — Empty.
///
/// UI-UX §46: never show a bare "No requests." Give the state a reassuring
/// title, a short explanation and, where it makes sense, a way forward.
class AppEmptyState extends StatelessWidget {
  const AppEmptyState({
    required this.title,
    this.message,
    this.icon = Icons.inbox_outlined,
    this.actionLabel,
    this.onAction,
    super.key,
  });

  final String title;
  final String? message;
  final IconData icon;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    return _MessageState(
      icon: icon,
      iconColor: palette.inkTertiary,
      iconBackground: palette.surfaceAlt,
      title: title,
      message: message,
      primaryLabel: actionLabel,
      onPrimary: onAction,
    );
  }
}

/// State 4 — Error.
///
/// Instructions §24: the message must already be user-safe. Never pass an
/// exception's `toString()` here.
class AppErrorState extends StatelessWidget {
  const AppErrorState({
    this.title = "Something went wrong",
    this.message = "We couldn't load this information.",
    this.onRetry,
    this.retryLabel = 'Try Again',
    super.key,
  });

  final String title;
  final String message;
  final VoidCallback? onRetry;
  final String retryLabel;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    return _MessageState(
      icon: Icons.error_outline,
      iconColor: palette.danger,
      iconBackground: palette.dangerContainer,
      title: title,
      message: message,
      primaryLabel: retryLabel,
      onPrimary: onRetry,
    );
  }
}

/// State 5 — Offline.
///
/// UI-UX §48: state plainly whether data is live or last synchronised, and
/// never present stale data as current.
class AppOfflineState extends StatelessWidget {
  const AppOfflineState({
    this.title = "You're offline",
    this.message = 'Showing your last synchronized data.',
    this.lastSyncedAt,
    this.onRetry,
    super.key,
  });

  final String title;
  final String message;
  final DateTime? lastSyncedAt;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final synced = lastSyncedAt;
    return _MessageState(
      icon: Icons.cloud_off_outlined,
      iconColor: palette.warning,
      iconBackground: palette.warningContainer,
      title: title,
      message: synced == null
          ? message
          : '$message\nLast synchronized ${_formatTime(synced)}.',
      primaryLabel: onRetry == null ? null : 'Try Again',
      onPrimary: onRetry,
    );
  }

  static String _formatTime(DateTime time) {
    final hour = time.hour % 12 == 0 ? 12 : time.hour % 12;
    final minute = time.minute.toString().padLeft(2, '0');
    final period = time.hour < 12 ? 'AM' : 'PM';
    return '$hour:$minute $period';
  }
}

/// Inline banner distinguishing cached data from live data (UI-UX §48).
/// Used above content that rendered from the local cache.
class AppStaleDataBanner extends StatelessWidget {
  const AppStaleDataBanner({required this.lastSyncedAt, this.onRefresh, super.key});

  final DateTime lastSyncedAt;
  final VoidCallback? onRefresh;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.sm,
        vertical: AppSpacing.xs,
      ),
      decoration: BoxDecoration(
        color: palette.warningContainer,
        borderRadius: AppRadius.controlRadius,
      ),
      child: Row(
        children: [
          Icon(
            Icons.history_outlined,
            size: AppSizes.iconSm,
            color: palette.onWarningContainer,
          ),
          const SizedBox(width: AppSpacing.xs),
          Expanded(
            child: Text(
              'Last synchronized ${AppOfflineState._formatTime(lastSyncedAt)}',
              style: context.text.bodySmall
                  ?.copyWith(color: palette.onWarningContainer),
            ),
          ),
          if (onRefresh != null)
            TextButton(
              onPressed: onRefresh,
              child: Text(
                'Refresh',
                style: context.text.labelMedium
                    ?.copyWith(color: palette.onWarningContainer),
              ),
            ),
        ],
      ),
    );
  }
}

/// State 6 — Permission Restricted.
///
/// Reached when the backend denies authorisation. Deliberately offers no
/// retry: retrying a denied request cannot succeed (Instructions §15).
class AppPermissionDeniedState extends StatelessWidget {
  const AppPermissionDeniedState({
    this.title = 'Restricted information',
    this.message = "You don't have permission to view this information.",
    this.onGoBack,
    super.key,
  });

  final String title;
  final String message;
  final VoidCallback? onGoBack;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    return _MessageState(
      icon: Icons.lock_outline,
      iconColor: palette.inkSecondary,
      iconBackground: palette.surfaceAlt,
      title: title,
      message: message,
      primaryLabel: onGoBack == null ? null : 'Go Back',
      onPrimary: onGoBack,
    );
  }
}
