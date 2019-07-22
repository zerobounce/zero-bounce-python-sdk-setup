from zerobouncesdk._zb_response import ZBResponse


class ZBGetApiUsageResponse(ZBResponse):
    total: int = 0
    status_valid: int = 0
    status_invalid: int = 0
    status_catch_all: int = 0
    status_do_not_mail: int = 0
    status_spamtrap: int = 0
    status_unknown: int = 0
    sub_status_toxic: int = 0
    sub_status_disposable: int = 0
    sub_status_role_based: int = 0
    sub_status_possible_trap: int = 0
    sub_status_global_suppression: int = 0
    sub_status_timeout_exceeded: int = 0
    sub_status_mail_server_temporary_error: int = 0
    sub_status_mail_server_did_not_respond: int = 0
    sub_status_greylisted: int = 0
    sub_status_antispam_system: int = 0
    sub_status_does_not_accept_mail: int = 0
    sub_status_exception_occurred: int = 0
    sub_status_failed_syntax_check: int = 0
    sub_status_mailbox_not_found: int = 0
    sub_status_unroutable_ip_address: int = 0
    sub_status_possible_typo: int = 0
    sub_status_no_dns_entries: int = 0
    sub_status_role_based_catch_all: int = 0
    sub_status_mailbox_quota_exceeded: int = 0
    sub_status_forcible_disconnect: int = 0
    sub_status_failed_smtp_connection: int = 0
    start_date: str = None
    end_date: str = None