from ._zb_response import ZBFileResponse


class ZBGetFileResponse(ZBFileResponse):
    """This is the response for the GET /getfile request."""

    success: bool = True

    local_file_path: str = None

    # Built by the SDK from the downloaded file, never from JSON.
    _SDK_FIELDS = ("local_file_path",)
