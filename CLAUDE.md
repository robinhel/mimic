# CLAUDE.md – Mimic

(tidigare copycheck)

Läs `PLAN.md` först. Bygg **en fas i taget**, i ordning. Gå inte vidare förrän fasens "Klart när" är uppfyllt.

## Regler

- **Bara läsning.** Ingen kod som lägger order eller loggar in på Kalshi eller Polymarket.
  - Undantag (Robins beslut 2026-11-16): `scripts/pm_robot.py` får lägga order på Polymarket,
    bara med `--live`, bara från en plånbok med Robins 1000 kr och med robotens tak (5 $ per köp,
    ca 100 $ totalt, STOP-filen). Ingen annan kod får lägga order.
- **Polymarket Data API: bara v2** (`https://data-api.polymarket.com/v2/...`). v1 är nedlagt sedan 2026-10-24.
  - Paginering med `cursor` (följ `pagination.next_cursor`). Skicka aldrig `offset` eller `market`.
  - Svaren ligger i `data` och har snake_case.
  - Använd `/v2/activity` (eller `taker_only=false`) så att limit-order kommer med.
- **Kalshi:** bas-URL i config, default `https://external-api.kalshi.com/trade-api/v2`
  (`api.elections.kalshi.com` gav fel på `/markets` i testet, ha den som reserv).
  Använd `/historical/...` för data före `GET /historical/cutoff`.
  - `yes_ask = 1 - best_no_bid`. Använd alltid hjälpfunktionen i `kalshi.py`.
  - Priser är strängar i `*_dollars`-fält (`"0.9900"`), antal i `*_fp`-fält. Tolka med `Decimal`.
    Det finns inga `yes_bid`/`yes_ask` utan suffix.
  - Candlesticks saknas för perioder utan handel. Använd senaste kända pris före
    tidpunkten och spara hur gammalt det är.
  - Filtrera bort kombinationsmarknader (ticker börjar med `KXMVE`).
- **Polymarket:** priser är flyttal med brus (`0.4900001785`). Avrunda till 4 decimaler.
- **Polymarket Gamma** (`gamma-api.polymarket.com`) ger frågetext, regler och resultat.
  Stängda marknader kommer bara med `closed=true`.
- **Kalshi candlesticks:** använd batch-endpointen `/markets/candlesticks` även för historik.
  Den historiska endpointen har andra fältnamn.
- **Avgift:** `round_up(0.07 * C * P * (1 - P))` till hel cent. Test: 100 st à 0.55 → 1.74.
- Alla tider sparas i **UTC** (unix-sekunder eller ISO med `Z`).
- Alla HTTP-anrop går via `http.py` (backoff, respektera `Retry-After`, max ~5 anrop/s mot Kalshi).
- Tester använder sparade JSON-filer i `tests/fixtures/`, aldrig riktiga nätanrop.
- Hemligheter i `.env`, aldrig i koden.

## Verktyg

- Python 3.12+, `requests`, `sqlite3`, `groq`
- `ruff check . && ruff format .` och `pytest` ska gå igenom innan commit.

## Om något i API:t inte stämmer med planen

Stanna och skriv vad som skiljer sig. Gissa inte fältnamn: kolla ett riktigt svar först.
