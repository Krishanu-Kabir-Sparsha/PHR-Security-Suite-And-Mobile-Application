import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';

/// Where a check-in was made, when the phone can say.
///
/// ## The one rule
///
/// **A location failure must never stop a punch.** Every path here returns
/// null rather than throwing, and the caller sends the punch without
/// coordinates — which the server reads as "nothing to check" and allows.
///
/// That is not laziness about the control. Attendance is how people get paid,
/// and location failures are not evenly distributed: they fall on whoever has
/// the older handset, the basement office, the metal roof, or who declined the
/// permission prompt once, months ago, for reasons nobody recorded. A hard
/// dependency on GPS turns each of those into an unpaid hour and a support
/// ticket. The server-side flag, not a client-side refusal, is where the
/// control actually lives.
///
/// ## Why permission is asked at check-in
///
/// Not at launch. A prompt on first open, before anybody has seen what the app
/// does, is how an app gets denied permanently — and on Android a permanent
/// denial cannot be re-prompted from inside the app at all. Asked at the
/// moment somebody presses Check In, the request has visible cause.
class PunchLocation {
  const PunchLocation({
    required this.latitude,
    required this.longitude,
    this.accuracyMetres,
  });

  final double latitude;
  final double longitude;

  /// The phone's own margin of error, in metres.
  ///
  /// Sent because the server subtracts it before deciding anybody is out of
  /// range. A fix 300m out with 200m of error is consistent with standing
  /// 100m away, and refusing it would be treating uncertainty as guilt.
  final double? accuracyMetres;

  Map<String, Object?> toJson() => {
        'latitude': latitude,
        'longitude': longitude,
        if (accuracyMetres != null) 'accuracy_m': accuracyMetres,
      };
}

abstract interface class PunchLocationService {
  /// A fix, or null if one cannot be had for any reason.
  Future<PunchLocation?> current();
}

class GeolocatorPunchLocationService implements PunchLocationService {
  const GeolocatorPunchLocationService({
    this.timeout = const Duration(seconds: 8),
  });

  /// How long to wait for a fix before giving up and punching without one.
  ///
  /// Short on purpose. Somebody is standing at a door with a phone in their
  /// hand; a thirty-second wait for a better fix reads as a frozen app, and
  /// they will press the button again.
  final Duration timeout;

  @override
  Future<PunchLocation?> current() async {
    try {
      if (!await Geolocator.isLocationServiceEnabled()) {
        // Location is switched off device-wide. Prompting would open Settings
        // and lose the check-in they were in the middle of.
        return null;
      }

      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever) {
        // deniedForever cannot be re-prompted from inside the app. Punching
        // without coordinates is the only outcome that lets them work.
        return null;
      }

      final position = await Geolocator.getCurrentPosition(
        locationSettings: LocationSettings(
          // 'medium' rather than 'best'. A geofence is measured in hundreds
          // of metres, and 'best' keeps the GPS radio hunting for precision
          // that changes no decision here while the user waits.
          accuracy: LocationAccuracy.medium,
          timeLimit: timeout,
        ),
      );
      return PunchLocation(
        latitude: position.latitude,
        longitude: position.longitude,
        accuracyMetres: position.accuracy,
      );
    } catch (_) {
      // Timeouts, a revoked permission mid-call, a platform channel error on
      // an unusual handset. All of them mean the same thing to the caller:
      // punch without coordinates.
      return null;
    }
  }
}

/// Always null. For widget tests, which have no platform channel to answer.
class NoPunchLocationService implements PunchLocationService {
  const NoPunchLocationService();

  @override
  Future<PunchLocation?> current() async => null;
}

final punchLocationServiceProvider = Provider<PunchLocationService>((ref) {
  return const GeolocatorPunchLocationService();
});
