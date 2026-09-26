/// Screen identifiers from the Screen & Wireframe Blueprint.
///
/// Instructions §20 (Screen ID Traceability) — every screen must carry its
/// blueprint ID through route name, widget documentation and test name so that
/// Requirement → Screen → Code → Test remains traceable.
///
/// Do not rename these. They are contract identifiers, not labels.
abstract final class ScreenIds {
  // Authentication & Onboarding — Blueprint §5–8
  static const String authWelcome = 'AUTH-01';
  static const String authLogin = 'AUTH-02';
  static const String authMfa = 'AUTH-03';
  static const String authBiometric = 'AUTH-04';

  /// Postdates the Blueprint. Device pairing did not exist when it was
  /// written: the design assumed a native app could reach a passkey, which
  /// needs the OS vendor to validate an app-to-domain association on the
  /// handset, and that validation fails closed with nothing actionable to
  /// diagnose. The ID is allocated here rather than left blank so the screen
  /// stays traceable under §20; fold it into the Blueprint at the next revision.
  static const String authPairDevice = 'AUTH-05';

  // Employee — Blueprint §9–24
  static const String employeeHome = 'E-01';
  static const String attendanceHome = 'E-02';
  static const String checkInConfirmation = 'E-03';
  static const String attendanceCalendar = 'E-04';
  static const String attendanceCorrection = 'E-05';
  static const String leaveDashboard = 'E-06';
  static const String applyLeave = 'E-07';
  static const String requestCenter = 'E-08';
  static const String requestDetail = 'E-09';
  static const String payrollHome = 'E-10';
  static const String payslipDetail = 'E-11';
  static const String employeePerformance = 'E-12'; // Release 2
  static const String learning = 'E-13'; // Release 2
  static const String skillGap = 'E-14'; // Release 2
  static const String careerCoach = 'E-15'; // Release 2
  static const String employeeProfile = 'E-16';

  // Manager — Blueprint §25–32
  static const String managerHome = 'M-01';
  static const String myTeam = 'M-02';
  static const String employee360 = 'M-03';
  static const String approvalInbox = 'M-04';
  static const String approvalDetail = 'M-05';
  static const String teamAttendance = 'M-06';
  static const String teamPerformance = 'M-07'; // Release 2
  static const String teamProductivity = 'M-08'; // Release 2

  // HR — Blueprint §33–39
  static const String hrDashboard = 'H-01';
  static const String workforce = 'H-02';
  static const String hrEmployeeDetail = 'H-03';
  static const String hrRequestCenter = 'H-04';
  static const String recruitmentDashboard = 'H-05';
  static const String candidateDetail = 'H-06';
  static const String interviewIntelligence = 'H-07'; // Release 2

  // Executive — Blueprint §40–42
  static const String executiveHome = 'X-01';
  static const String workforceIntelligence = 'X-02';
  static const String executiveInsightDetail = 'X-03';

  // AI — Blueprint §43–47
  static const String aiHome = 'AI-01';
  static const String aiConversation = 'AI-02';
  static const String aiExplainability = 'AI-03';
  static const String aiInsightDetail = 'AI-04'; // Release 2
  static const String aiActionCenter = 'AI-05'; // Release 3

  // Cross-cutting — Blueprint §48–51
  static const String notifications = 'N-01';
  static const String globalSearch = 'S-01';
  static const String more = 'SET-01';
  static const String security = 'SET-02';

  // Super Admin — Functional Blueprint §31. Not in Release 1.
  // The Blueprint does not assign IDs to the SaaS Control experience, so these
  // are provisional and should be confirmed when Super Admin is scheduled.
  static const String saasHome = 'SA-00';
  static const String tenantList = 'SA-01';
  static const String saasMonitoring = 'SA-02';
}
