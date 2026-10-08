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
