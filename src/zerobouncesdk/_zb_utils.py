"""Utility functions for ZeroBounce SDK."""

import warnings


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
