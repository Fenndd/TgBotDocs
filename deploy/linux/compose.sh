#!/bin/sh
# Validate public image references for every command, from any working directory.
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
: "${LLAMA_CPP_IMAGE:?Set the reviewed llama.cpp base reference}"
: "${TGBOTDOCS_APP_IMAGE:?Set the verified application image reference}"

require_digest() {
    printf '%s\n' "$1" | grep -Eq '^[a-z0-9][a-zA-Z0-9./:_-]*@sha256:[0-9a-f]{64}$'
}
require_local_tag() {
    printf '%s\n' "$1" | grep -Eq '^local/[a-z0-9][a-z0-9./_-]*:[A-Za-z0-9][A-Za-z0-9_.-]*$'
}

if ! require_digest "$LLAMA_CPP_IMAGE"; then
    if [ "${ALLOW_UNPINNED_LLAMA_CPP_IMAGE:-0}" != 1 ] || ! require_local_tag "$LLAMA_CPP_IMAGE"; then
        echo 'LLAMA_CPP_IMAGE requires a complete sha256 digest; reviewed local builds need explicit opt-in.' >&2
        exit 2
    fi
fi
if ! require_digest "$TGBOTDOCS_APP_IMAGE"; then
    if [ "${ALLOW_LOCAL_APP_IMAGE:-0}" != 1 ] || ! require_local_tag "$TGBOTDOCS_APP_IMAGE"; then
        echo 'TGBOTDOCS_APP_IMAGE requires a complete sha256 digest; local validation images need explicit opt-in.' >&2
        exit 2
    fi
fi
case "${1:-}" in
    build) if [ "${ALLOW_LOCAL_APP_IMAGE:-0}" != 1 ]; then
        echo 'Build to a local validation tag first; production uses the verified application manifest digest.' >&2
        exit 2
    fi ;;
esac

# Explicit public env-file prevents loading an unrelated cwd/checkout .env.
# Keep relative contexts and init-script mounts based at this Compose directory.
if [ "${ALLOW_LOCAL_APP_IMAGE:-0}" != 1 ]; then
    exec docker compose --env-file "$script_dir/compose.env" --project-directory "$script_dir" \
        --file "$script_dir/compose.yaml" --file "$script_dir/compose.production.yaml" "$@"
fi
exec docker compose --env-file "$script_dir/compose.env" --project-directory "$script_dir" \
    --file "$script_dir/compose.yaml" "$@"
