from ._zb_response import INT, STRING, ZBResponse


class ZBScoreEmailResponse(ZBResponse):
    """Response for GET/POST /scoring (real-time AI scoring)."""

    email: str = None
    score: int = None

    _FIELD_TYPES = {"email": STRING, "score": INT}
