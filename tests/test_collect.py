import json
from pathlib import Path

from mimic import cli, db

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


class RoutingClient:
    def __init__(self):
        self.calls = []

    def get_json(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        if url.endswith("/leaderboard"):
            return load("pm_leaderboard")
        if url.endswith("/activity"):
            return load("pm_activity")
        return load("pm_positions_closed")


def test_collect_fyller_tabellerna_och_kan_koras_igen():
    conn = db.connect(":memory:")
    client = RoutingClient()
    for _ in range(2):
        cli.collect(client, conn, per_list=5, days=150, now=1794311314, log=lambda *a: None)
    n_traders = conn.execute("SELECT COUNT(*) FROM traders").fetchone()[0]
    assert n_traders == len(load("pm_leaderboard")["data"])
    assert conn.execute("SELECT COUNT(*) FROM pm_activity").fetchone()[0] == len(
        load("pm_activity")["data"]
    )
    # 4 topplistor slås ihop till en källa-lista per trader.
    sources = conn.execute("SELECT sources FROM traders LIMIT 1").fetchone()[0]
    assert sources == "all:PNL,all:VOLUME,month:PNL,month:VOLUME"
    assert (
        conn.execute("SELECT COUNT(*) FROM traders WHERE collected_ts IS NULL").fetchone()[0] == 0
    )


def test_collect_hamtar_bara_nya_affarer_andra_gangen():
    conn = db.connect(":memory:")
    client = RoutingClient()
    cli.collect(client, conn, per_list=5, days=150, now=1794311314, log=lambda *a: None)
    client.calls.clear()
    cli.collect(client, conn, per_list=5, days=150, now=1794311314, log=lambda *a: None)
    starts = {p["user"]: p["start"] for u, p in client.calls if u.endswith("/activity")}
    wallet = load("pm_activity")["data"][0]["proxy_wallet"]
    assert starts[wallet] == max(r["timestamp"] for r in load("pm_activity")["data"])
    assert min(starts.values()) == 1794311314 - 150 * 86400


def test_hoppar_over_positioner_nar_aktiviteten_ar_avkortad():
    conn = db.connect(":memory:")
    client = RoutingClient()
    act = load("pm_activity")
    act["pagination"]["next_cursor"] = "mer"
    client.get_json = lambda url, params=None, orig=client.get_json: (
        act if url.endswith("/activity") else orig(url, params)
    )
    cli.collect(
        client, conn, per_list=5, days=150, now=1794311314, log=lambda *a: None, max_pages=1
    )
    assert conn.execute("SELECT COUNT(*) FROM pm_positions").fetchone()[0] == 0
    assert conn.execute("SELECT MIN(is_bot) FROM traders").fetchone()[0] == 1
