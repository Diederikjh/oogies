# Build through tools/build_release.py: its tar context contains only listed inputs.
FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587 AS runtime-base
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates python3 tzdata ffmpeg libuuid1 libssl3 libasound2 libx11-6 \
    && rm -rf /var/lib/apt/lists/*

FROM runtime-base AS builder
RUN apt-get update && apt-get install -y --no-install-recommends g++ libc6-dev unzip \
    && rm -rf /var/lib/apt/lists/*
COPY sdk.zip /build/sdk.zip
RUN echo '8de553fb2e8dbb0ac441ee1bd73c5ecb73d720c1359396750479a6e169abf93f  /build/sdk.zip' | sha256sum -c - \
    && unzip -q /build/sdk.zip -d /build \
    && mv /build/EN-HCNetSDKV6.1.9.48_build20230410_linux64 /sdk \
    && rm /build/sdk.zip
COPY native/ /build/native/
RUN g++ -std=c++17 -D_LINUX_ -I/sdk/incEn -I/sdk/QtDemo/includeCn \
    /build/native/live_grid.cpp -L/sdk/lib -Wl,-rpath,/sdk/lib \
    -lhcnetsdk -lPlayCtrl -lpthread -ldl -o /build/cam-sdk-grid \
    && strip --strip-unneeded /build/cam-sdk-grid

FROM runtime-base AS release
ARG APP_VERSION
ARG SOURCE_REVISION
LABEL org.opencontainers.image.title="Oogies" \
    org.opencontainers.image.version=$APP_VERSION \
    org.opencontainers.image.revision=$SOURCE_REVISION \
    org.opencontainers.image.source="https://github.com/Diederikjh/oogies" \
    oogies.sdk-profile="hcnet-6.1.9.48-linux64"
COPY --from=builder /sdk/lib/ /sdk/lib/
COPY --from=builder /sdk/doc/*.txt /sdk/notices/
COPY --from=builder /build/cam-sdk-grid /opt/oogies/bin/cam-sdk-grid
COPY app/ /probe/
COPY support/ /support/
COPY web/ /web/
COPY vendor-README.md /opt/oogies/vendor/README.md
COPY release.json /opt/oogies/release.json
RUN mkdir -p /configuration /credentials /output /exports \
    && chown 65532:65532 /output /exports
ENV PYTHONPATH=/support:/probe PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    OOGIES_LIVE_BRIDGE=/opt/oogies/bin/cam-sdk-grid
USER 65532:65532
WORKDIR /sdk/lib
EXPOSE 8088
CMD ["python3", "/probe/grid_server.py"]
