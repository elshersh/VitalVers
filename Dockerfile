# Vitalverse web app (FastAPI + scikit-learn model + offline/online chatbot)
# Works on Hugging Face Spaces (Docker SDK), Render and any Docker host.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Hugging Face runs the container as user 1000; the app writes its database, uploads and .env,
# so everything under /app belongs to that user.
RUN useradd -m -u 1000 user
WORKDIR /app

# runtime dependencies only (pytest and playwright are for local testing)
COPY requirements.txt .
RUN grep -v -E '^(pytest|playwright)==' requirements.txt > /tmp/requirements-runtime.txt \
 && pip install -r /tmp/requirements-runtime.txt

COPY --chown=user:user . .
USER user

# served over HTTPS by the host, so session cookies are marked Secure
ENV HOME=/home/user \
    VITALVERSE_COOKIE_SECURE=1 \
    PORT=7860
EXPOSE 7860

CMD ["python", "scripts/render_start.py"]
