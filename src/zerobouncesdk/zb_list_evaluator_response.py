from ._zb_response import ZBResponse


class ZBListEvaluatorResponse(ZBResponse):
    """Response for POST /listevaluator/ and GET /listevaluator/{file_id}/."""

    file_id: str = None

    status: str = None
    """``processing`` until the evaluation is done, then ``finished``."""

    progress: int = None
    """0 to 100."""

    invalid_percentage: float = None

    catch_all_percentage: float = None

    activity_data_percentage: float = None

    abuse: bool = None
    """Whether abuse addresses were found."""

    do_not_mail: bool = None
    """Whether do-not-mail addresses were found."""

    spam_trap: bool = None
    """Whether spam traps were found."""

    total_risky_percentage: float = None

    error_message: str = None
