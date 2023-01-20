from zerobouncesdk._zb_response import ZBResponse
from zerobouncesdk.zb_validate_status import ZBValidateStatus
from zerobouncesdk.zb_validate_sub_status import ZBValidateSubStatus


class ZBValidateResponse(ZBResponse):
    """This is the response for the validate API"""

    address: str = None
    """The email address you are validating."""

    status: ZBValidateStatus = None
    """one of [valid, invalid, catch-all, unknown, spamtrap, abuse, do_not_mail]"""

    sub_status: ZBValidateSubStatus = None
    """one of [antispam_system, greylisted, mail_server_temporary_error, forcible_disconnect, 
    mail_server_did_not_respond, timeout_exceeded, failed_smtp_connection, mailbox_quota_exceeded, 
    exception_occurred, possible_trap, role_based, global_suppression, mailbox_not_found, no_dns_entries, 
    failed_syntax_check, possible_typo, unroutable_ip_address, leading_period_removed, does_not_accept_mail, 
    alias_address, role_based_catch_all, disposable, toxic, alternate, mx_forward] """

    account: str = None
    """The portion of the email address before the "@" symbol."""

    domain: str = None
    """The portion of the email address after the "@" symbol."""

    did_you_mean: str = None
    """Suggestive Fix for an email typo"""

    domain_age_days: str = None
    """Age of the email domain in days or [null]."""

    free_email = False
    """[true/false] If the email comes from a free provider."""

    mx_found = False
    """[true/false] Does the domain have an MX record."""

    mx_record: str = None
    """ The preferred MX record of the domain"""

    smtp_provider: str = None
    """The SMTP Provider of the email or [null] [BETA]."""

    firstname: str = None
    """The first name of the owner of the email when available or [null]."""

    lastname: str = None
    """The last name of the owner of the email when available or [null]."""

    gender: str = None
    """The gender of the owner of the email when available or [null]."""

    city: str = None
    """The city of the IP passed in."""

    region: str = None
    """The region/state of the IP passed in."""

    zipcode: str = None
    """The zipcode of the IP passed in."""

    country: str = None
    """The country of the IP passed in."""

    processed_at: str = None
    """The UTC time the email was validated."""

    error: str = None

    def __init__(self, j):
        super().__init__(j)
        self.status = None if self.status is None else ZBValidateStatus(self.status)
        self.sub_status = None if self.sub_status is None else ZBValidateSubStatus(self.sub_status)



