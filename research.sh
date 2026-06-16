#!/usr/bin/env bash
# Research Workstation — Three-step automated pipeline
#
# Step 1: Sentinel capture (news/anomaly/sentiment via Gemini)
# Step 2: Qlib inference (quantitative prediction)
# Step 3: Data aggregation (Bayesian fusion — must succeed)
#
# Usage:
#   ./research.sh                              # Full pipeline, default symbols
#   ./research.sh --symbols 600519,000001      # Custom symbols
#   ./research.sh --skip-sentinel              # Skip Step 1
#   ./research.sh --skip-qlib                  # Skip Step 2
#   ./research.sh --skip-sentinel --skip-qlib  # Pure degradation mode (tech only)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
PYTHON="${PROJECT_ROOT}/.venv/bin/python"
LOG_DIR="${PROJECT_ROOT}/workspace/logs"
DATE=$(date +%Y-%m-%d)
LOG_FILE="${LOG_DIR}/research_${DATE}.log"

# Defaults
SYMBOLS=""
SKIP_SENTINEL=false
SKIP_QLIB=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --symbols)
            SYMBOLS="$2"
            shift 2
            ;;
        --skip-sentinel)
            SKIP_SENTINEL=true
            shift
            ;;
        --skip-qlib)
            SKIP_QLIB=true
            shift
            ;;
        -h|--help)
            echo "Usage: ./research.sh [--symbols SYM1,SYM2] [--skip-sentinel] [--skip-qlib]"
            echo ""
            echo "Options:"
            echo "  --symbols         Comma-separated stock codes (default: from config)"
            echo "  --skip-sentinel   Skip Gemini sentinel capture"
            echo "  --skip-qlib       Skip Qlib inference"
            echo "  -h, --help        Show this help"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Create log directory
mkdir -p "$LOG_DIR"

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    echo "$msg" | tee -a "$LOG_FILE"
}

log "=== Research Workstation Pipeline Start ==="
log "Date: ${DATE}"
log "Skip Sentinel: ${SKIP_SENTINEL}"
log "Skip Qlib: ${SKIP_QLIB}"
[ -n "$SYMBOLS" ] && log "Symbols: ${SYMBOLS}"

SYMBOL_ARG=""
[ -n "$SYMBOLS" ] && SYMBOL_ARG="--symbols ${SYMBOLS}"

# ──────────────────────────────────────────────────────────
# Step 1: Sentinel Capture
# ──────────────────────────────────────────────────────────
if [ "$SKIP_SENTINEL" = false ]; then
    log "Step 1: Sentinel capture starting..."
    if $PYTHON -c "
from src.data.sentinel_capture import SentinelCapture
symbols = '${SYMBOLS}'.split(',') if '${SYMBOLS}' else None
symbols = [s.strip() for s in symbols] if symbols and symbols[0] else None
capture = SentinelCapture()
result = capture.capture(symbols)
print(f'Captured {len(result.get(\"symbols\", []))} symbols, fallback={result.get(\"fallback_used\", True)}')
" >> "$LOG_FILE" 2>&1; then
        log "Step 1: Sentinel capture DONE"
    else
        log "Step 1: Sentinel capture FAILED (logged, continuing)"
    fi
else
    log "Step 1: Sentinel capture SKIPPED"
fi

# ──────────────────────────────────────────────────────────
# Step 2: Qlib Inference
# ──────────────────────────────────────────────────────────
if [ "$SKIP_QLIB" = false ]; then
    log "Step 2: Qlib inference starting..."
    if $PYTHON scripts/qlib_inference.py $SYMBOL_ARG >> "$LOG_FILE" 2>&1; then
        log "Step 2: Qlib inference DONE"
    else
        log "Step 2: Qlib inference FAILED (logged, continuing)"
    fi
else
    log "Step 2: Qlib inference SKIPPED"
fi

# ──────────────────────────────────────────────────────────
# Step 3: Data Aggregation (must succeed)
# ──────────────────────────────────────────────────────────
log "Step 3: Data aggregation starting..."
if $PYTHON scripts/data_aggregator.py $SYMBOL_ARG --date "$DATE" >> "$LOG_FILE" 2>&1; then
    log "Step 3: Data aggregation DONE"
else
    log "Step 3: Data aggregation FAILED — pipeline aborted"
    exit 1
fi

log "=== Research Workstation Pipeline Complete ==="
log "Signal output: workspace/signals/research_signal_${DATE}.json"
log "Log file: ${LOG_FILE}"
