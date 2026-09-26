/// Which kind of proof the server is asking this device for.
///
/// The server decides, never the app. Only the server knows what the account
/// actually holds, and an app that guessed would raise a prompt the user cannot
/// answer whenever it guessed wrong — which is indistinguishable, from the
/// user's side, from the product being broken.
///
/// Lives in `core` rather than under a feature because both sign-in and
/// approvals ask the same question and must agree on the answer.
enum SecondFactorMethod {
  /// This installation's own paired key, released by the device's biometric.
  /// Preferred wherever it is offered: the app being asked *is* the device, so
  /// its key is certainly reachable, with no platform association to validate.
  device,

  /// A passkey, through the platform's credential manager.
  passkey,
}

/// Read the method off a server response.
///
/// Defaults to [SecondFactorMethod.passkey] when the field is absent, so an app
/// newer than the server it is talking to keeps working against the older
/// response shape instead of failing on a missing key.
SecondFactorMethod parseSecondFactorMethod(Object? raw) {
  return raw == 'device' ? SecondFactorMethod.device : SecondFactorMethod.passkey;
}
