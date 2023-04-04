from datetime import datetime

from ._zb_response import ZBFileResponse


class ZBFileStatusResponse(ZBFileResponse):
    """This is the response for the GET /filestatus request."""

    file_id: str = None

    file_name: str = None

    upload_date: datetime = None

    file_status: str = None

    complete_percentage: str = None

    error_reason: str = None

    return_url: str = None

    def __init__(self, data):
        super().__init__(data)
        if self.upload_date is not None:
                self.upload_date = datetime.strptime(self.upload_date, "%Y-%m-%dT%H:%M:%SZ")

