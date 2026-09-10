/// Perfect HR roles — Functional Blueprint §2 (Target Role Architecture).
///
/// The role determines which *experience* is presented. It never determines
/// what data the client is entitled to: Instructions §5 and §15 require that
/// authorisation is always enforced server-side. Role here drives navigation
/// and layout only.
enum UserRole {
  employee('employee', 'My HR'),
  manager('manager', 'My Team'),
  hr('hr', 'HR Operations'),
  chro('chro', 'HR Intelligence'),
  executive('executive', 'Executive Intelligence'),
  superAdmin('super_admin', 'SaaS Control');

  const UserRole(this.wireValue, this.experienceLabel);

  /// Value exchanged with the backend / present in Keycloak token claims.
  final String wireValue;

  /// Experience name used in onboarding copy and analytics dimensions.
  final String experienceLabel;

  static UserRole fromWire(String? value) {
    return UserRole.values.firstWhere(
      (r) => r.wireValue == value,
      orElse: () => UserRole.employee,
    );
  }

  /// CHRO and CEO share the executive navigation profile
  /// (UI-UX §5.4 lists one Executive bottom navigation for both).
  bool get usesExecutiveExperience =>
      this == UserRole.chro || this == UserRole.executive;
}
