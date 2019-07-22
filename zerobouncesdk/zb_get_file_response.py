from zerobouncesdk._zb_response import ZBResponse


class ZBGetFileResponse(ZBResponse):
    localFilePath: str = None
