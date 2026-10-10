#!/bin/sh
# Keep stdout clean: Git filters exchange their data over stdin/stdout.
set -eu
repo=$(git rev-parse --show-toplevel)
exec docker run --rm -i --read-only \
    --user "$(id -u):$(id -g)" --cap-drop=ALL \
    --security-opt=no-new-privileges --cpus=1 \
    --memory=512m --memory-swap=512m --pids-limit=128 \
    --tmpfs /tmp:rw,nosuid,size=64m \
    --mount "type=bind,source=$repo,target=/repo" \
    --workdir /repo --env GIT_CONFIG_GLOBAL=/dev/null \
    --env GIT_CONFIG_NOSYSTEM=1 --env GIT_CONFIG_COUNT=3 \
    --env GIT_CONFIG_KEY_0=filter.lfs.clean --env 'GIT_CONFIG_VALUE_0=git-lfs clean -- %f' \
    --env GIT_CONFIG_KEY_1=filter.lfs.smudge --env 'GIT_CONFIG_VALUE_1=git-lfs smudge -- %f' \
    --env GIT_CONFIG_KEY_2=filter.lfs.process --env 'GIT_CONFIG_VALUE_2=git-lfs filter-process' \
    cam-git-lfs:local "$@"
