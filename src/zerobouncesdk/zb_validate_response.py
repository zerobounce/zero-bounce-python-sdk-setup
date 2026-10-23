from datetime import datetime

from . import ZBValidateStatus, ZBValidateSubStatus
from ._zb_response import ZBResponse
from ._zb_utils import parse_bool, parse_datetime, safe_enum_convert


class ZBValidateResponse(ZBResponse):
    """This is the response for the GET /validate request."""

    address: str = None
    """The email address you are validating."""

    status: ZBValidateStatus = None
    """one of [valid, invalid, catch-all, unknown, spamtrap, abuse, do_not_mail]"""

    sub_status: ZBValidateSubStatus = None
    """one of [antispam_system, greylisted, mail_server_temporary_error, forcible_disconnect,
    mail_server_did_not_respond, timeout_exceeded, failed_smtp_connection, mailbox_quota_exceeded,
    exception_occurred, possible_trap, role_based, global_suppression, mailbox_not_found, no_dns_entries,
    failed_syntax_check, possible_typo, unroutable_ip_address, leading_period_removed, does_not_accept_mail,
    alias_address, role_based_catch_all, disposable, toxic, alternate, mx_forward, blocked, allowed, accept_all,
    role_based_accept_all, gold, ai_agent_mailbox]"""

    account: str = None
    """The portion of the email address before the "@" symbol."""

    domain: str = None
    """The portion of the email address after the "@" symbol."""

    did_you_mean: str = None
    """Suggestive Fix for an email typo"""

    domain_age_days: str = None
    """Age of the email domain in days or [null]."""

    active_in_days: str = None
    """Last activity bucket when activity_data was requested (e.g. 30, 365+)."""

    active_first_seen: str = None
    """First date activity was detected (YYYY-MM-DD)."""

    free_email: bool = False
    """[true/false] If the email comes from a free provider."""

    mx_found: bool = False
    """[true/false] Does the domain have an MX record."""

    mx_record: str = None
    """ The preferred MX record of the domain"""

    smtp_provider: str = None
    """The SMTP Provider of the email or [null] [BETA]."""

    catchall_domain: bool = None
    """[true/false or null] Is the domain name a catch-all (the domain email server responds with valid to any SMTP checks and emailing to an invalid might not bounce)?"""

    firstname: str = None
    """The first name of the owner of the email when available or [null]."""

    lastname: str = None
    """The last name of the owner of the email when available or [null]."""

    gender: str = None
    """The gender of the owner of the email when available or [null]."""

    city: str = None
    """The city of the IP passed in or [null]"""

    region: str = None
    """The region/state of the IP passed in or [null]"""

    zipcode: str = None
    """The zipcode of the IP passed in or [null]"""

    country: str = None
    """The country of the IP passed in or [null]"""

    processed_at: datetime = None
    """The UTC time the email was validated."""

    domain_website_exists: str = None
    """With domain_info: whether the domain has a website ("True", "False" or "unchecked")."""

    domain_registrant_company_name: str = None
    """With domain_info: the WHOIS registrant company, "Registrant info not found" or "unchecked"."""

    message: str = None
    """Set instead of a result while greylist processing is still running; call validate again later."""

    def __init__(self, data):
        super().__init__(data)
        if self.message is None and isinstance(self.__dict__.get("Message"), str):
            self.message = self.__dict__["Message"]
        self.status = safe_enum_convert(ZBValidateStatus, self.status, "status")
        self.sub_status = safe_enum_convert(ZBValidateSubStatus, self.sub_status, "sub_status")
        for flag in ("free_email", "mx_found", "catchall_domain"):
            if flag in self.__dict__:
                setattr(self, flag, parse_bool(self.__dict__[flag]))
        self.processed_at = parse_datetime(
            self.processed_at, ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"), "processed_at"
        )
