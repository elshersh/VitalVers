# Vitalverse web app (FastAPI + scikit-learn model + offline/online chatbot)
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# runtime dependencies only (pytest and playwright are for local testing)
COPY requirements.txt .
RUN grep -v -E '^(pytest|playwright)==' requirements.txt > /tmp/requirements-runtime.txt \
 && pip install -r /tmp/requirements-runtime.txt

COPY . .

# the site is served over HTTPS on the host, so session cookies are marked Secure
ENV VITALVERSE_COOKIE_SECURE=1 \
    PORT=10000
EXPOSE 10000

CMD ["python", "scripts/render_start.py"]
