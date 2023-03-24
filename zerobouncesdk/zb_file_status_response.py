from ._zb_response import ZBFileResponse


class ZBFileStatusResponse(ZBFileResponse):
    """This is the response for the GET /filestatus request."""

    file_id: str = None

    file_name: str = None

    upload_date: str = None

    file_status: str = None

    complete_percentage: str = None

    error_reason: str = None

    return_url: str = None
