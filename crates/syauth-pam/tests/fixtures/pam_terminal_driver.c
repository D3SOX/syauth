/* Private libpam driver. The caller supplies a disposable configuration tree. */
#include <security/pam_appl.h>
#include <security/pam_ext.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int converse(int count, const struct pam_message **messages,
                    struct pam_response **responses, void *data)
{
    struct pam_response *reply = calloc(count, sizeof(*reply));
    if (reply == NULL) return PAM_BUF_ERR;
    for (int i = 0; i < count; i++) {
        if (messages[i]->msg_style != PAM_PROMPT_ECHO_OFF) continue;
        fputs(messages[i]->msg, stdout);
        fflush(stdout);
        char password[PAM_MAX_RESP_SIZE];
        if (fgets(password, sizeof(password), stdin) == NULL) {
            for (int j = 0; j < i; j++) free(reply[j].resp);
            free(reply);
            return PAM_CONV_ERR;
        }
        password[strcspn(password, "\n")] = '\0';
        reply[i].resp = strdup(password);
        explicit_bzero(password, sizeof(password));
        if (reply[i].resp == NULL) {
            for (int j = 0; j < i; j++) free(reply[j].resp);
            free(reply);
            return PAM_BUF_ERR;
        }
    }
    *responses = reply;
    return PAM_SUCCESS;
}

int main(int argc, char **argv)
{
    if (argc != 2) return 2;
    struct pam_conv conversation = {converse, NULL};
    pam_handle_t *handle = NULL;
    int result = pam_start_confdir("syauth-terminal-test", "nico", &conversation, argv[1], &handle);
    if (result == PAM_SUCCESS) {
        /* sudo enables PAM_SILENT during ordinary interactive authentication. */
        result = pam_authenticate(handle, PAM_SILENT);
        pam_end(handle, result);
    }
    printf("RESULT:%d\n", result);
    return result == PAM_SUCCESS ? 0 : 1;
}
