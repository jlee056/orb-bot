#!/usr/bin/env bash
# Trusted standard-library validator: one new date, or reconciliation of pending rows.
# Final history and entry/signal facts are immutable; no secret-holding code runs here.
set -euo pipefail
python3 paper_log.py validate "$1" "$2" "$3"
