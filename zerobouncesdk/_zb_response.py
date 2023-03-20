
class ZBResponse(object):
    def __init__(self, data=None):
        self.__dict__ = data

    def __str__(self) -> str:
        return str(self.__class__.__name__) + "=" + str(self.__dict__)
