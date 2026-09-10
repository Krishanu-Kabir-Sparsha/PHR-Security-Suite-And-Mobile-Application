import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../errors/app_failure.dart';

/// Network reachability status.
///
/// IMPORTANT: `connectivity_plus` reports whether a network *interface* is
/// available, not whether Perfect HR is reachable. A captive portal, a VPN
/// without a route, or a DNS failure all report as online. Treat this as a
/// hint that shortcuts the obvious offline case; the authoritative answer is
/// always the outcome of the request itself.
enum ConnectivityStatus { online, offline }

/// Connectivity abstraction, so tests and mock repositories can drive
/// offline scenarios without a device.
abstract interface class ConnectivityService {
  ConnectivityStatus get status;

  Stream<ConnectivityStatus> get changes;

  bool get isOffline;

  Future<void> dispose();
}

/// Live implementation backed by `connectivity_plus`.
class PlatformConnectivityService implements ConnectivityService {
  PlatformConnectivityService({Connectivity? connectivity})
      : _connectivity = connectivity ?? Connectivity();

  final Connectivity _connectivity;
  final _controller = StreamController<ConnectivityStatus>.broadcast();
  StreamSubscription<List<ConnectivityResult>>? _subscription;

  // Optimistic default: assume online until told otherwise, so a slow first
  // platform response does not render a spurious offline state.
  ConnectivityStatus _status = ConnectivityStatus.online;
  bool _initialised = false;

  /// Resolves current status and subscribes to changes.
  ///
  /// Idempotent: both `main()` (to settle status before the first frame) and
  /// the provider (in case the service is created lazily elsewhere) call this,
  /// and a second subscription would double-emit every change.
  Future<void> initialise() async {
    if (_initialised) return;
    _initialised = true;
    _status = _resolve(await _connectivity.checkConnectivity());
    _subscription = _connectivity.onConnectivityChanged.listen((results) {
      final next = _resolve(results);
      if (next == _status) return;
      _status = next;
      _controller.add(next);
    });
  }

  static ConnectivityStatus _resolve(List<ConnectivityResult> results) {
    final hasInterface = results.any(
      (r) => r != ConnectivityResult.none,
    );
    return hasInterface ? ConnectivityStatus.online : ConnectivityStatus.offline;
  }

  @override
  ConnectivityStatus get status => _status;

  @override
  Stream<ConnectivityStatus> get changes => _controller.stream;

  @override
  bool get isOffline => _status == ConnectivityStatus.offline;

  @override
  Future<void> dispose() async {
    await _subscription?.cancel();
    await _controller.close();
  }
}

/// In-memory implementation for tests and dev mock mode.
class FakeConnectivityService implements ConnectivityService {
  FakeConnectivityService([this._status = ConnectivityStatus.online]);

  ConnectivityStatus _status;
  final _controller = StreamController<ConnectivityStatus>.broadcast();

  void setStatus(ConnectivityStatus status) {
    if (status == _status) return;
    _status = status;
    _controller.add(status);
  }

  @override
  ConnectivityStatus get status => _status;

  @override
  Stream<ConnectivityStatus> get changes => _controller.stream;

  @override
  bool get isOffline => _status == ConnectivityStatus.offline;

  @override
  Future<void> dispose() => _controller.close();
}

final connectivityServiceProvider = Provider<ConnectivityService>((ref) {
  final service = PlatformConnectivityService();
  // Fire-and-forget: `status` is optimistic until this resolves, which is the
  // correct default for a first frame.
  unawaited(service.initialise());
  ref.onDispose(service.dispose);
  return service;
});

/// Reactive connectivity for widgets, e.g. to show an offline banner.
final connectivityStatusProvider = StreamProvider<ConnectivityStatus>((ref) {
  final service = ref.watch(connectivityServiceProvider);
  return service.changes;
});

/// Guards an action that cannot be satisfied from cache and must reach the
/// server to be valid.
///
/// Spec: UI-UX §48, Instructions §17. Attendance check-in, approvals and any
/// submission are in this category — completing them optimistically offline
/// would create records the backend never authorised.
///
/// ```dart
/// await requireLiveConnection(
///   connectivity,
///   action: () => api.post('/attendance/check-in'),
///   message: 'Connection required to complete check-in.',
/// );
/// ```
Future<T> requireLiveConnection<T>(
  ConnectivityService connectivity, {
  required Future<T> Function() action,
  String? message,
}) async {
  if (connectivity.isOffline) {
    throw ConnectionRequiredFailure(
      userMessage: message ?? 'Connection required to complete this action.',
      technical: 'blocked pre-flight: no network interface',
    );
  }
  return action();
}
