/* Private test module. It captures syauth's real return code and checks
 * whether a later password module can reuse the submitted credential. */
#include <dlfcn.h>
#include <security/pam_modules.h>
#include <security/pam_ext.h>
#include <stdlib.h>
#include <string.h>

int pam_sm_authenticate(pam_handle_t *pamh, int flags, int argc, const char **argv)
{
    if (argc >= 2 && strncmp(argv[0], "module=", 7) == 0) {
        void *module = dlopen(argv[0] + 7, RTLD_NOW | RTLD_LOCAL);
        if (module == NULL) return PAM_AUTH_ERR;
        int (*authenticate)(pam_handle_t *, int, int, const char **) =
            dlsym(module, "pam_sm_authenticate");
        int result = authenticate == NULL ? PAM_AUTH_ERR :
            authenticate(pamh, flags, argc - 2, argv + 2);
        dlclose(module);
        return result == atoi(argv[1]) ? PAM_SUCCESS : PAM_AUTH_ERR;
    }
    if (argc == 0) return PAM_AUTH_ERR;
    if (argc == 2) {
        const void *cached = NULL;
        if (pam_get_item(pamh, PAM_AUTHTOK, &cached) != PAM_SUCCESS ||
            cached != NULL) return PAM_AUTH_ERR;
    }
    const char *token = NULL;
    if (pam_get_authtok(pamh, PAM_AUTHTOK, &token, "Test password: ") != PAM_SUCCESS ||
        token == NULL) return PAM_AUTH_ERR;
    return strcmp(token, argv[0]) == 0 ? PAM_SUCCESS : PAM_AUTH_ERR;
}

int pam_sm_setcred(pam_handle_t *pamh, int flags, int argc, const char **argv)
{
    return PAM_SUCCESS;
}
