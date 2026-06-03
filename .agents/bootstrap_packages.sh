#!/usr/bin/env bash
# Install sandbox Python packages by tier. Safe to re-run; skips tiers already marked done.
set -euo pipefail

AGENTS_DIR="${AGENTS_DIR:-/workspace/.agents}"
MARKER_DIR="${MARKER_DIR:-/workspace/.sandbox_packages}"

install_tier() {
    local tier="$1"
    local req_file="${AGENTS_DIR}/requirements-tier${tier}.txt"
    local marker="${MARKER_DIR}/tier${tier}.done"

    if [[ -f "$marker" ]]; then
        echo "Tier ${tier} already installed."
        return 0
    fi

    if [[ ! -f "$req_file" ]]; then
        echo "Missing requirements file: ${req_file}" >&2
        return 1
    fi

    echo "Installing Tier ${tier} packages..."
    pip install -q -r "$req_file"
    mkdir -p "$MARKER_DIR"
    touch "$marker"
    echo "Tier ${tier} installation complete."
}

usage() {
    echo "Usage: bootstrap_packages.sh [1|2|3|4|all]" >&2
}

main() {
    local target="${1:-1}"

    case "$target" in
        1)
            install_tier 1
            ;;
        2)
            install_tier 1
            install_tier 2
            ;;
        3)
            install_tier 1
            install_tier 3
            ;;
        4)
            install_tier 1
            install_tier 4
            ;;
        all)
            for tier in 1 2 3 4; do
                install_tier "$tier"
            done
            ;;
        *)
            usage
            exit 1
            ;;
    esac
}

main "$@"
