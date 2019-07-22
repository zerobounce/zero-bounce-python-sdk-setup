from zerobouncesdk._zb_response import ZBResponse


class ZBSendFileResponse(ZBResponse):
    success: bool = False

    message: str = None

    fileName: str = None

    fileId: str = None
