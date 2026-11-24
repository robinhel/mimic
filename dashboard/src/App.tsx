import { type ReactNode, useState } from "react";
import Results from "./components/Results";
import { Badge, Stat } from "./components/ui";
import { useData } from "./data";
import { dateTime, int, pct, tone } from "./format";

const TABS = [
  { id: "results", label: "Results" },
  { id: "how", label: "How it works" },
  { id: "traders", label: "Traders" },
  { id: "robot", label: "Robot" },
  { id: "about", label: "About" },
] as const;
type TabId = (typeof TABS)[number]["id"];

export default function App() {
  const { data, error } = useData();
  const [tab, setTab] = useState<TabId>("results");

  if (error) return <Shell><p className="text-rose-300">Could not load data: {error}</p></Shell>;
  if (!data) return <Shell><p className="text-zinc-400">Loading…</p></Shell>;
  const s = data.summary;

  return (
    <Shell>
      <header className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm text-emerald-400">copycheck</span>
          {s.sample && <Badge tone="amber">Example data</Badge>}
          <span className="text-xs text-zinc-500">Updated {dateTime(s.generated_at)} UTC</span>
        </div>
        <h1 className="max-w-3xl text-2xl font-semibold tracking-tight text-zinc-50 text-balance sm:text-4xl">
          Can you make money by copying the best Polymarket traders?
        </h1>
        <p className="max-w-2xl text-sm leading-relaxed text-zinc-400 sm:text-base">
          copycheck follows top traders on-chain, copies their buys within seconds on paper, and measures the result
          after fees and slippage. Built in Python. Read-only research.
        </p>
        {s.sample && (
          <p className="max-w-2xl rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-200">
            This page shows example data. Headline numbers match the real project; curves, runs and trader rows are illustrative.
          </p>
        )}
      </header>

      <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Simulated trades" value={int(s.sim_trades)} sub="Kalshi backtest" />
        <Stat label="Kalshi copy ROI" value={pct(s.kalshi_roi_pct, 0)} valueClass={tone(s.kalshi_roi_pct)} sub={<Badge tone="red">dropped</Badge>} />
        <Stat
          label="Live paper ROI"
          value={pct(s.live_roi_fee_pct ?? s.live_roi_pct, 0)}
          valueClass={tone(s.live_roi_fee_pct ?? s.live_roi_pct)}
          sub={`${s.live_buys} buys, ${s.live_settled} settled, after fees`}
        />
        <Stat label="Traders followed" value={String(s.players)} sub={`${s.players_trusted} trusted`} />
      </div>

      <nav className="sticky top-0 z-10 -mx-4 mt-8 border-b border-zinc-800 bg-zinc-950/90 px-4 backdrop-blur sm:mx-0 sm:px-0" aria-label="Sections">
        <div className="flex overflow-x-auto sm:gap-1" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
              className={`shrink-0 border-b-2 px-2 py-3 text-[13px] sm:px-3 sm:text-sm transition-colors ${
                tab === t.id ? "border-emerald-400 text-zinc-50" : "border-transparent text-zinc-400 hover:text-zinc-200"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </nav>

      <main className="mt-6">
        {tab === "results" ? <Results data={data} /> : <p className="text-sm text-zinc-500">Coming soon.</p>}
      </main>
    </Shell>
  );
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-12">
      {children}
      <footer className="mt-16 border-t border-zinc-800 pt-6 text-xs text-zinc-500">
        copycheck · research project, not financial advice ·{" "}
        <a className="text-zinc-400 underline-offset-2 hover:underline" href="https://github.com/robinhel/copycheck">source on GitHub</a>
      </footer>
    </div>
  );
}
