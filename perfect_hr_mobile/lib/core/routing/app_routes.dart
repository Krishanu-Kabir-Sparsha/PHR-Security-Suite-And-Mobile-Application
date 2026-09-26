/// Route paths and names.
///
/// Instructions §20 — route *names* are the Blueprint screen IDs, so a
/// navigation log or analytics event reads directly against the spec.
/// Paths stay human-readable for deep links and push-notification payloads.
abstract final class AppRoutes {
  // Authentication
  static const String welcome = '/welcome';
  static const String login = '/login';
  static const String mfa = '/login/mfa';
  static const String biometric = '/login/biometric';

  /// Reachable without a session, by necessity: a handset cannot sign in until
  /// it is paired, so a pairing screen behind the session gate would be a door
  /// locked from the inside.
  static const String pairDevice = '/login/pair';

  // Shell branch roots — one per bottom-navigation destination.
  static const String home = '/home';
  static const String attendance = '/attendance';
  static const String requests = '/requests';
  static const String team = '/team';
  static const String approvals = '/approvals';
  static const String workforce = '/workforce';
  static const String insights = '/insights';
  static const String alerts = '/alerts';
  static const String tenants = '/tenants';
  static const String monitoring = '/monitoring';
  static const String ai = '/ai';
  static const String more = '/more';

  // Attendance branch
  static const String checkIn = '/attendance/check-in';
  static const String attendanceCalendar = '/attendance/calendar';
  static const String attendanceCorrection = '/attendance/correction';

  // Leave — reached from Home and from Requests
  static const String leave = '/requests/leave';
  static const String applyLeave = '/requests/leave/apply';

  // Requests branch
  static const String requestDetail = '/requests/:requestId';
  static String requestDetailFor(String id) => '/requests/$id';

  // Payroll — reached from Home and More
  static const String payroll = '/more/payroll';
  static const String payslip = '/more/payroll/:payslipId';
  static String payslipFor(String id) => '/more/payroll/$id';

  // Profile & settings
  static const String profile = '/more/profile';
  static const String security = '/more/security';

  // Manager branch
  static const String employee360 = '/team/:employeeId';
  static String employee360For(String id) => '/team/$id';
  static const String teamAttendance = '/team/attendance';
  static const String approvalDetail = '/approvals/:approvalId';
  static String approvalDetailFor(String id) => '/approvals/$id';

  // HR branch
  static const String hrEmployeeDetail = '/workforce/:employeeId';
  static String hrEmployeeDetailFor(String id) => '/workforce/$id';
  static const String recruitment = '/workforce/recruitment';
  static const String candidateDetail = '/workforce/recruitment/:candidateId';
  static String candidateDetailFor(String id) =>
      '/workforce/recruitment/$id';

  // Executive branch
  static const String executiveInsightDetail = '/insights/:insightId';
  static String executiveInsightDetailFor(String id) => '/insights/$id';

  // AI branch
  static const String aiConversation = '/ai/conversation';

  // Cross-cutting
  static const String notifications = '/notifications';
  static const String search = '/search';
}
