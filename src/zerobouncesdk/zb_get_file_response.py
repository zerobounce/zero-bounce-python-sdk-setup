from ._zb_response import ZBFileResponse


class ZBGetFileResponse(ZBFileResponse):
    """This is the response for the GET /getfile request."""

    success: bool = True

    local_file_path: str = None
