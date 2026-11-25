import { int, pct } from "../format";
import type { Data } from "../types";
import { Card } from "./ui";

const STACK = [
  { name: "Python 3.12", text: "All collection, simulation and reports" },
  { name: "SQLite", text: "Trades, markets and prices" },
  { name: "Polygon RPC", text: "OrderFilled events, aiming at 0–2 s after a trade" },
  { name: "Polymarket Data API v2", text: "Trader history and activity" },
  { name: "Polymarket Gamma", text: "Questions, rules and outcomes" },
  { name: "Kalshi API", text: "Prices and candlesticks for the backtest" },
  { name: "Groq", text: "LLM that matches Polymarket and Kalshi questions" },
  { name: "React + Recharts", text: "This dashboard, built from JSON exports" },
];

function learned({ summary, runs, latency }: Data): string[] {
  const live = runs.filter((r) => r.name !== "Kalshi backtest");
  const roi = live.map((r) => r.roi_fee_pct ?? r.roi_pct).filter((v): v is number => v != null);
  const buys = live.map((r) => r.buys);
  const kalshi = runs.find((r) => r.name === "Kalshi backtest");
  return [
    `Copying with a delay on another exchange loses money: in the Kalshi backtest the main setup returned ${pct(summary.kalshi_roi_pct)} after fees${kalshi ? ` on ${int(kalshi.buys)} trades` : ""}.`,
    `Speed matters. Reading the chain directly is built to give the signal in 0–2 seconds instead of minutes in the Data API.${latency.median_s == null ? "" : ` In ${summary.live_run ?? "the largest live run"} the measured median was ${Number(latency.median_s.toFixed(1))} s.`}`,
    "Fees and slippage decide the result, so every copy is priced against the real order book, not the trader's price.",
    roi.length
      ? `Few settled buys means wide error bars: the live tests ran from ${pct(Math.min(...roi))} to ${pct(Math.max(...roi))} after fees, on ${Math.min(...buys)} to ${Math.max(...buys)} buys each. A small result either way is a reason to keep testing, not proof.`
      : "Few settled buys means wide error bars. A small result either way is a reason to keep testing, not proof.",
  ];
}

export default function About({ data }: { data: Data }) {
  const LEARNED = learned(data);
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
          Mimic is a research project. The live test trades on paper only; the robot buys with a small, capped amount to check the paper
          results against reality. Past results say little about the future, and prediction markets can lose you all of your stake.
          Nothing on this page is a recommendation to trade.
        </p>
        <p className="mt-3 text-sm text-zinc-400">
          Source code:{" "}
          <a className="text-emerald-400 underline-offset-2 hover:underline" href="https://github.com/robinhel/mimic">
            github.com/robinhel/mimic
          </a>
        </p>
      </Card>
    </div>
  );
}
