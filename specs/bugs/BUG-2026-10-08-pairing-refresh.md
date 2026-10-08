# Pairing completion requires restarting the Android app

After LESC and four-word confirmation, the phone persisted its bond and displayed
success. Tapping Done returned to an unpaired Home screen. Only restarting the
app loaded the record and initialized the companion connection.

`MainActivity` loaded the bond and installed the companion service dependencies
only in `onCreate`; the pair route's Done callback only popped navigation.

The callback now passes the terminal pairing state to the Activity. A successful
state reloads the persisted bond, updates Compose state, and uses the same
activation path as cold startup: install the bond-dependent providers and GATT
factory, observe CDM associations, start the foreground service, and schedule the
watchdog. Failed pairing and missing records do not activate a connection.

Regression coverage: `MainActivityPairingTest` persists a bond while the original
Activity remains alive, completes pairing, and checks Home's state, the signing
alias provider, and the service start. Separate cases cover failed pairing with a
partially persisted record and success without a record. Existing pairing state
machine tests cover the CDM association result.

Implementation: `syauth-android/app/src/main/kotlin/com/sy/syauth/android/MainActivity.kt`.

## Physical Pixel verification

Verified on 2026-10-08 with the Pixel 8 Pro (Android 16) and the Arch/KDE laptop.
After installing the updated APK without clearing app data, the existing app bond
record was backed up and temporarily moved aside so Home began unpaired. The
existing Android Keystore signing key and system Bluetooth bond were preserved.
The desktop daemon was stopped and `syauth pair --timeout-secs 300 --force` ran
against the phone's normal pairing UI. The four-word confirmations matched and
were approved on both devices.

Tapping Done immediately displayed the new host name and pairing timestamp on
Home and started `SyauthCompanionService` in the foreground. Both the phone process
ID and the Android ActivityRecord remained unchanged from before pairing to after
Done. The desktop daemon was then started; the phone connected and subscribed
without reopening or restarting the app. The first connection took about 40
seconds after the desktop daemon started. A private test of the real PAM module
returned `PAM_SUCCESS` after the user approved the Pixel fingerprint. Headphones
remained connected. Temporary phone bond backups were removed after success.

This tests app-level pairing completion while reusing the existing system
Bluetooth bond; initial six-digit Bluetooth pairing was verified separately during
installation. It does not require deleting unrelated pairings or resetting the
Bluetooth adapter.
