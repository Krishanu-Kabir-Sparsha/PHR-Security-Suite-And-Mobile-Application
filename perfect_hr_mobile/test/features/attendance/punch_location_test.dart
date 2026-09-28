import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/data/cache_policy.dart';
import 'package:perfect_hr_mobile/core/errors/app_failure.dart';
import 'package:perfect_hr_mobile/core/networking/dio_failure_mapper.dart';
import 'package:perfect_hr_mobile/core/security/punch_location_service.dart';
import 'package:perfect_hr_mobile/features/attendance/application/attendance_providers.dart';
import 'package:perfect_hr_mobile/features/attendance/data/attendance_repository.dart';
import 'package:perfect_hr_mobile/features/attendance/domain/attendance_overview.dart';
import 'package:perfect_hr_mobile/features/dashboard/domain/employee_home_summary.dart';

/// Where a punch was made, and what happens when the server says "not here".
///
/// The rule underneath all of it: **a location failure must never stop a
/// punch.** Attendance is how people get paid, and GPS failures fall hardest
/// on whoever has the older handset or the basement office.

class _FixedLocation implements PunchLocationService {
  const _FixedLocation(this._value);
  final PunchLocation? _value;

  @override
  Future<PunchLocation?> current() async => _value;
}

class _RecordingRepository implements AttendanceRepository {
  _RecordingRepository({this.failure});

  final Object? failure;

  int toggleCount = 0;
  int breakCount = 0;
  double? sentLatitude;
  double? sentLongitude;
  double? sentAccuracy;
  String? sentReason;

  @override
  Future<AttendanceToggleResult> toggle({
    double? latitude,
    double? longitude,
    double? accuracyMetres,
    String? offSiteReason,
  }) async {
    toggleCount++;
    sentLatitude = latitude;
    sentLongitude = longitude;
    sentAccuracy = accuracyMetres;
    sentReason = offSiteReason;
    // Only the FIRST attempt fails, so a retry carrying a reason succeeds --
    // which is exactly the server's behaviour.
    if (failure != null && offSiteReason == null) throw failure!;
    return AttendanceToggleResult(
      checkedIn: true,
      today: const TodayAttendance(state: AttendanceState.checkedIn),
    );
  }

  @override
  Future<AttendanceToggleResult> toggleBreak({String? breakType}) async {
    breakCount++;
    return AttendanceToggleResult(
      checkedIn: true,
      today: const TodayAttendance(state: AttendanceState.onBreak),
    );
  }

  @override
  Future<AttendanceOverview> resolveStale() async =>
      const AttendanceOverview(today: TodayAttendance(
        state: AttendanceState.notCheckedIn,
      ));

  @override
  Future<DataSnapshot<AttendanceOverview>> loadOverview({
    bool forceRefresh = false,
  }) async =>
      DataSnapshot.live(
        const AttendanceOverview(
          today: TodayAttendance(state: AttendanceState.notCheckedIn),
        ),
        syncedAt: DateTime.now(),
      );

  @override
  Future<void> invalidate() async {}
}

ProviderContainer _container(
  _RecordingRepository repository,
  PunchLocationService location,
) {
  return ProviderContainer(
    overrides: [
      attendanceRepositoryProvider.overrideWithValue(repository),
      punchLocationServiceProvider.overrideWithValue(location),
    ],
  );
}

void main() {
  group('location on a punch', () {
    test('a fix is sent with the punch, accuracy included', () async {
      // Accuracy matters as much as position: the server subtracts it before
      // deciding anybody is out of range, so a poor fix counts in the
      // employee's favour instead of against them.
      final repository = _RecordingRepository();
      final container = _container(
        repository,
        const _FixedLocation(
          PunchLocation(
            latitude: 23.8759,
            longitude: 90.3200,
            accuracyMetres: 18,
          ),
        ),
      );
      addTearDown(container.dispose);

      await container.read(attendanceToggleProvider.notifier).toggle();

      expect(repository.sentLatitude, 23.8759);
      expect(repository.sentLongitude, 90.3200);
      expect(repository.sentAccuracy, 18);
    });

    test('no fix still punches', () async {
      // THE rule. Permission denied, radio off, timeout, a platform channel
      // error on an odd handset -- all of them mean "send it without
      // coordinates", never "refuse to record that somebody came to work".
      final repository = _RecordingRepository();
      final container = _container(repository, const NoPunchLocationService());
      addTearDown(container.dispose);

      final result =
          await container.read(attendanceToggleProvider.notifier).toggle();

      expect(result, isNotNull);
      expect(repository.toggleCount, 1);
      expect(repository.sentLatitude, isNull);
    });
  });

  group('an off-site refusal', () {
    AppFailure offSite() {
      // Built through the real mapper, so this asserts the code actually
      // survives the network layer rather than assuming it does.
      final mapper = DioFailureMapper(isOffline: () => false);
      return mapper.map(
        DioException(
          requestOptions: RequestOptions(path: '/me/attendance/toggle'),
          // Without the type the mapper treats this as an unknown transport
          // error and never looks at the body -- so the assertion below would
          // pass or fail for the wrong reason.
          type: DioExceptionType.badResponse,
          response: Response<dynamic>(
            requestOptions: RequestOptions(path: '/me/attendance/toggle'),
            statusCode: 403,
            data: const {
              'user_message': 'You seem to be about 1.1 km away from Head '
                  'Office. If you are working away from there, send this '
                  'again with a short reason and it will be recorded.',
              'code': 'off_site',
              'errors': {'distance_m': 1100, 'radius_m': 250},
            },
          ),
        ),
        StackTrace.current,
      );
    }

    test('the server code survives the mapper', () async {
      final failure = offSite();
      expect(failure.code, 'off_site');
      expect(failure.details['distance_m'], 1100);
      // And the message is the server's own, not a generic 403 line.
      expect(failure.userMessage, contains('1.1 km'));
    });

    test('the first attempt fails and holds the failure for the screen',
        () async {
      final repository = _RecordingRepository(failure: offSite());
      final container = _container(
        repository,
        const _FixedLocation(
          PunchLocation(latitude: 23.9, longitude: 90.4),
        ),
      );
      addTearDown(container.dispose);

      final result =
          await container.read(attendanceToggleProvider.notifier).toggle();

      expect(result, isNull);
      final held = container.read(attendanceToggleProvider).error;
      expect(held, isA<AppFailure>());
      expect((held! as AppFailure).code, 'off_site');
    });

    test('sending a reason gets the punch accepted', () async {
      // The appeal path. Nobody is left unable to start work, and the reason
      // travels with the record for HR.
      final repository = _RecordingRepository(failure: offSite());
      final container = _container(
        repository,
        const _FixedLocation(
          PunchLocation(latitude: 23.9, longitude: 90.4),
        ),
      );
      addTearDown(container.dispose);

      await container.read(attendanceToggleProvider.notifier).toggle();
      final second = await container
          .read(attendanceToggleProvider.notifier)
          .toggle(offSiteReason: 'Client visit at Gulshan');

      expect(second, isNotNull);
      expect(repository.sentReason, 'Client visit at Gulshan');
      expect(repository.toggleCount, 2);
    });
  });

  group('breaks', () {
    test('a break is its own call, not a check-out', () async {
      // Sharing the toggle would make "going for lunch" and "going home" the
      // same button press, and the two rows would be indistinguishable
      // afterwards.
      final repository = _RecordingRepository();
      final container = _container(repository, const NoPunchLocationService());
      addTearDown(container.dispose);

      await container.read(attendanceToggleProvider.notifier).toggleBreak();

      expect(repository.breakCount, 1);
      expect(repository.toggleCount, 0);
    });

    test('the state comes back as on break', () async {
      final container = _container(
        _RecordingRepository(),
        const NoPunchLocationService(),
      );
      addTearDown(container.dispose);

      final result = await container
          .read(attendanceToggleProvider.notifier)
          .toggleBreak();

      expect(result?.today.state, AttendanceState.onBreak);
    });
  });
}
