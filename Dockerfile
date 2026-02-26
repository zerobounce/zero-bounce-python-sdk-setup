# ZeroBounce Python SDK – test image (Python 3.12)
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml setup.py ./
COPY src/ src/
RUN pip install --no-cache-dir -e ".[test]"

COPY tests/ tests/

# Unit tests only (no API key); use CMD so it can be overridden
CMD ["python", "-m", "pytest", "tests/zero_bounce_test_case.py", "-v", \
     "--cov=zerobouncesdk", "--cov-report=term-missing", "--cov-fail-under=50"]
