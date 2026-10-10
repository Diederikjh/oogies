FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git openssh-client && rm -rf /var/lib/apt/lists/*
# Official amd64 release; checksum published by git-lfs/git-lfs.
RUN curl --fail --location --retry 2 --output /tmp/git-lfs.tar.gz \
      https://github.com/git-lfs/git-lfs/releases/download/v3.8.0/git-lfs-linux-amd64-v3.8.0.tar.gz \
    && echo 'e455e00f15d9b95661b8d53498ffb0c3367962cf1ec73c31ab7369516cd6ab8d  /tmp/git-lfs.tar.gz' | sha256sum --check \
    && tar -xzf /tmp/git-lfs.tar.gz -C /tmp \
    && install -m 0755 /tmp/git-lfs-3.8.0/git-lfs /usr/local/bin/git-lfs \
    && rm -rf /tmp/git-lfs.tar.gz /tmp/git-lfs-3.8.0
WORKDIR /repo
ENTRYPOINT ["git-lfs"]
