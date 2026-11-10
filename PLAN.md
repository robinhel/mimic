# copycheck – plan

**Mål:** Ta reda på om det hade lönat sig att kopiera Polymarkets bästa traders på Kalshi, *med fördröjning och avgifter*. Inga riktiga pengar. Programmet läser bara data.

**Svaret vi vill ha:** "Hade du kopierat trader X med 2 minuters fördröjning hade du gått +/− Y % efter avgifter."

---

## 1. De viktigaste ändringarna jämfört med första idén

**1. Backtest först, livetest sedan.**
Vi behöver inte vänta i veckor. Polymarket har historik för varje plånbok, och Kalshi har prishistorik per minut. Då kan vi räkna på månader bakåt direkt. Livetestet blir en kontroll av att backtestet räknar rätt.

**2. Välj traders utan att fuska.**
Tar vi dagens topplista och testar på samma traders historik så fuskar vi. De är ju med på listan *för att* det gick bra. Lösning: välj traders på data från en *tidigare* period och testa på en *senare* period.

**3. Testa flera fördröjningar.**
Vi räknar med 30 sekunder, 2 minuter och 10 minuter. Då ser vi hur snabbt vinsten försvinner.

**4. Bara exakta matchningar räknas.**
Två frågor med nästan samma titel kan avgöras olika. Matchningen måste jämföra *reglerna*, inte bara titlarna.

---

## 2. Luckor jag hittade och hur vi löser dem

### API och data

| # | Lucka | Lösning |
|---|---|---|
| 1 | Polymarket **Data API v1 stängdes 24 oktober 2026**. De flesta guider och AI-exempel på nätet använder v1 (`/trades?offset=`). | Använd **bara `/v2/...`**. Paginering med `cursor`, aldrig `offset` (ger fel 400). Svaren ligger i `data` och har snake_case. |
| 2 | `/v2/trades` har `taker_only=true` som standard. Traders som lägger limit-order **syns inte**. | Använd `/v2/activity?user=...&type=TRADE` för varje plånbok, eller sätt `taker_only=false`. |
| 3 | Polymarkets data har en egen fördröjning. | Läs `/v2/status` (`lag_seconds`). Spara **två tider** per affär: när den hände och när vi såg den. |
| 4 | Polymarket kan ge `429` (för många anrop). | Vänta så länge `Retry-After` säger. Backoff i en gemensam HTTP-klient. |
| 5 | Kalshi delar upp data i **live** och **historik**. Gamla avgjorda marknader finns bara under `/historical/...`. | Läs `GET /historical/cutoff` och välj endpoint efter datum. |
| 6 | Kalshis orderbok visar bara **bud** (bids). Det finns inga asks direkt. | `yes_ask = 1 − bästa no_bid`. Gör det i **en** hjälpfunktion med test, för gör man fel här blir allt baklänges. |
| 7 | Orderboken kräver kanske inloggning (dokumentationen säger emot sig själv). | Använd fälten `yes_ask`/`yes_bid` från `/markets` som reserv. |
| 8 | Kalshi har två bas-URL:er i olika källor (`api.elections.kalshi.com` och `external-api.kalshi.com`). | Lägg bas-URL:en i config och testa den i fas 0. |
| 9 | Kalshis gräns för anrop (Basic: 20 läsningar/s, räknat i "tokens"). | Håll oss långt under, max ~5 anrop/s. Hämta många marknader per anrop. |

### Vilka traders ska vi följa?

| # | Lucka | Lösning |
|---|---|---|
| 10 | Topplistan visar bara läget **nu**. | Bygg en egen ranking: hämta stängda positioner för ~500 kandidater och räkna vinst *per period* själv. |
| 11 | Många på topplistan är **bottar eller market makers**. De köper och säljer hela tiden och tjänar på skillnaden mellan köp- och säljpris, inte på att gissa rätt. Sådant går inte att kopiera. | Filtrera bort plånböcker som handlar på båda sidor i samma marknad, som gör väldigt många affärer per dag, eller som har mycket liten vinst per affär. |
| 12 | Hög "win rate" kan vara falsk (köper kontrakt för 95¢). | Ranka på **ROI och vinst per affär**, inte win rate. Krav: minst 50 avgjorda marknader. |

### Vilka affärer ska vi kopiera?

| # | Lucka | Lösning |
|---|---|---|
| 13 | Ett köp delas ofta upp i många små fyllningar. | Slå ihop till en **signal**: samma plånbok + samma marknad + samma sida inom 10 minuter. |
| 14 | Små köp är brus. | Bara signaler över en minsta summa (default **$250**). |
| 15 | Vad gör vi när tradern **säljer**? | Testa två strategier: **A** håll till avgörande, **B** sälj när tradern säljer. |
| 16 | Hur mycket "köper" vi? | Fast summa per signal (default **$10**). `kontrakt = floor(summa / pris)`. |
| 17 | Priset kan ha sprungit iväg. | Strategivariant: hoppa över om Kalshis pris är mer än **X cent** sämre än traderns pris. |

### Matchning Polymarket ↔ Kalshi

| # | Lucka | Lösning |
|---|---|---|
| 18 | Titlarna skiljer sig, och samma titel kan ha olika regler (källa, datum, tidszon, gränsvärde). | Steg 1: hitta kandidater med text-likhet. Steg 2: låt **Groq** jämföra *reglerna* (Kalshi `rules_primary`, Polymarkets beskrivning) och svara `exact` / `near` / `related` / `none`, plus **vilken sida** som motsvarar vilken. |
| 19 | YES på ena sidan kan motsvara NO på den andra. | Matchningen sparar `side_map` (t.ex. PM "Yes" → Kalshi "no"). |
| 20 | Polymarket har frågor med flera alternativ, Kalshi har en marknad per alternativ. | Matcha på **alternativ-nivå** (en Polymarket-token ↔ en Kalshi-ticker). |
| 21 | AI:n kan ha fel. | Spara matchningar i databasen (varje par körs bara en gång). Gör ett litet CLI där du granskar de första ~50 för hand och mäter träffsäkerheten. |
| 22 | Många Polymarket-frågor finns inte alls på Kalshi. | Rapportera **täckning**: hur stor andel av signalerna som gick att kopiera. Det är ett resultat i sig. |
| 23 | Färdiga tjänster för matchning finns (Predexon, Prediction Hunt), men kostar eller har kvot. | Bygg egen först. Jämför eventuellt med Prediction Hunts gratisnivå. |

### Simulering och resultat

| # | Lucka | Lösning |
|---|---|---|
| 24 | Vilket pris hade vi fått? | Backtest: Kalshis `yes_ask` (minutdata) vid *tid vi såg affären + fördröjning*. Live: spara orderboken i samma sekund. |
| 25 | Minutdata visar inte hur mycket som går att köpa till det priset. | Lägg på antagen slippage (default 1¢). Livetestet visar om antagandet håller. |
| 26 | Avgifter. | Kalshi: `round_up(0.07 × C × P × (1−P))` per order. Test: 100 kontrakt à $0.55 = **$1.74**. Ingen avgift vid avgörande. |
| 27 | Frågor som avgörs om ett år. | Visa dem som "öppna" och värdera dem med nuvarande `yes_bid`. |
| 28 | Kalshi och Polymarket kan avgöras **olika**. | Flagga det som `resolution_mismatch`. Intressant att räkna. |
| 29 | Tur eller skicklighet? | Kräv minst ~200 signaler innan vi drar slutsatser. Visa ett osäkerhetsintervall (bootstrap). |
| 30 | Vad jämför vi med? | Två jämförelser: (1) traderns eget resultat på Polymarket, (2) samma köp på Kalshi **utan** fördröjning. Skillnaden visar exakt vad fördröjningen kostar. |

### Drift (livetestet)

| # | Lucka | Lösning |
|---|---|---|
| 31 | Programmet måste köra dygnet runt. | Kör på VM:en som **systemd-tjänst** med automatisk omstart. |
| 32 | Om programmet ligger nere missar vi priset i rätt ögonblick. | Varje körning skriver en "heartbeat". Affärer som upptäcks sent markeras `late=true` och räknas separat. |
| 33 | Tidszoner. | Allt sparas i **UTC**. Svensk tid bara i rapporten. |
| 34 | Databasen kan gå sönder. | SQLite med WAL-läge, plus en daglig backup-fil. |
| 35 | API-nyckel för Groq. | `.env` (står i `.gitignore`), med `.env.example` i repot. |

### Hittat vid test av API:erna (2026-11-10)

| # | Lucka | Lösning |
|---|---|---|
| 36 | Kalshis candlesticks finns bara för perioder med handel (en lugn marknad hade 8 dagliga candles på ~50 dagar). | Använd senaste `yes_ask` före tidpunkten (batch-endpointen har `include_latest_before_start`). Är priset äldre än 15 min markeras signalen `stale` och räknas separat. |
| 37 | Kalshis `/markets` fylls av kombinationsmarknader (`KXMVE...`, tomma regler). | Filtrera bort dem. Kolla om det finns en filterparameter. |
| 38 | Kalshi-priser är text i `*_dollars`-fält, antal i `*_fp`. Polymarket skickar flyttal med brus. | Tolka med `Decimal` i en hjälpfunktion per API. |
| 39 | Topplistans etta (månad) handlar "Bitcoin upp/ner 5 minuter", alltså en bot. | Uteslut också marknader som stänger inom 1 timme efter signalen. |

---

## 3. Faser

Varje fas ska fungera och vara testad innan nästa börjar.

### Fas 0 – Grund (liten)
- Repo, `pyproject.toml`, ruff, pytest, `.env.example`, `CLAUDE.md`
- Ett "röktest"-skript som anropar varje endpoint en gång och skriver ut svaret:
  - Polymarket: `/v2/status`, `/v2/leaderboard`, `/v2/activity`, `/v2/positions?status=CLOSED`
  - Kalshi: `/markets`, `/historical/cutoff`, candlesticks för en marknad
- **Klart när:** alla anrop svarar och JSON-exempel ligger sparade i `tests/fixtures/`.

### Fas 1 – Polymarket-insamling
- Hämta ~500 kandidater (topplistor `month` + `all`, både PNL och VOLUME)
- Hämta deras aktivitet och stängda positioner till databasen
- Botfilter (lucka 11)
- **Klart när:** `copycheck collect` fyller tabellerna och kan köras igen utan dubbletter.

### Fas 2 – Kalshi-katalog
- Hämta alla marknader (öppna + historiska) med regler och resultat
- **Klart när:** marknaderna går att söka på i databasen.

### Fas 3 – Matchning
- Kandidatsökning → Groq-bedömning → spara i `matches`
- `copycheck review` för granskning för hand
- **Klart när:** träffsäkerheten för `exact` är mätt på minst 50 par.

### Fas 4 – Backtest
- Bygg signaler (lucka 13–14)
- Ranka traders på **träningsperioden** (default 90 dagar)
- Simulera på **testperioden** (de 60 dagarna efter) för varje fördröjning × strategi
- **Klart när:** `copycheck backtest` skriver resultat till `sim_trades`.

### Fas 5 – Rapport → BESLUTSPUNKT
- Tabell per trader, fördröjning, strategi och kategori: ROI, antal signaler, täckning, snitt-slippage
- **Beslut:** Är resultatet tydligt negativt efter fördröjning? Då är svaret klart, och projektet har gjort sitt jobb. Är det positivt? Gå vidare till fas 6.

### Fas 6 – Livetest (pappershandel)
- Poller var 30:e sekund för de utvalda traders
- Spara Kalshis orderbok i samma ögonblick som en signal upptäcks
- Kör i 3–4 veckor och jämför med backtestets antaganden
- **Klart när:** systemd-tjänsten har gått en vecka utan avbrott.

### Fas 7 – Extra (valfritt)
- Notiser (t.ex. Telegram eller ntfy)
- Enkel dashboard
- **Ingen kod som handlar på riktigt.** Det ligger utanför projektet.

---

## 4. Datamodell (SQLite)

| Tabell | Innehåll |
|---|---|
| `traders` | plånbok, namn, källa (vilken topplista), botflagga |
| `pm_activity` | rå affär: plånbok, condition, token, sida, pris, storlek, `trade_ts`, `seen_ts` |
| `signals` | ihopslagna köp: plånbok, token, sida, snittpris, summa, första/sista tid |
| `pm_markets` | condition, token, titel, beskrivning, kategori, resultat |
| `kalshi_markets` | ticker, event, titel, regler, stängningstid, resultat |
| `matches` | pm_token ↔ kalshi_ticker, nivå (`exact`/`near`/…), `side_map`, AI-motivering, granskad (ja/nej) |
| `kalshi_quotes` | ticker, tid, yes_bid, yes_ask, källa (`candle`/`orderbook`) |
| `sim_trades` | signal, strategi, fördröjning, inpris, kontrakt, avgift, utpris, resultat |
| `heartbeats` | tid, komponent, status |

---

## 5. Mappstruktur

```
copycheck/
├── CLAUDE.md
├── PLAN.md
├── pyproject.toml
├── .env.example
├── src/copycheck/
│   ├── http.py          # gemensam klient: backoff, 429, loggning
│   ├── polymarket.py    # bara v2-endpoints
│   ├── kalshi.py        # live + historical, yes_ask-hjälpare
│   ├── db.py            # schema + frågor
│   ├── signals.py       # slå ihop fyllningar → signaler
│   ├── ranking.py       # botfilter + ranking per period
│   ├── matching.py      # kandidater + Groq-bedömning
│   ├── fees.py          # Kalshis avgiftsformel
│   ├── backtest.py
│   ├── live.py
│   ├── report.py
│   └── cli.py           # collect / match / review / backtest / live / report
└── tests/
    ├── fixtures/        # sparade JSON-svar, inga nätanrop i tester
    └── test_*.py
```

---

## 6. Beslut du behöver ta (med mina förslag)

| Fråga | Förslag |
|---|---|
| Summa per signal | $10 |
| Fördröjningar att testa | 30 s, 2 min, 10 min |
| Tränings-/testperiod | 90 dagar / 60 dagar |
| Minsta signal | $250 |
| Antagen slippage i backtest | 1¢ |
| Matchning | Egen med Groq först |
| Var livetestet körs | VM:en |

---

## 7. Inte med i projektet

- Riktig handel eller inloggning på Kalshi
- Att lagra något om traders utöver publika plånboksdata
- Att sälja tjänsten till andra
