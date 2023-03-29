from ._zb_response import ZBFileResponse


class ZBSendFileResponse(ZBFileResponse):
    """This is the response for the POST /sendfile request."""

    file_name: str = None

    file_id: str = None
