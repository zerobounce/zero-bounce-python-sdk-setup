from enum import Enum


class ZBConfidence(Enum):
    """The model class that lists all the possible confidence values for a
    `guess format` result.
    """
    high = "high"
    medium = "medium"
    low = "low"
    unknown = "unknown"
    undetermined = "undetermined"
