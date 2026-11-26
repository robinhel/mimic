import { type ReactNode, useEffect, useState } from "react";
import About from "./components/About";
import HowItWorks from "./components/HowItWorks";
import Replay from "./components/Replay";
import Robot from "./components/Robot";
import Traders from "./components/Traders";
import Results from "./components/Results";
import { Badge, Stat } from "./components/ui";
import { useData } from "./data";
import { dateTime, int, pct, tone } from "./format";

const TABS = [
  { id: "results", label: "Results" },
  { id: "replay", label: "Replay" },
  { id: "how", label: "How it works" },
  { id: "traders", label: "Traders" },
  { id: "robot", label: "Robot" },
  { id: "about", label: "About" },
] as const;
type TabId = (typeof TABS)[number]["id"];

export default function App() {
  const { data, error } = useData();
  const [tab, setTab] = useState<TabId>(() => (window.location.hash.startsWith("#replay") ? "replay" : "results"));
  // A pasted #replay link in an open page remounts Replay so it reads the new choice.
  const [hashKey, setHashKey] = useState(0);
  useEffect(() => {
    const onHash = () => {
      if (window.location.hash.startsWith("#replay")) {
        setTab("replay");
        setHashKey((k) => k + 1);
      }
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  if (error) return <Shell><p className="text-rose-300">Could not load data: {error}</p></Shell>;
  if (!data) return <Shell><p className="text-zinc-400">Loading…</p></Shell>;
  const s = data.summary;
  const tabs = TABS.filter((t) => t.id !== "replay" || data.replayTrades);
  const current: TabId = tab === "replay" && !data.replayTrades ? "results" : tab;
  const pick = (id: TabId) => {
    // Only the Replay tab keeps its choice in the hash.
    if (id !== "replay") window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    setTab(id);
  };

  return (
    <Shell>
      <header className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <div className="flex items-center gap-2.5">
            <MimicMark />
            <div className="leading-tight">
              <span className="block text-2xl font-semibold tracking-tight text-zinc-50 sm:text-3xl">Mimic</span>
              <span className="block text-xs text-balance text-emerald-300/80 sm:text-sm">
                Copy the best Polymarket traders. Measure if it pays.
              </span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {s.sample && <Badge tone="amber">Example data</Badge>}
            <span className="text-xs text-zinc-500">Updated {dateTime(s.generated_at)} UTC</span>
          </div>
        </div>
        <h1 className="max-w-3xl text-2xl font-semibold tracking-tight text-zinc-50 text-balance sm:text-4xl">
          Can you make money by copying the best Polymarket traders?
        </h1>
        <p className="max-w-2xl text-sm leading-relaxed text-zinc-400 sm:text-base">
          Mimic follows top traders on-chain, copies their buys on paper against the live order book, and measures
          the result after fees and slippage. Built in Python. Read-only research.
        </p>
        {s.sample && (
          <p className="max-w-2xl rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-200">
            This page shows example data. Headline numbers match the real project; curves, runs and trader rows are illustrative.
          </p>
        )}
      </header>

      <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Simulated trades" value={int(s.sim_trades)} sub="Kalshi backtest" />
        <Stat label="Kalshi copy ROI" value={pct(s.kalshi_roi_pct)} valueClass={tone(s.kalshi_roi_pct)} sub={<Badge tone="red">dropped</Badge>} />
        <Stat
          label="Live paper ROI"
          value={pct(s.live_roi_fee_pct ?? s.live_roi_pct)}
          valueClass={tone(s.live_roi_fee_pct ?? s.live_roi_pct)}
          sub={
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <Badge tone="amber">small sample</Badge>
              <span>
                {s.live_run ? `${s.live_run}: ` : ""}
                {s.live_buys} buys, {s.live_settled} settled, after fees
              </span>
            </span>
          }
        />
        <Stat label="Traders followed" value={String(s.players)} sub={`${s.players_trusted} trusted`} />
      </div>

      <nav className="sticky top-0 z-10 -mx-4 mt-8 border-b border-zinc-800 bg-zinc-950/90 px-4 backdrop-blur sm:mx-0 sm:px-0" aria-label="Sections">
        <div className="flex overflow-x-auto sm:gap-1" role="tablist">
          {tabs.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={current === t.id}
              onClick={() => pick(t.id)}
              className={`shrink-0 border-b-2 px-1.5 py-3 text-[13px] sm:px-3 sm:text-sm transition-colors ${
                current === t.id ? "border-emerald-400 text-zinc-50" : "border-transparent text-zinc-400 hover:text-zinc-200"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </nav>

      <main className="mt-6">
        {current === "results" && <Results data={data} />}
        {current === "replay" && data.replayTrades && <Replay key={hashKey} f={data.replayTrades} />}
        {current === "how" && <HowItWorks data={data} />}
        {current === "traders" && <Traders data={data} />}
        {current === "robot" && <Robot data={data} />}
        {current === "about" && <About data={data} />}
      </main>
    </Shell>
  );
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-12">
      {children}
      <footer className="mt-16 border-t border-zinc-800 pt-6 text-xs text-zinc-500">
        Mimic · research project, not financial advice ·{" "}
        <a className="text-zinc-400 underline-offset-2 hover:underline" href="https://github.com/robinhel/mimic">source on GitHub</a>
      </footer>
    </div>
  );
}

/** Two overlapping circles: a trader and its copy. */
function MimicMark() {
  return (
    <svg viewBox="0 0 40 40" className="h-9 w-9 shrink-0 sm:h-10 sm:w-10" aria-hidden="true">
      <rect width="40" height="40" rx="10" className="fill-emerald-400/10" />
      <circle cx="16" cy="20" r="8" className="fill-emerald-400" />
      <circle cx="24" cy="20" r="8" className="fill-none stroke-emerald-400" strokeWidth="2.5" />
    </svg>
  );
}
