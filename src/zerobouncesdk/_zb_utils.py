"""Utility functions for ZeroBounce SDK."""

import warnings
from datetime import datetime


def safe_enum_convert(enum_class, value, field_name="field", lowercase=False):
    """Safely convert a value to an enum, handling unknown values gracefully.
    
    Parameters
    ----------
    enum_class : Enum
        The enum class to convert to
    value : str or None
        The value to convert
    field_name : str
        Name of the field for error messages
    lowercase : bool
        Whether to lowercase the value before conversion (default: False)
        
    Returns
    -------
    Enum or None
        The enum value if conversion succeeds, None if value is None or conversion fails
    """
    if value is None:
        return None
    
    # Handle case-insensitive conversion if requested
    if lowercase and isinstance(value, str):
        value = value.lower()
    
    try:
        return enum_class(value)
    except ValueError:
        # Unknown enum value - log warning but don't crash
        warnings.warn(
            f"Unknown {field_name} value '{value}' received from API. "
            f"This may indicate the SDK is out of date. Please update zerobouncesdk. "
            f"Falling back to None.",
            UserWarning,
            stacklevel=3
        )
        return None


def parse_bool(value):
    """A flag from the API as a bool, or None.

    The API documents some flags as JSON booleans and shows others as "true"/"false" strings.
    True/False, "true"/"false" in any case, and 1/0 (or "1"/"0") are booleans; anything else
    (such as "unknown") is None, so it is never mistaken for true.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return value == 1
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1"):
            return True
        if lowered in ("false", "0"):
            return False
    return None


def parse_datetime(value, formats, field_name="field"):
    """Parse ``value`` with the first matching format; keep the original string (with a warning) if none match."""
    if value is None or not isinstance(value, str):
        return value
    for fmt in formats:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    warnings.warn(
        f"Unexpected {field_name} format '{value}' received from API; keeping the original string.",
        UserWarning,
        stacklevel=3,
    )
    return value
