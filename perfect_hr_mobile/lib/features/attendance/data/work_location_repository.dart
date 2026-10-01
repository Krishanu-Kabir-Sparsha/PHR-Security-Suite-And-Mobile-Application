import 'package:flutter/foundation.dart';

import '../../../core/networking/api_client.dart';

/// A work location, and whether it has been placed on the map yet.
///
/// "Placed" is the whole point of this screen. A geofence with no centre
/// enforces nothing, and until now the only way to give it one was to type two
/// decimal numbers that nobody knows offhand.
@immutable
class ManagedWorkLocation {
  const ManagedWorkLocation({
    required this.id,
    required this.name,
    required this.placed,
    this.latitude,
    this.longitude,
    this.radiusMetres = 0,
  });

  final String id;
  final String name;

  /// Whether this location has coordinates to measure against. Nothing is
  /// enforced for one that does not, so an unplaced site is not a stricter
  /// setting than a placed one -- it is no setting at all.
  final bool placed;

  final double? latitude;
  final double? longitude;
  final int radiusMetres;

  factory ManagedWorkLocation.fromJson(Map<String, Object?> json) =>
      ManagedWorkLocation(
        id: '${json['id'] ?? ''}',
        name: json['name'] as String? ?? '',
        placed: json['placed'] as bool? ?? false,
        latitude: (json['latitude'] as num?)?.toDouble(),
        longitude: (json['longitude'] as num?)?.toDouble(),
        radiusMetres: (json['radius_m'] as num?)?.toInt() ?? 0,
      );
}

@immutable
class WorkLocationList {
  const WorkLocationList({
    required this.locations,
    required this.maxAccuracyMetres,
  });

  final List<ManagedWorkLocation> locations;

  /// How good a fix has to be before the server will save it as a centre.
  ///
  /// Sent by the server rather than hard-coded, so the screen can say the real
  /// number while somebody is standing outside waiting for their signal to
  /// settle. A client guessing it would eventually guess wrong and tell people
  /// to wait for an accuracy the server had stopped requiring.
  final int maxAccuracyMetres;
}

abstract interface class WorkLocationRepository {
  Future<WorkLocationList> load();

  /// Write this handset's current position as the centre of [locationId].
  Future<ManagedWorkLocation> captureHere({
    required String locationId,
    required double latitude,
    required double longitude,
    double? accuracyMetres,
    int? radiusMetres,
  });
}

class ApiWorkLocationRepository implements WorkLocationRepository {
  ApiWorkLocationRepository({required ApiClient client}) : _client = client;

  final ApiClient _client;

  @override
  Future<WorkLocationList> load() async {
    final body = await _client.get<Map<String, dynamic>>(
      '/admin/work-locations',
    );
    final raw = body['locations'];
    return WorkLocationList(
      locations: raw is List
          ? raw
              .whereType<Map<Object?, Object?>>()
              .map((l) => ManagedWorkLocation.fromJson(l.cast<String, Object?>()))
              .toList()
          : const [],
      maxAccuracyMetres: (body['max_accuracy_m'] as num?)?.toInt() ?? 100,
    );
  }

  @override
  Future<ManagedWorkLocation> captureHere({
    required String locationId,
    required double latitude,
    required double longitude,
    double? accuracyMetres,
    int? radiusMetres,
  }) async {
    final body = await _client.post<Map<String, dynamic>>(
      '/admin/work-locations/$locationId/here',
      data: <String, Object?>{
        'latitude': latitude,
        'longitude': longitude,
        // Sent so the server can REFUSE a vague fix. A centre captured from a
        // two-kilometre fix would put the geofence somewhere nobody chose, and
        // the damage is invisible until a workforce cannot check in.
        if (accuracyMetres != null) 'accuracy_m': accuracyMetres,
        if (radiusMetres != null) 'radius_m': radiusMetres,
      },
    );
    final raw = body['location'];
    return ManagedWorkLocation.fromJson((raw as Map).cast<String, Object?>());
  }
}
