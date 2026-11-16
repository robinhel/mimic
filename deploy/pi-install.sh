#!/usr/bin/env bash
# Flyttar livetestet och robotens torrkörning till Raspberry Pi:n. Körs från Macen.
#
#   deploy/pi-install.sh robin@robot.local DATADIR ROBOTDIR [DB]
#
# DATADIR har players.json, fills.jsonl och events.jsonl. ROBOTDIR har state.json.
# Den stora databasen (8 GB) flyttas inte. I stället skrivs en liten seed.db med spelarnas
# innehav: en rad per spelare och svar, med samma tabell som livetestet läser vid start.
# .env kopieras aldrig: robotens nyckel läggs in för hand på Pi:n.
set -euo pipefail
HOST=$1 DATA=$2 ROBOT=$3 DB=${4:-/Volumes/SSD/copycheck.noindex/copycheck.db}
REPO=$(cd "$(dirname "$0")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

"$REPO/.venv/bin/python" -I - "$DB" "$DATA/players.json" "$TMP/seed.db" <<'EOF'
import json, sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?immutable=1", uri=True)
wallets = [p["wallet"] for p in json.load(open(sys.argv[2]))]
ph = ",".join("?" * len(wallets))
rows = src.execute(
    f"""SELECT wallet, token_id, SUM(CASE side WHEN 'BUY' THEN size ELSE -size END),
               (SELECT MAX(trade_ts) FROM pm_activity b WHERE b.wallet = a.wallet)
        FROM pm_activity a WHERE wallet IN ({ph}) GROUP BY wallet, token_id""", wallets).fetchall()
dst = sqlite3.connect(sys.argv[3])
dst.execute("""CREATE TABLE pm_activity (wallet TEXT, token_id TEXT, side TEXT, size REAL,
               trade_ts INTEGER)""")
dst.executemany("INSERT INTO pm_activity VALUES (?, ?, 'BUY', ?, ?)", rows)
dst.commit()
print(f"seed.db: {len(rows)} innehav för {len(wallets)} spelare")
EOF

ssh "$HOST" 'mkdir -p ~/copycheck ~/pm_livetest ~/pm_robot'
rsync -a --delete --exclude .venv --exclude .env --exclude '*.db' --exclude '.*_cache' \
  --exclude __pycache__ "$REPO/" "$HOST:copycheck/"
rsync -a "$TMP/seed.db" "$HOST:copycheck/seed.db"
rsync -a "$DATA/players.json" "$DATA/fills.jsonl" "$DATA/events.jsonl" "$HOST:pm_livetest/"
rsync -a "$ROBOT/state.json" "$HOST:pm_robot/"

ssh "$HOST" bash -s <<'EOF'
set -euo pipefail
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
cd ~/copycheck && ~/.local/bin/uv sync --python python3
curl -s https://polymarket.com/api/geoblock; echo
# Användartjänster: ingen sudo behövs. linger gör att de startar när Pi:n startar.
loginctl enable-linger "$USER"
mkdir -p ~/.config/systemd/user
for s in pm-livetest pm-robot; do
  sed "s|@HOME@|$HOME|g" deploy/$s.service > ~/.config/systemd/user/$s.service
done
systemctl --user daemon-reload
systemctl --user enable --now pm-livetest pm-robot
EOF
echo "Klart. Följ loggen: ssh $HOST journalctl --user -u pm-livetest -u pm-robot -f"
