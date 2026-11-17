#!/usr/bin/env bash
# Gordongecko / SILAS: build a PAPER-ONLY desk workspace from this repo.
# Usage: bash scripts/paper_setup.sh <start_cash_usd> [baseline_date YYYY-MM-DD]
# Creates the historical /workspace layout the helpers expect, writes a paper config
# (executionMode=paper, liveMode.armed=false), and resets the paper broker book.
set -euo pipefail
CASH="${1:?start cash in USD}"; BDATE="${2:-$(TZ=America/New_York date +%F)}"
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(dirname "$HERE")"
DATA=/workspace/robinhood-fable-agent/data/equity-paper
CFG=/workspace/robinhood-fable-agent/config/equity-morning-session.json
mkdir -p /workspace/robinhood-fable-agent/config "$DATA/paper-mode" "$DATA/raw" /workspace/equity-am-desk/live /workspace/equity-am-desk/kb /workspace/journal
ln -sfn "$HERE" /workspace/paper
python3 - "$REPO/config/example-config.json" "$CFG" "$CASH" "$BDATE" <<'EOF'
import json, sys
src, dst, cash, bdate = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
s = open(src).read()
for k, v in {"${DESK_DATA}": "/workspace/robinhood-fable-agent/data/equity-paper", "${DESK_ROOT}": "/workspace/equity-am-desk",
             "${HELPERS_DIR}": "/workspace/paper", "${KB_DIR}": "/workspace/equity-am-desk/kb", "${DESK_CONFIG}": dst}.items():
    s = s.replace(k, v)
c = json.loads(s)
c["executionMode"] = "paper"
c["liveMode"]["armed"] = False
c["liveMode"].setdefault("autoSwitchAtOpen", {})["enabled"] = False
c["liveMode"]["note"] = "DISARMED: paper workspace built by scripts/paper_setup.sh. Only Kevin can arm live."
c["paperMode"]["startCashUsd"] = cash
c["bankStop"]["baselineUsd"] = cash
c["bankStop"]["baselineDate"] = bdate
json.dump(c, open(dst, "w"), indent=1)
EOF
export TZ=America/New_York RECONCILE_CONFIG="$CFG"
python3 "$HERE/paper_broker.py" reset --cash "$CASH" --force
python3 "$HERE/paper_guard.py" mode
python3 "$HERE/paper_guard.py" check-call --tool place_equity_order || true
echo "Paper desk ready. export TZ=America/New_York RECONCILE_CONFIG=$CFG BROKER_ACCOUNT_NUMBER=<agentic account>"
