from datetime import datetime

from ._zb_response import STRING, ZBFileResponse


class ZBFileStatusResponse(ZBFileResponse):
    """This is the response for the GET /filestatus request."""

    file_id: str = None

    file_name: str = None

    upload_date: datetime = None

    file_status: str = None

    file_phase_2_status: str = None

    complete_percentage: str = None

    error_reason: str = None

    return_url: str = None

    _FIELD_TYPES = {
        **ZBFileResponse._FIELD_TYPES,
        "file_id": STRING, "file_name": STRING, "upload_date": STRING, "file_status": STRING,
        "file_phase_2_status": STRING, "complete_percentage": STRING, "error_reason": STRING, "return_url": STRING,
    }

    def __init__(self, data):
        super().__init__(data)
        if self.upload_date is not None:
                self.upload_date = datetime.strptime(self.upload_date, "%Y-%m-%dT%H:%M:%SZ")

