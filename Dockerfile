# ==============================================================================
# VerbaClear Standalone Offline Appliance Dockerfile
# Multi-stage build producing an air-gapped container image
# ==============================================================================

FROM python:3.12-slim AS base

# System audio dependencies for PortAudio and ALSA
RUN apt-get update && apt-get install -y --no-install-recommends \
    portaudio19-dev \
    alsa-utils \
    libasound2 \
    libasound2-plugins \
    libgomp1 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir . && \
    python -m spacy download en_core_web_sm

# Copy full application codebase and offline models
COPY . .

# Pre-cache CTranslate2 faster-whisper tiny.en model offline inside the container image
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('tiny.en', device='cpu', compute_type='int8')"

# Run built-in self-diagnostics during image build to guarantee integrity
RUN python -m src.interfaces.cli diagnose

EXPOSE 8000

ENV PYTHONUNBUFFERED=1 \
    PORT=8000 \
    HOST=0.0.0.0

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1

ENTRYPOINT ["python", "-m", "src.interfaces.cli"]
CMD ["start", "--host", "0.0.0.0", "--port", "8000"]
