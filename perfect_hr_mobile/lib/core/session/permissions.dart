/// Fine-grained client-side permission hints.
///
/// CRITICAL (Instructions §15, §44): these values are *hints supplied by the
/// server* used to decide what to render. They are not a security boundary.
/// Hiding a widget does not protect data — every request is authorised again
/// by APISIX/FastAPI. Never grant capability on the strength of this set
/// alone, and never construct it from client-side logic.
enum Permission {
  attendanceSelfRead('attendance.self.read'),
  attendanceSelfWrite('attendance.self.write'),
  attendanceTeamRead('attendance.team.read'),
  attendanceOrgRead('attendance.org.read'),
  leaveSelfWrite('leave.self.write'),
  leaveApprove('leave.approve'),
  requestSelfWrite('request.self.write'),
  requestProcess('request.process'),
  payrollSelfRead('payroll.self.read'),
  payrollOrgRead('payroll.org.read'),
  performanceSelfRead('performance.self.read'),
  performanceTeamRead('performance.team.read'),
  workforceRead('workforce.read'),
  recruitmentRead('recruitment.read'),
  recruitmentAction('recruitment.action'),
  executiveIntelligenceRead('executive.intelligence.read'),
  attritionIntelligenceRead('attrition.intelligence.read'),
  aiAssistant('ai.assistant'),
  tenantAdmin('tenant.admin');

  const Permission(this.wireValue);

  final String wireValue;

  static Permission? fromWire(String value) {
    for (final p in Permission.values) {
      if (p.wireValue == value) return p;
    }
    return null; // Unknown permissions from a newer backend are ignored.
  }
}

/// Immutable set of server-granted permission hints.
///
/// Implemented as a plain class rather than an extension type over
/// `Set<Permission>`. An extension type with a private representation field
/// (`_values`) raises a question about whether its implicit constructor is
/// reachable from another library — and `SessionController` does exactly that.
/// The answer is not worth depending on in authorisation-adjacent code, so
/// this is deliberately ordinary.
class PermissionSet {
  const PermissionSet(this._values);

  final Set<Permission> _values;

  static const PermissionSet empty = PermissionSet(<Permission>{});

  bool has(Permission permission) => _values.contains(permission);

  bool hasAny(Iterable<Permission> permissions) =>
      permissions.any(_values.contains);

  bool hasAll(Iterable<Permission> permissions) =>
      permissions.every(_values.contains);

  /// Unmodifiable view, for diagnostics and tests. Callers must not rely on
  /// iteration order.
  Set<Permission> get values => Set.unmodifiable(_values);

  int get length => _values.length;

  bool get isEmpty => _values.isEmpty;

  /// Parses the permission claim array returned by the application API.
  ///
  /// Unrecognised entries are dropped so a newer backend cannot break an
  /// older client.
  static PermissionSet fromWire(Iterable<String>? raw) {
    if (raw == null) return empty;
    final parsed =
        raw.map(Permission.fromWire).whereType<Permission>().toSet();
    return PermissionSet(parsed);
  }

  @override
  bool operator ==(Object other) =>
      other is PermissionSet &&
      other._values.length == _values.length &&
      other._values.containsAll(_values);

  @override
  int get hashCode => Object.hashAllUnordered(_values);

  @override
  String toString() =>
      'PermissionSet(${_values.map((p) => p.wireValue).join(', ')})';
}
