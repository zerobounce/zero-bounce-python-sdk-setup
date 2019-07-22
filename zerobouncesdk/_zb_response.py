import json


class ZBResponse(object):
    def __init__(self, j=None):
        if j is not None:
            self.__dict__ = json.loads(j)

    def __str__(self) -> str:
        return str(self.__class__.__name__) + "=" + str(self.__dict__)
