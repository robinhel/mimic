# Mimic

Mimic asks a simple question: can you make money by copying the trades of the best Polymarket players, after delays and fees?

Dashboard: https://robinhel.github.io/mimic/
Source: https://github.com/robinhel/mimic

The project was previously called copycheck.

<!-- Add a screenshot of the dashboard here when docs/screenshot.png exists. -->

## Results

The first test was a backtest. It copied Polymarket players onto matching Kalshi markets, with delays and Kalshi fees. It ran 81,384 simulated trades across 4 delays and 3 strategies. The main setup, a 2 minute delay and holding to settlement, returned -13.2% after fees on 1,816 trades. That approach was dropped.

The second test followed players live on Polymarket itself, with paper money. Live tests 1 to 3 ran on 15 and 16 November 2026 and the wide test on 17 November. The biggest one, live test 3, followed 48 players. 6 of them made buys, which gave 23 copied buys, and 20 of them were settled. It returned -8.5% before fees and -10.6% after fees. The live ROI counts every buy from all followed players. Open buys are valued at the current market price. That is a very small sample from about one day, so it says little either way.

A third check, test15, was not live. A script went back over 16 to 23 November 2026 and bought after the fact by the robot's rules, from a cash box of 100 dollars. The cash box ended between +2.8% and +3.6%, depending on the delay (5, 30 or 120 seconds), with open buys valued at the market price. With a 30 second delay it made 35 buys, and 18 of them were still open at the end. This is a change of the whole cash box, not ROI per buy, so it cannot be compared directly with the live numbers.

That is far too little data for a conclusion. A handful of settled markets can swing the result either way, and live tests that ran for a day or two, plus one week of replay, say nothing about how the players do over time. The honest answer so far is: not proven.

## How it works

- Build a ranking of Polymarket players from their past closed positions, and filter out bots and market makers.
- Pick players on an earlier period and test them on a later period, so the selection does not cheat.
- Watch the chosen players' trades on the Polygon blockchain. The goal is to see each trade within 0 to 2 seconds. In live test 3 the measured median was 18 seconds.
- Record what a copy would have cost against the live order book, then follow each position until the market settles.
- Export the results to JSON for the dashboard.

## Tech

- Python 3.12, managed with uv, with requests, sqlite3 and pytest.
- Polymarket Data API v2, Gamma API and order books, and the Kalshi trade API for the backtest.
- Groq for matching market rules between Polymarket and Kalshi.
- A static dashboard built with Vite and React, deployed to GitHub Pages.

## Running it

Install and look at the command line tool:

```
uv sync
uv run mimic --help
```

Run the live paper test. DATADIR holds players.json with the players to follow:

```
uv run python scripts/pm_livetest.py run DATADIR
```

Export data for the dashboard. OUTDIR should be `dashboard/public/data`. Commit the files there, because GitHub Pages only shows what is committed:

```
uv run python scripts/export_dashboard.py dashboard/public/data --live DATADIR \
    --run NAME=DATADIR --db mimic.db --robot-api
```

`--live` is the live test shown as the headline number on the dashboard, currently the largest one (live test 3). If a `--run` has the same folder, its name is shown as the title of the live run. Each `--run` adds one test run to the ROI chart, and a folder without signals is skipped. `--db` adds the Kalshi backtest. `--robot` adds the robot log. It must point to a folder where the robot has only run with `--live`, otherwise the export stops. `--robot-api` instead fetches the robot's real buys, sells and redeems from Polymarket's public Data API. It reads the robot's address only from `POLYMARKET_WALLET_ADDRESS` in your local `.env`, stops if it is missing, and never prints or writes the address. Skips exist only in the robot's own log, so they are not shown with `--robot-api`. `--robot` and `--robot-api` cannot be used together. Without either, the export removes an old `robot.json`. The export also stops if it finds a wallet address or a secret.

`replay.json` is not made by the export. It is written by hand from the test15 result, and the export leaves it alone.

Run the dashboard locally:

```
cd dashboard && npm ci && npm run dev
```

Run the tests:

```
uv run pytest -q
```

## Safety

Everything except one script only reads public data. The exception is `scripts/pm_robot.py`, which can place real orders on Polymarket. It is a dry run by default and only trades with `--live`. It has hard limits: at most 5 dollars per buy, a bank of about 100 dollars, at most 40 open buys, no buy if the price has moved more than 5 cents, and no buys at all while a file named STOP exists in its folder.

Keys are only read from a local `.env` file. That file is listed in `.gitignore` and is never committed. See `.env.example` for the variable names.

## Disclaimer

This is a research project only. It is not financial advice. Polymarket is not available in every country, so check the rules where you live.

## License

MIT, see `LICENSE`.
