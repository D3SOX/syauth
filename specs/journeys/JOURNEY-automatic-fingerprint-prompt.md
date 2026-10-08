# Open biometrics automatically with a manual approval fallback

The user requested direct fingerprint approval without first pressing Authorize,
and asked that dismissing the biometric dialog return to the original approval
screen with Authorize and Disallow.

A verified challenge launches the existing over-keyguard approval Activity. Its
first resume automatically starts the existing strong-biometric, Keystore-backed
signing operation. Dismissing the system prompt (outside tap, Back, or its Cancel
button) leaves the request pending on the Authorize/Disallow screen. Authorize
reopens biometrics; Disallow sends the existing denied response and finishes.
Resuming the screen does not automatically reopen a dismissed prompt.

Each biometric operation tracks its completion so late callbacks from a dismissed
operation cannot answer a manual retry. Opening or dismissing the prompt never
authorizes authentication. Successful per-use strong biometric Keystore signing
is still required. No PIN fallback, cached authorization, wire-format change, or
PAM change is introduced. The existing desktop deadline remains in effect on the
fallback screen. Host cancellation and timeout close both screens and suppress
late callbacks. Malformed or already cancelled requests do not open biometrics.

## Validation

`BiometricPromptTest` covers automatic start without an Authorize tap, pause/resume
without duplicate prompting, no response before biometric success, a new operation
for every request, missing extras, cancellation before launch, dismissal followed
by manual retry, rejection through Disallow, and late callbacks after dismissal.
Existing tests cover host cancellation while biometrics are pending.

On the physical Pixel 8 Pro (Android 16), the automatic system dialog displayed
"Touch the fingerprint sensor" and Cancel. The user's fingerprint returned
`PAM_SUCCESS` without an Authorize tap. Unanswered requests dismissed the biometric
operation at the existing 8-second PAM deadline. Headphones stayed connected.
With the final fallback build installed, tapping outside the system dialog returned
to the same approval Activity. Its screen displayed Authorize and Disallow. The PAM
request remained pending until its deadline rather than failing at the outside tap.

## Implementation

- `syauth-android/app/src/main/kotlin/com/sy/syauth/android/bg/ChallengeApprovalActivity.kt`
- `syauth-android/app/src/test/kotlin/com/sy/syauth/android/bg/BiometricPromptTest.kt`
- `syauth-android/app/src/test/kotlin/com/sy/syauth/android/bg/ChallengeApprovalActivityTest.kt`
- `docs/android-setup.md`, `docs/pam.md`, and `docs/cancellation.md`

The installation/PAM guides use `sudo`, and the root `AGENTS.md` was removed at the
user's request.
