import 'package:dio/dio.dart';

import '../errors/app_failure.dart';
import '../networking/api_headers.dart';
import '../networking/dio_failure_mapper.dart';
import 'tenant_config.dart';

/// Asks a candidate address whether it is a Perfect HR workspace.
///
/// Builds its own short-lived [Dio] per call rather than using
/// `apiClientProvider`. That is not an oversight: the shared client's base URL
/// is derived from the resolved tenant, and this runs *before* one exists. A
/// provider that depended on the thing it resolves would be a cycle.
///
/// Deliberately carries no auth interceptor and no retry policy either. Nobody
/// is signed in, and a retry against an address somebody is still typing would
/// multiply a typo into several requests to a stranger's server.
abstract interface class TenantRepository {
  /// Confirm [baseUrl] is a workspace and describe it.
  Future<TenantConfig> resolve(String baseUrl);

  /// The companies that workspace publishes for its sign-in picker.
  ///
  /// An empty list is a normal answer and not an error — see the server's
  /// `controllers/tenant.py`. It means "do not ask", and the sign-in endpoint
  /// will place each user in their own default company.
  Future<List<TenantCompany>> companies(String baseUrl);
}

class HttpTenantRepository implements TenantRepository {
  HttpTenantRepository({DioFailureMapper? mapper, Dio Function(String)? build})
      : _mapper = mapper ?? DioFailureMapper(isOffline: () => false),
        _build = build ?? _defaultDio;

  final DioFailureMapper _mapper;
  final Dio Function(String) _build;

  static Dio _defaultDio(String baseUrl) => Dio(
        BaseOptions(
          baseUrl: '$baseUrl/api/mobile/v1',
          // Shorter than the app's usual timeouts. This is somebody waiting on
          // a sign-in screen having just typed an address, and a wrong one
          // should be reported in seconds rather than making them wonder
          // whether it worked.
          connectTimeout: const Duration(seconds: 8),
          receiveTimeout: const Duration(seconds: 10),
          headers: {
            ApiHeaders.accept: 'application/json',
            ApiHeaders.clientApp: 'perfect-hr-mobile',
          },
          validateStatus: (s) => s != null && s >= 200 && s < 300,
          responseType: ResponseType.json,
        ),
      );

  @override
  Future<TenantConfig> resolve(String baseUrl) async {
    final dio = _build(baseUrl);
    try {
      final response = await dio.get<Map<String, dynamic>>('/tenant/resolve');
      final body = response.data;
      if (body == null) {
        throw const ServerFailure(
          userMessage: 'That address did not answer as a Perfect HR '
              'workspace. Check it with your HR team.',
        );
      }
      return TenantConfig.fromJson(baseUrl, body);
    } on DioException catch (error, stack) {
      // A 404 is the ordinary case, not an exceptional one: any web server
      // that is not a Perfect HR workspace has no such route. Saying "not a
      // workspace" is both true and actionable, where "404" is neither.
      if (error.response?.statusCode == 404) {
        throw ServerFailure(
          userMessage: 'That address is not a Perfect HR workspace. Check it '
              'with your HR team, then try again.',
          technical: 'tenant/resolve 404 at $baseUrl',
        );
      }
      throw _mapper.map(error, stack);
    } catch (error, stack) {
      if (error is AppFailure) rethrow;
      throw _mapper.map(error, stack);
    } finally {
      dio.close();
    }
  }

  @override
  Future<List<TenantCompany>> companies(String baseUrl) async {
    final dio = _build(baseUrl);
    try {
      final response = await dio.get<Map<String, dynamic>>('/tenant/companies');
      final raw = (response.data?['companies'] as List?) ?? const [];
      return raw
          .whereType<Map>()
          .map((c) => TenantCompany.fromJson(c.cast<String, Object?>()))
          .toList();
    } on DioException catch (error, stack) {
      // A workspace that cannot answer this is not a workspace the user cannot
      // sign into: the company step is optional by design. Returning an empty
      // list degrades to "do not ask", which is the same path a tenant that
      // publishes nothing takes, and is strictly better than blocking sign-in
      // on an optional call.
      if (error.response?.statusCode == 404) return const [];
      throw _mapper.map(error, stack);
    } catch (error, stack) {
      if (error is AppFailure) rethrow;
      throw _mapper.map(error, stack);
    } finally {
      dio.close();
    }
  }
}
