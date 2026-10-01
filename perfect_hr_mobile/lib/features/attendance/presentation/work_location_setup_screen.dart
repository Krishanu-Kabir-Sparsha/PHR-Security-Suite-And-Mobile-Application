import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/errors/app_failure.dart';
import '../../../core/networking/api_client.dart';
import '../../../core/security/punch_location_service.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../../shared/extensions/theme_context.dart';
import '../../../shared/widgets/app_card.dart';
import '../data/work_location_repository.dart';

final workLocationRepositoryProvider = Provider<WorkLocationRepository>((ref) {
  return ApiWorkLocationRepository(client: ref.watch(apiClientProvider));
});

final workLocationsProvider =
    FutureProvider.autoDispose<WorkLocationList>((ref) {
  return ref.watch(workLocationRepositoryProvider).load();
});

/// **SET-04 — Work locations.**
///
/// Placing a geofence by standing in it.
///
/// A geofence is only as good as the point at its centre, and that point used
/// to have to be typed in as two decimal numbers. Nobody knows their office's
/// latitude; people find it by searching a map, which returns the coordinates
/// of a rooftop, a street entrance, or whatever the map provider decided the
/// address meant. A centre thirty metres out silently eats thirty metres of
/// every employee's allowance, and nobody finds out until somebody standing at
/// their own desk is refused.
///
/// Standing at the door with the handset that will be doing the checking in
/// removes every one of those translation steps: same hardware, same place,
/// same conditions.
class WorkLocationSetupScreen extends ConsumerStatefulWidget {
  const WorkLocationSetupScreen({super.key});

  @override
  ConsumerState<WorkLocationSetupScreen> createState() =>
      _WorkLocationSetupScreenState();
}

class _WorkLocationSetupScreenState
    extends ConsumerState<WorkLocationSetupScreen> {
  String? _busyId;

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(workLocationsProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Work locations')),
      body: RefreshIndicator(
        onRefresh: () async => ref.refresh(workLocationsProvider.future),
        child: async.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (error, _) => _Error(error: error),
          data: (list) => ListView(
            padding: const EdgeInsets.all(AppSpacing.md),
            children: [
              _Explainer(maxAccuracy: list.maxAccuracyMetres),
              const SizedBox(height: AppSpacing.md),
              if (list.locations.isEmpty)
                AppCard(
                  child: Text(
                    'No work locations have been created yet. Add them in '
                    'Perfect HR under Employees, Configuration, Work '
                    'Locations, then come back here to place them.',
                    style: context.text.bodyMedium,
                  ),
                )
              else
                for (final location in list.locations) ...[
                  _LocationCard(
                    location: location,
                    busy: _busyId == location.id,
                    onCapture: () => _capture(location, list.maxAccuracyMetres),
                  ),
                  const SizedBox(height: AppSpacing.sm),
                ],
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _capture(ManagedWorkLocation location, int maxAccuracy) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Place ${location.name} here?'),
        content: Text(
          location.placed
              ? 'This will move ${location.name} to where you are standing '
                  'now. Anybody who checks in near the old position will '
                  'start being refused.'
              : 'This will set ${location.name} to where you are standing '
                  'now. Make sure you are at the place people arrive at, not '
                  'in the car park across the road.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Use my position'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() => _busyId = location.id);
    try {
      final where = await ref.read(punchLocationServiceProvider).current();
      if (where == null) {
        if (!mounted) return;
        _say('Your phone did not report a position. Turn on location and try '
            'again from inside the grounds.');
        return;
      }

      await ref.read(workLocationRepositoryProvider).captureHere(
            locationId: location.id,
            latitude: where.latitude,
            longitude: where.longitude,
            accuracyMetres: where.accuracyMetres,
          );
      if (!mounted) return;
      ref.invalidate(workLocationsProvider);
      _say('${location.name} is now set to where you are standing.');
    } catch (error) {
      if (!mounted) return;
      // The server refuses a fix too vague to be a centre, and that refusal is
      // the useful one: it names the accuracy it got and the accuracy it
      // needs, so somebody can wait thirty seconds and try again.
      _say(error is AppFailure
          ? error.userMessage
          : 'That could not be saved. Please try again.');
    } finally {
      if (mounted) setState(() => _busyId = null);
    }
  }

  void _say(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), duration: const Duration(seconds: 5)),
    );
  }
}

class _Explainer extends StatelessWidget {
  const _Explainer({required this.maxAccuracy});

  final int maxAccuracy;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      background: context.palette.infoContainer,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Stand where people arrive',
            style: context.text.titleSmall
                ?.copyWith(color: context.palette.onInfoContainer),
          ),
          const SizedBox(height: AppSpacing.xxs),
          Text(
            'Go to the entrance, wait a few seconds for the signal to settle, '
            'then tap Set from here. Your phone has to be accurate to within '
            '$maxAccuracy metres or it will be refused — a centre saved '
            'from a vague position puts the boundary somewhere nobody chose.',
            style: context.text.bodySmall
                ?.copyWith(color: context.palette.onInfoContainer),
          ),
        ],
      ),
    );
  }
}

class _LocationCard extends StatelessWidget {
  const _LocationCard({
    required this.location,
    required this.busy,
    required this.onCapture,
  });

  final ManagedWorkLocation location;
  final bool busy;
  final VoidCallback onCapture;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                location.placed
                    ? Icons.where_to_vote_outlined
                    : Icons.not_listed_location_outlined,
                color: location.placed ? palette.success : palette.warning,
              ),
              const SizedBox(width: AppSpacing.xs),
              Expanded(
                child: Text(location.name, style: context.text.titleSmall),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.xxs),
          Text(
            location.placed
                ? 'Set, with a ${location.radiusMetres} metre radius'
                // Said plainly: an unplaced location is not a stricter
                // setting, it is no setting. Nothing is enforced for it.
                : 'Not set yet — nobody is checked against this location',
            style: context.text.bodySmall?.copyWith(
              color: location.placed ? palette.inkSecondary : palette.warning,
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          SizedBox(
            width: double.infinity,
            child: busy
                ? const Center(
                    child: Padding(
                      padding: EdgeInsets.all(AppSpacing.xs),
                      child: SizedBox(
                        width: AppSizes.iconSm,
                        height: AppSizes.iconSm,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                    ),
                  )
                : OutlinedButton.icon(
                    onPressed: onCapture,
                    icon: const Icon(Icons.my_location),
                    label: Text(
                      location.placed ? 'Move it here' : 'Set from here',
                    ),
                  ),
          ),
        ],
      ),
    );
  }
}

class _Error extends StatelessWidget {
  const _Error({required this.error});

  final Object error;

  @override
  Widget build(BuildContext context) {
    final failure = error is AppFailure ? error as AppFailure : null;
    return ListView(
      padding: const EdgeInsets.all(AppSpacing.md),
      children: [
        AppCard(
          child: Text(
            failure?.userMessage ??
                'Work locations could not be loaded. Pull down to try again.',
            style: context.text.bodyMedium,
          ),
        ),
      ],
    );
  }
}
