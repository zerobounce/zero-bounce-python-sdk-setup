from enum import Enum


class ZBApiUrl(Enum):
    """Enumeration of available ZeroBounce API base URLs."""
    
    API_DEFAULT_URL = "https://api.zerobounce.net/v2/"
    API_USA_URL = "https://api-us.zerobounce.net/v2/"
    API_EU_URL = "https://api-eu.zerobounce.net/v2/"

