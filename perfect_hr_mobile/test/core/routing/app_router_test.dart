import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:perfect_hr_mobile/core/config/app_config.dart';
import 'package:perfect_hr_mobile/core/constants/screen_ids.dart';
import 'package:perfect_hr_mobile/core/routing/app_router.dart';
import 'package:perfect_hr_mobile/core/routing/app_routes.dart';
import 'package:perfect_hr_mobile/core/session/session_controller.dart';
import 'package:perfect_hr_mobile/core/session/user_role.dart';

/// Guards the router construction for every role.
///
/// Route names are Blueprint screen IDs (Instructions §20) and GoRouter
/// requires them to be unique within a router instance. Because the router is
/// built per role from that role's navigation profile, a screen ID reused
/// across a branch root and another route only fails for that one role — which
/// is easy to miss by inspection. This test builds every role's router.

/// Collects every route name in a router's configuration.
List<String> _routeNames(List<RouteBase> routes) {
  final names = <String>[];
  void walk(List<RouteBase> current) {
    for (final route in current) {
      if (route is StatefulShellRoute) {
        for (final branch in route.branches) {
          walk(branch.routes);
        }
        continue;
      }
      if (route is GoRoute && route.name != null) {
        names.add(route.name!);
      }
      walk(route.routes);
    }
  }

  walk(routes);
  return names;
}

ProviderContainer _containerFor(UserRole? role) {
  final container = ProviderContainer();
  if (role != null) {
    container.read(sessionControllerProvider.notifier).devSwitchRole(role);
  }
  return container;
}

void main() {
  setUpAll(() {
    // Dev flavour, so devSwitchRole is permitted in tests.
    AppConfig.initialise(flavorName: 'dev');
  });

  group('router construction', () {
    test('builds without error for every role', () {
      for (final role in UserRole.values) {
        final container = _containerFor(role);
        addTearDown(container.dispose);
        expect(
          () => container.read(routerProvider),
          returnsNormally,
          reason: 'router must build for ${role.name}',
        );
      }
    });

    test('builds for an unauthenticated session', () {
      final container = _containerFor(null);
      addTearDown(container.dispose);
      expect(() => container.read(routerProvider), returnsNormally);
    });

    test('route names are unique within every role\'s router', () {
      for (final role in UserRole.values) {
        final container = _containerFor(role);
        addTearDown(container.dispose);

        final names = _routeNames(
          container.read(routerProvider).configuration.routes,
        );
        final duplicates = <String>[];
        final seen = <String>{};
        for (final name in names) {
          if (!seen.add(name)) duplicates.add(name);
        }

        expect(
          duplicates,
          isEmpty,
          reason: 'duplicate route names for ${role.name}: $duplicates',
        );
      }
    });

    test('every role can reach the AI assistant and Home', () {
      for (final role in UserRole.values) {
        final container = _containerFor(role);
        addTearDown(container.dispose);

        final names = _routeNames(
          container.read(routerProvider).configuration.routes,
        );
        expect(names, contains(ScreenIds.aiHome), reason: role.name);
        expect(names, contains(ScreenIds.more), reason: role.name);
      }
    });
  });

  group('initial location', () {
    test('unauthenticated sessions start at AUTH-01', () {
      final container = _containerFor(null);
      addTearDown(container.dispose);

      final router = container.read(routerProvider);
      expect(
        router.routeInformationProvider.value.uri.path,
        AppRoutes.welcome,
      );
    });

    test('authenticated sessions start at Home', () {
      final container = _containerFor(UserRole.employee);
      addTearDown(container.dispose);

      final router = container.read(routerProvider);
      expect(
        router.routeInformationProvider.value.uri.path,
        AppRoutes.home,
      );
    });
  });

  group('session-driven rebuild', () {
    test('router is rebuilt when the role changes', () {
      final container = _containerFor(UserRole.employee);
      addTearDown(container.dispose);

      final first = container.read(routerProvider);
      container
          .read(sessionControllerProvider.notifier)
          .devSwitchRole(UserRole.manager);
      final second = container.read(routerProvider);

      expect(second, isNot(same(first)));
    });

    test('router is not rebuilt when the role is unchanged', () {
      final container = _containerFor(UserRole.employee);
      addTearDown(container.dispose);

      final first = container.read(routerProvider);
      container
          .read(sessionControllerProvider.notifier)
          .devSwitchRole(UserRole.employee);
      final second = container.read(routerProvider);

      expect(second, same(first));
    });
  });
}
