// Roadmap item S-018 — deep-link to the battery-optimization
// exclusion settings page.
//
// Doze (API 23+) stops the foreground service's BLE connection unless
// syauth is excluded from battery optimization. Clearing the app's
// data drops the exclusion, so the home card checks it on every
// resume and offers this intent when it is missing.
//
// `Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` is API 23+;
// we never need to gate this by SDK because our minSdk is 26.
package com.sy.syauth.android.bg

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.PowerManager
import android.provider.Settings

/** Scheme used to identify the package in the deep-link URI. */
internal const val PACKAGE_URI_SCHEME: String = "package"

/**
 * Build the intent that opens the per-app battery-optimization
 * exclusion dialog. The OS shows a confirmation dialog; user taps
 * Allow to exempt the app.
 *
 * The function is pure (no side effects); callers decide when to
 * fire it (typically once on first launch).
 */
public fun batteryOptimizationDeepLinkIntent(context: Context): Intent {
    val uri = Uri.fromParts(PACKAGE_URI_SCHEME, context.packageName, null)
    return Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).setData(uri)
}

/**
 * Check whether syauth is currently exempt from battery
 * optimization. The home screen calls this to decide whether to pop
 * [batteryOptimizationDeepLinkIntent].
 *
 * Returns `true` when the app is exempt (or when the OS does not
 * support battery optimization, in which case the deep-link is a
 * no-op).
 */
public fun isIgnoringBatteryOptimizations(context: Context): Boolean {
    val pm = context.getSystemService(PowerManager::class.java) ?: return true
    return pm.isIgnoringBatteryOptimizations(context.packageName)
}
