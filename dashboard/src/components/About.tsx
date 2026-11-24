import { Card } from "./ui";

const STACK = [
  { name: "Python 3.12", text: "All collection, simulation and reports" },
  { name: "SQLite", text: "Trades, markets and prices" },
  { name: "Polygon RPC", text: "OrderFilled events, 0–2 s after a trade" },
  { name: "Polymarket Data API v2", text: "Trader history and activity" },
  { name: "Polymarket Gamma", text: "Questions, rules and outcomes" },
  { name: "Kalshi API", text: "Prices and candlesticks for the backtest" },
  { name: "Groq", text: "LLM that matches Polymarket and Kalshi questions" },
  { name: "React + Recharts", text: "This dashboard, built from JSON exports" },
];

const LEARNED = [
  "Copying with a delay on another exchange loses money: the Kalshi backtest returned about −13 % after fees.",
  "Speed matters. Reading the chain directly gives the signal in 0–2 seconds instead of about 8 minutes.",
  "Fees and slippage decide the result, so every copy is priced against the real order book, not the trader's price.",
  "Few settled buys means wide error bars. A small positive result is a reason to keep testing, not proof.",
];

export default function About() {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card title="Built with">
        <ul className="grid gap-2 sm:grid-cols-2">
          {STACK.map((s) => (
            <li key={s.name} className="rounded-lg border border-zinc-800 bg-zinc-950/60 px-3 py-2">
              <span className="block text-sm text-zinc-100">{s.name}</span>
              <span className="block text-xs text-zinc-400">{s.text}</span>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="What I learned">
        <ul className="grid gap-3 text-sm leading-relaxed text-zinc-400">
          {LEARNED.map((l) => (
            <li key={l} className="flex gap-3">
              <span className="mt-2 size-1.5 shrink-0 rounded-full bg-zinc-500" />
              <span>{l}</span>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Not financial advice" className="md:col-span-2">
        <p className="text-sm leading-relaxed text-zinc-400">
          copycheck is a research project. The live test trades on paper only; the robot buys with a small, capped amount to check the paper
          results against reality. Past results say little about the future, and prediction markets can lose you all of your stake.
          Nothing on this page is a recommendation to trade.
        </p>
        <p className="mt-3 text-sm text-zinc-400">
          Source code:{" "}
          <a className="text-emerald-400 underline-offset-2 hover:underline" href="https://github.com/robinhel/copycheck">
            github.com/robinhel/copycheck
          </a>
        </p>
      </Card>
    </div>
  );
}
