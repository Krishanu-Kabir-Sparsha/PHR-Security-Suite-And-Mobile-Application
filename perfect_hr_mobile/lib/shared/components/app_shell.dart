import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/routing/nav_profile.dart';
import '../extensions/theme_context.dart';

/// Role-aware application shell.
///
/// Spec: UI-UX Specification §5, Functional Blueprint §3, Instructions §11.
/// The navigation frame is visually identical for every role; only the
/// destinations behind it change. Each branch keeps its own navigation stack,
/// so switching tabs and returning preserves where the user was.
class AppShell extends StatelessWidget {
  const AppShell({
    required this.profile,
    required this.navigationShell,
    super.key,
  });

  final NavProfile profile;
  final StatefulNavigationShell navigationShell;

  void _onDestinationSelected(int index) {
    // Tapping the active destination pops that branch back to its root,
    // which is the expected mobile idiom for returning to a section home.
    navigationShell.goBranch(
      index,
      initialLocation: index == navigationShell.currentIndex,
    );
  }

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;

    return Scaffold(
      body: navigationShell,
      bottomNavigationBar: DecoratedBox(
        decoration: BoxDecoration(
          border: Border(top: BorderSide(color: palette.border)),
        ),
        child: NavigationBar(
          selectedIndex: navigationShell.currentIndex,
          onDestinationSelected: _onDestinationSelected,
          destinations: [
            for (final destination in profile.destinations)
              NavigationDestination(
                icon: Icon(destination.icon),
                selectedIcon: Icon(destination.selectedIcon),
                label: destination.label,
                tooltip: destination.semanticLabel,
              ),
          ],
        ),
      ),
    );
  }
}

/// Standard dashboard header — UI-UX §11.
///
/// `Profile | Greeting | Notifications` for home screens. Detail screens use
/// the themed [AppBar] with a back affordance instead.
class AppDashboardHeader extends StatelessWidget {
  const AppDashboardHeader({
    required this.greeting,
    this.subtitle,
    this.avatarUrl,
    this.notificationCount = 0,
    this.onAvatarTap,
    this.onNotificationsTap,
    super.key,
  });

  final String greeting;
  final String? subtitle;
  final String? avatarUrl;
  final int notificationCount;
  final VoidCallback? onAvatarTap;
  final VoidCallback? onNotificationsTap;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;

    return Semantics(
      header: true,
      child: Row(
        children: [
          if (avatarUrl != null || onAvatarTap != null)
            Padding(
              padding: const EdgeInsets.only(right: 12),
              child: GestureDetector(
                onTap: onAvatarTap,
                child: CircleAvatar(
                  radius: 22,
                  backgroundColor: palette.brandContainer,
                  foregroundImage:
                      avatarUrl == null ? null : NetworkImage(avatarUrl!),
                  child: Icon(
                    Icons.person_outline,
                    color: palette.onBrandContainer,
                  ),
                ),
              ),
            ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(greeting, style: context.text.titleLarge),
                if (subtitle != null)
                  Text(
                    subtitle!,
                    style: context.text.bodySmall,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
              ],
            ),
          ),
          _NotificationButton(
            count: notificationCount,
            onTap: onNotificationsTap,
          ),
        ],
      ),
    );
  }
}

class _NotificationButton extends StatelessWidget {
  const _NotificationButton({required this.count, this.onTap});

  final int count;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final label = count == 0
        ? 'Notifications'
        : 'Notifications, $count unread';

    return IconButton(
      onPressed: onTap,
      tooltip: label,
      icon: Badge(
        isLabelVisible: count > 0,
        backgroundColor: palette.danger,
        label: Text(count > 99 ? '99+' : '$count'),
        child: const Icon(Icons.notifications_outlined),
      ),
    );
  }
}
