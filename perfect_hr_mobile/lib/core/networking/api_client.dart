import 'dart:io';
import 'dart:ui' show PlatformDispatcher;

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config/app_config.dart';
import '../errors/app_failure.dart';
import 'api_headers.dart';
import 'auth_interceptor.dart';
import 'connectivity_service.dart';
import 'dio_failure_mapper.dart';
import 'logging_interceptor.dart';
import 'retry_interceptor.dart';

/// Builds the configured [Dio] instance.
///
/// Spec: Tech-Stack §6, §9, Instructions §7 and §25.
///
/// All traffic goes to [AppConfig.apiBaseUrl], which is the APISIX gateway.
/// The app has no other outbound host and no direct service or database
/// access.
Dio buildDio({
  required AppConfig config,
  required AuthTokenStore tokenStore,
  required ConnectivityService connectivity,
  String clientVersion = 'unknown',
  void Function()? onSessionExpired,
}) {
  final options = BaseOptions(
    baseUrl: config.apiBaseUrl,
    connectTimeout: const Duration(seconds: 12),
    // Generous read timeout: AI endpoints do real work, and mobile networks in
    // the target market are frequently slow rather than absent.
    receiveTimeout: const Duration(seconds: 30),
    sendTimeout: const Duration(seconds: 20),
    headers: {
      ApiHeaders.accept: 'application/json',
      ApiHeaders.clientApp: 'perfect-hr-mobile',
      ApiHeaders.clientVersion: clientVersion,
      ApiHeaders.clientPlatform: _platformName(),
    },
    // Non-2xx raises a DioException carrying the response, which is what the
    // failure mapper needs: it reads the status and the body (for field
    // errors) in one place, so no other layer interprets status codes.
    validateStatus: (status) => status != null && status >= 200 && status < 300,
    responseType: ResponseType.json,
  );

  final dio = Dio(options);

  // A bare client used to replay requests, so refresh and retry cannot recurse
  // through their own interceptors.
  final replayClient = Dio(options);

  dio.interceptors.addAll([
    _RequestContextInterceptor(),
    AuthInterceptor(
      tokenStore: tokenStore,
      retryClient: replayClient,
      onSessionExpired: onSessionExpired,
    ),
    RetryInterceptor(client: replayClient),
    if (config.allowsVerboseLogging) const LoggingInterceptor(),
  ]);

  return dio;
}

/// Android and iOS are the only targets (Tech-Stack §2), so `dart:io` is safe
/// here and no web branch is pretended.
String _platformName() {
  if (Platform.isAndroid) return 'android';
  if (Platform.isIOS) return 'ios';
  return Platform.operatingSystem;
}

/// Adds per-request context: a correlation ID and the device locale.
class _RequestContextInterceptor extends Interceptor {
  int _sequence = 0;

  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    options.headers.putIfAbsent(
      ApiHeaders.correlationId,
      () => _nextCorrelationId(),
    );
    options.headers.putIfAbsent(
      ApiHeaders.acceptLanguage,
      () => PlatformDispatcher.instance.locale.toLanguageTag(),
    );
    handler.next(options);
  }

  /// Timestamp plus a monotonic counter. Not a UUID: this only needs to be
  /// unique enough to correlate one client's request with a gateway trace, and
  /// it deliberately encodes no employee or device identifier.
  String _nextCorrelationId() {
    _sequence = (_sequence + 1) % 100000;
    final stamp = DateTime.now().microsecondsSinceEpoch.toRadixString(36);
    return 'phm-$stamp-$_sequence';
  }
}

/// Thin typed wrapper over [Dio].
///
/// Its one job is to guarantee that **every** transport error crossing into the
/// application is an [AppFailure]. Feature repositories depend on this class
/// rather than on Dio, so no feature ever handles a [DioException] or sees a
/// status code (Instructions §24).
class ApiClient {
  ApiClient({required Dio dio, required DioFailureMapper mapper})
      : _dio = dio,
        _mapper = mapper;

  final Dio _dio;
  final DioFailureMapper _mapper;

  Future<T> get<T>(
    String path, {
    Map<String, dynamic>? queryParameters,
    CancelToken? cancelToken,
    Options? options,
  }) {
    return _guard(
      () => _dio.get<T>(
        path,
        queryParameters: queryParameters,
        cancelToken: cancelToken,
        options: options,
      ),
    );
  }

  /// POST. Supply [idempotencyKey] for any submission that would be harmful to
  /// duplicate; without one, the request is never retried.
  Future<T> post<T>(
    String path, {
    Object? data,
    Map<String, dynamic>? queryParameters,
    String? idempotencyKey,
    CancelToken? cancelToken,
    Options? options,
  }) {
    return _guard(
      () => _dio.post<T>(
        path,
        data: data,
        queryParameters: queryParameters,
        cancelToken: cancelToken,
        options: _withIdempotency(options, idempotencyKey),
      ),
    );
  }

  Future<T> put<T>(
    String path, {
    Object? data,
    String? idempotencyKey,
    CancelToken? cancelToken,
    Options? options,
  }) {
    return _guard(
      () => _dio.put<T>(
        path,
        data: data,
        cancelToken: cancelToken,
        options: _withIdempotency(options, idempotencyKey),
      ),
    );
  }

  Future<T> patch<T>(
    String path, {
    Object? data,
    String? idempotencyKey,
    CancelToken? cancelToken,
    Options? options,
  }) {
    return _guard(
      () => _dio.patch<T>(
        path,
        data: data,
        cancelToken: cancelToken,
        options: _withIdempotency(options, idempotencyKey),
      ),
    );
  }

  Future<T> delete<T>(
    String path, {
    Object? data,
    CancelToken? cancelToken,
    Options? options,
  }) {
    return _guard(
      () => _dio.delete<T>(
        path,
        data: data,
        cancelToken: cancelToken,
        options: options,
      ),
    );
  }

  Options _withIdempotency(Options? options, String? key) {
    if (key == null) return options ?? Options();
    final base = options ?? Options();
    return base.copyWith(
      headers: {
        ...?base.headers,
        ApiHeaders.idempotencyKey: key,
      },
    );
  }

  Future<T> _guard<T>(Future<Response<T>> Function() request) async {
    try {
      final response = await request();
      final data = response.data;
      if (data == null) {
        // A 2xx with no body where one was expected is a contract violation,
        // not something to surface as a user error message.
        throw ServerFailure(
          technical: 'empty body for ${response.requestOptions.path}',
        );
      }
      return data;
    } catch (error, stackTrace) {
      throw _mapper.map(error, stackTrace);
    }
  }
}

final dioFailureMapperProvider = Provider<DioFailureMapper>((ref) {
  final connectivity = ref.watch(connectivityServiceProvider);
  return DioFailureMapper(isOffline: () => connectivity.isOffline);
});

final dioProvider = Provider<Dio>((ref) {
  final dio = buildDio(
    config: AppConfig.current,
    tokenStore: ref.watch(authTokenStoreProvider),
    connectivity: ref.watch(connectivityServiceProvider),
  );
  ref.onDispose(dio.close);
  return dio;
});

final apiClientProvider = Provider<ApiClient>((ref) {
  return ApiClient(
    dio: ref.watch(dioProvider),
    mapper: ref.watch(dioFailureMapperProvider),
  );
});
