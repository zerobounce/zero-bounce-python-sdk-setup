class ZBException(Exception):
    pass


class ZBApiException(ZBException):
    pass


class ZBClientException(ZBException):
    pass


class ZBMissingApiKeyException(ZBException):
    pass
