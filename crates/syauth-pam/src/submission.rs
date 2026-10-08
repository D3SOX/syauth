//! Select phone authentication using a submitted empty password.

use std::{ffi::c_char, ptr};

use pam_sys::{PamHandle, PamItemType, raw::pam_set_item};

use crate::entry::{PAM_AUTH_ERR, PAM_IGNORE, PAM_SUCCESS};

// pam-sys 0.5 supplies the PAM types but omits this Linux-PAM extension.
#[link(name = "pam")]
unsafe extern "C" {
    fn pam_get_authtok(pamh: *mut PamHandle, item: i32, authtok: *mut *const c_char, prompt: *const c_char) -> i32;
}

/// Return `Ok(())` only after an actual empty submission. A typed password
/// stays in PAM_AUTHTOK for the password module and returns PAM_IGNORE.
/// Conversation errors never select phone authentication.
///
/// # Safety
/// `pamh` must be a live handle owned by libpam during module authentication.
pub(crate) unsafe fn request_phone(pamh: *mut PamHandle) -> Result<(), i32> {
    if pamh.is_null() {
        return Err(PAM_AUTH_ERR);
    }
    let mut token = ptr::null();
    // SAFETY: the handle is live, token is a writable out-pointer, and the
    // prompt is a static NUL-terminated string. libpam owns the returned token.
    let result = unsafe {
        pam_get_authtok(
            pamh,
            PamItemType::AUTHTOK as i32,
            &mut token,
            c"Password, or press Enter to use your phone: ".as_ptr(),
        )
    };
    if result != PAM_SUCCESS || token.is_null() {
        return Err(PAM_AUTH_ERR);
    }
    // SAFETY: successful pam_get_authtok returned a non-null C string that
    // remains valid until we change the item. Only its first byte is read.
    if unsafe { *token } != 0 {
        return Err(PAM_IGNORE);
    }
    // Clear the empty selector before requesting the phone. If the phone
    // fails, a password module can prompt again rather than retrying it.
    // SAFETY: the handle is live and libpam defines a null item as clearing
    // PAM_AUTHTOK. We do not access token after this invalidates it.
    let result = unsafe { pam_set_item(pamh, PamItemType::AUTHTOK as i32, ptr::null()) };
    if result != PAM_SUCCESS {
        return Err(PAM_AUTH_ERR);
    }
    Ok(())
}
