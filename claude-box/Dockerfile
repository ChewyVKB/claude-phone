FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git jq less nano procps openssh-client tzdata \
      tmux sox ffmpeg \
      python3 python3-venv \
 && rm -rf /var/lib/apt/lists/*

# ttyd (browser terminal): static binary from its GitHub releases
ARG TTYD_VERSION=1.7.7
RUN arch="$(uname -m)" \
 && curl -fsSL -o /usr/local/bin/ttyd "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.${arch}" \
 && chmod +x /usr/local/bin/ttyd \
 && ttyd --version

# Speech: faster-whisper (speech-to-text) and Piper (text-to-speech), in their own venv
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/venv/bin/pip install --no-cache-dir faster-whisper piper-tts

# Non-root user (uid 1000) that runs Claude Code
RUN useradd -m -u 1000 -s /bin/bash claude

COPY app/ /opt/claude-phone/
COPY templates/ /opt/claude-phone/templates/
COPY entrypoint.sh start.sh /opt/claude-phone/
RUN chmod +x /opt/claude-phone/*.sh /opt/claude-phone/*.py

ENV HOME=/home/claude \
    PATH=/home/claude/.local/bin:/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    HF_HOME=/data/hf \
    SPOOL_DIR=/spool
WORKDIR /workspace

# Starts as root only to fix folder ownership, then drops to uid 1000
ENTRYPOINT ["/opt/claude-phone/entrypoint.sh"]
