from datetime import date, datetime

from ._zb_response import ZBResponse


class ZBGetApiUsageResponse(ZBResponse):
    """This is the response for the GET /apiusage request."""

    total: int = 0
    """Total number of times the API has been called"""

    status_valid: int = 0
    """Total valid email addresses returned by the API"""

    status_invalid: int = 0
    """Total invalid email addresses returned by the API"""

    status_catch_all: int = 0
    """Total catch-all email addresses returned by the API"""

    status_do_not_mail: int = 0
    """Total do not mail email addresses returned by the API"""

    status_spamtrap: int = 0
    """Total spamtrap email addresses returned by the API"""

    status_unknown: int = 0
    """Total unknown email addresses returned by the API"""

    sub_status_toxic: int = 0
    """Total number of times the API has a sub status of toxic"""

    sub_status_disposable: int = 0
    """Total number of times the API has a sub status of disposable"""

    sub_status_role_based: int = 0
    """Total number of times the API has a sub status of role_based"""

    sub_status_possible_trap: int = 0
    """Total number of times the API has a sub status of possible_trap"""

    sub_status_global_suppression: int = 0
    """Total number of times the API has a sub status of global_suppression"""

    sub_status_timeout_exceeded: int = 0
    """Total number of times the API has a sub status of timeout_exceeded"""

    sub_status_mail_server_temporary_error: int = 0
    """Total number of times the API has a sub status of mail_server_temporary_error"""

    sub_status_mail_server_did_not_respond: int = 0
    """Total number of times the API has a sub status of mail_server_did_not_respond"""

    sub_status_greylisted: int = 0
    """Total number of times the API has a sub status of greylisted"""

    sub_status_antispam_system: int = 0
    """Total number of times the API has a sub status of antispam_system"""

    sub_status_does_not_accept_mail: int = 0
    """Total number of times the API has a sub status of does_not_accept_mail"""

    sub_status_exception_occurred: int = 0
    """Total number of times the API has a sub status of exception_occurred"""

    sub_status_failed_syntax_check: int = 0
    """Total number of times the API has a sub status of failed_syntax_check"""

    sub_status_mailbox_not_found: int = 0
    """Total number of times the API has a sub status of mailbox_not_found"""

    sub_status_unroutable_ip_address: int = 0
    """Total number of times the API has a sub status of unroutable_ip_address"""

    sub_status_possible_typo: int = 0
    """Total number of times the API has a sub status of possible_typo"""

    sub_status_no_dns_entries: int = 0
    """Total number of times the API has a sub status of no_dns_entries"""

    sub_status_role_based_catch_all: int = 0
    """Total number of times the API has a sub status of role_based_catch_all"""

    sub_status_mailbox_quota_exceeded: int = 0
    """Total number of times the API has a sub status of mailbox_quota_exceeded"""

    sub_status_forcible_disconnect: int = 0
    """Total number of times the API has a sub status of forcible_disconnect"""

    sub_status_failed_smtp_connection: int = 0
    """Total number of times the API has a sub status of failed_smtp_connection"""

    sub_status_mx_forward: int = 0
    """Total number of times the API has a sub status of mx_forward"""

    sub_status_alternate: int = 0
    """Total number of times the API has a sub status of alternate"""

    sub_status_allowed: int = 0
    """Total number of times the API has a sub status of allowed"""

    sub_status_blocked: int = 0
    """Total number of times the API has a sub status of blocked"""

    start_date: date = None
    """Start date of query"""

    end_date: date = None
    """End date of query"""

    def __init__(self, data):
        super().__init__(data)
        if self.start_date is not None:
            self.start_date = datetime.strptime(self.start_date, "%m/%d/%Y").date()
        if self.end_date is not None:
            self.end_date = datetime.strptime(self.end_date, "%m/%d/%Y").date()
