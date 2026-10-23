# ZeroBounce Python SDK – test image (Python 3.12)
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml setup.py ./
COPY src/ src/
RUN pip install --no-cache-dir -e ".[test]"

COPY tests/ tests/

# Every offline suite (no API key, no network); use CMD so it can be overridden

USER 65532:65532

CMD ["python", "-m", "pytest", "-v", \
     "--cov=zerobouncesdk", "--cov-report=term-missing", "--cov-fail-under=50"]
