from enum import Enum


class ZBValidateStatus(Enum):
    """The model class that lists all the possible statuses of the email validation result."""
    
    valid = "valid"
    invalid = "invalid"
    catch_all = "catch-all"
    unknown = "unknown"
    spamtrap = "spamtrap"
    abuse = "abuse"
    do_not_mail = "do_not_mail"
