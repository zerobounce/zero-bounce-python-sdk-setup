# ZeroBounce Python SDK – test image (Python 3.14, as in the SDK CI matrix)
FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f

WORKDIR /app

COPY pyproject.toml setup.py ./
COPY src/ src/
RUN pip install --no-cache-dir -e ".[test]"

COPY tests/ tests/

# Every offline suite (no API key, no network); use CMD so it can be overridden.
# The suite writes fixture files and .coverage into the working directory, so the
# non-root test user owns /app.
RUN chown -R 65532:65532 /app

USER 65532:65532

CMD ["python", "-m", "pytest", "-v", \
     "--cov=zerobouncesdk", "--cov-report=term-missing", "--cov-fail-under=50"]
