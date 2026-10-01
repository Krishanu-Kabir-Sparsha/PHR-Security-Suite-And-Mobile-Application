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
import 'package:perfect_hr_mobile/features/attendance/domain/offsite_request.dart';
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
  int offsiteCount = 0;
  double? sentLatitude;
  double? sentLongitude;
  double? sentAccuracy;
  String? sentReason;

  @override
  Future<AttendanceToggleResult> toggle({
    double? latitude,
    double? longitude,
    double? accuracyMetres,
  }) async {
    toggleCount++;
    sentLatitude = latitude;
    sentLongitude = longitude;
    sentAccuracy = accuracyMetres;
    // Every attempt fails while the stub holds a failure. There is no longer
    // a "second attempt with a reason" that succeeds -- that was the whole
    // defect, see the group below.
    if (failure != null) throw failure!;
    return AttendanceToggleResult(
      checkedIn: true,
      today: const TodayAttendance(state: AttendanceState.checkedIn),
    );
  }


  @override
  Future<OffsiteRequest> submitOffsiteRequest({
    required String reason,
    double? latitude,
    double? longitude,
    double? accuracyMetres,
  }) async {
    offsiteCount++;
    sentReason = reason;
    sentLatitude = latitude;
    sentLongitude = longitude;
    sentAccuracy = accuracyMetres;
    return OffsiteRequest(
      id: 'req-1',
      state: OffsiteRequestState.pending,
      requestedAt: DateTime.now(),
      reason: reason,
      distanceMetres: 1100,
      locationName: 'Head Office',
      manager: 'Ayesha Rahman',
    );
  }

  @override
  Future<OffsiteRequest?> loadOffsiteRequest() async => null;

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

    test('a reason creates a REQUEST and records no attendance', () async {
      // This replaces a test that asserted the opposite, and the change is the
      // point of the whole feature.
      //
      // The old behaviour: refused, the app asked why, the same punch was
      // resent carrying a reason, and the server accepted it and flagged it.
      // That made the employee the authoriser of their own exception -- the
      // radius stopped nobody willing to type a sentence, which is a prompt,
      // not a control.
      //
      // Now the reason goes to a manager and NOTHING is recorded until they
      // decide. So the assertions are: a request was made, and the punch was
      // not retried.
      final repository = _RecordingRepository(failure: offSite());
      final container = _container(
        repository,
        const _FixedLocation(
          PunchLocation(latitude: 23.9, longitude: 90.4),
        ),
      );
      addTearDown(container.dispose);

      await container.read(attendanceToggleProvider.notifier).toggle();
      final request = await container
          .read(attendanceToggleProvider.notifier)
          .submitOffsiteRequest('Client visit at Gulshan');

      expect(request, isNotNull);
      expect(request!.state, OffsiteRequestState.pending);
      expect(repository.sentReason, 'Client visit at Gulshan');
      expect(repository.offsiteCount, 1);
      // THE assertion. A second toggle here would mean the punch had been
      // retried, which is exactly what must not happen any more.
      expect(repository.toggleCount, 1);
    });

    test('the request carries where they were when refused', () async {
      // Not where they are by the time they finish typing. A manager judging
      // "was this person at a client site at 9am?" needs the 9am position,
      // and a phone moves while somebody writes a sentence.
      final repository = _RecordingRepository(failure: offSite());
      final container = _container(
        repository,
        const _FixedLocation(
          PunchLocation(latitude: 23.9, longitude: 90.4, accuracyMetres: 12),
        ),
      );
      addTearDown(container.dispose);

      await container.read(attendanceToggleProvider.notifier).toggle();
      await container
          .read(attendanceToggleProvider.notifier)
          .submitOffsiteRequest('Client visit');

      expect(repository.sentLatitude, 23.9);
      expect(repository.sentAccuracy, 12);
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
