from ._zb_response import ZBResponse


class ZBScoreEmailResponse(ZBResponse):
    """Response for GET/POST /scoring (real-time AI scoring)."""

    email: str = None
    score: int = None
