from typing import Optional


class ZBGetFileOptions:
    """Optional query parameters for bulk getfile.

    ``activity_data`` applies to validation ``get_file`` only; ``scoring_get_file`` does not send it.
    """

    def __init__(
        self,
        download_type: Optional[str] = None,
        activity_data: Optional[bool] = None,
    ):
        self.download_type = download_type
        self.activity_data = activity_data
