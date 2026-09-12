FROM node:22.22.0-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv python3-pip build-essential curl git \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -m venv /opt/venv

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir ".[web,bedrock]" \
 && reflex compile --no-rich \
 && useradd --create-home --uid 10001 appuser \
 && install -d -m 0755 -o appuser -g appuser /home/appuser/.tradingagents \
 && chown -R appuser:appuser /app

USER appuser
EXPOSE 8501

CMD ["tradingagents"]
