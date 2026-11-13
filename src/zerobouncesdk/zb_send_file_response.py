from ._zb_response import STRING, ZBFileResponse


class ZBSendFileResponse(ZBFileResponse):
    """This is the response for the POST /sendfile request."""

    file_name: str = None

    file_id: str = None

    _FIELD_TYPES = {**ZBFileResponse._FIELD_TYPES, "file_name": STRING, "file_id": STRING}
