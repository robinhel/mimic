# copycheck

copycheck asks a simple question: can you make money by copying the trades of the best Polymarket players, after delays and fees?

Dashboard: https://robinhel.github.io/copycheck/

<!-- Screenshot goes here. The file docs/screenshot.png will be added later. -->
![copycheck dashboard](docs/screenshot.png)

## Results

The first test was a backtest. It copied Polymarket players onto matching Kalshi markets, with delays and Kalshi fees. Over 81,384 simulated trades it lost about 13%. That approach was dropped.

The second test followed players live on Polymarket itself. The test ran from 16 to 23 November 2026 with paper money. It made about +3% on 35 buys, but only 11 of them were settled when the test ended.

That is far too little data for a conclusion. A handful of settled markets can swing the result either way, and one week says nothing about how the players do over time. The honest answer so far is: not proven.

## How it works

- Build a ranking of Polymarket players from their past closed positions, and filter out bots and market makers.
- Pick players on an earlier period and test them on a later period, so the selection does not cheat.
- Watch the chosen players' trades on the Polygon blockchain, within 0 to 2 seconds of each trade.
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
uv run copycheck --help
```

Run the live paper test. DATADIR holds players.json with the players to follow:

```
python scripts/pm_livetest.py run DATADIR
```

Export data for the dashboard and run it locally:

```
python scripts/export_dashboard.py OUTDIR --live DATADIR
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
