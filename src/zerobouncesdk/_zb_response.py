
class ZBResponse(object):
    def __init__(self, data=None):
        self.__dict__ = data

    def __str__(self) -> str:
        return str(self.__class__.__name__) + "=" + str(self.__dict__)


class ZBFileResponse(ZBResponse):
    success: bool = False

    message: str = None

    def __init__(self, data):
        super().__init__(data)
        if isinstance(self.message, list) and len(self.message) > 0:
            self.message = self.message[0]
        if isinstance(self.success, str):
            if self.success == "True":
                self.success = True
            elif self.success == "False":
                self.success = False
