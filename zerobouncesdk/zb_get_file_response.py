from ._zb_response import ZBResponse


class ZBGetFileResponse(ZBResponse):
    """This is the response for the GET /getfile request."""

    local_file_path: str = None

    success: bool = True

    message: str = None
