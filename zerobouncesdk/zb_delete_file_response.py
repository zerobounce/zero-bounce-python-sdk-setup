from zerobouncesdk._zb_response import ZBResponse


class ZBDeleteFileResponse(ZBResponse):
    success: bool = False

    message: str = None

    fileName: str = None

    fileId: str = None
