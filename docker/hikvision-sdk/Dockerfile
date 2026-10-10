FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587 AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates python3 g++ libc6-dev libuuid1 libssl3 libasound2 libx11-6 \
    ffmpeg unzip curl && rm -rf /var/lib/apt/lists/*
WORKDIR /work

FROM runtime AS download-browser
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium chromium-driver python3-selenium && rm -rf /var/lib/apt/lists/*
