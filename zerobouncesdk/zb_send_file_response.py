from ._zb_response import ZBResponse


class ZBSendFileResponse(ZBResponse):
    """This is the response for the POST /sendfile request."""

    success: bool = False

    message: str = None

    file_name: str = None

    file_id: str = None

    def __init__(self, data):
        super().__init__(data)
        if isinstance(self.message, list):
            if len(self.message) > 0:
                self.message = self.message[0]
            else:
                self.message = None
