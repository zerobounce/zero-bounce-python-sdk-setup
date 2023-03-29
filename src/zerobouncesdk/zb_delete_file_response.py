from ._zb_response import ZBFileResponse


class ZBDeleteFileResponse(ZBFileResponse):
    """This is the response for the GET /deletefile request."""

    file_name: str = None

    file_id: str = None
