import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { dateRange, dateTime, day, int, pct, tick, tone, usd } from "../format";
import type { ReplayTrade, ReplayTrades } from "../types";
import { Badge, Card, Stat } from "./ui";

const AXIS = { stroke: "#71717a", fontSize: 11 };
const TIP = {
  contentStyle: { background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8, fontSize: 12 },
  labelStyle: { color: "#a1a1aa" },
};
const DAY = 86400000;
const SMALL = 50;

type Rule = "all" | "robot";
interface Choice {
  players: number[];
  from: string;
  to: string;
  delay: number;
  rule: Rule;
}

function addDays(iso: string, n: number): string {
  return new Date(Date.parse(`${iso}T00:00:00Z`) + n * DAY).toISOString().slice(0, 10);
}

function clampDay(v: string | null, f: ReplayTrades, fallback: string): string {
  if (!v || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return fallback;
  return v < f.from ? f.from : v > f.to ? f.to : v;
}

// Hash looks like #replay?p=0,3&from=2026-10-01&to=2026-11-26&d=30&r=all. Missing parts fall back to defaults.
function parseHash(hash: string, f: ReplayTrades): Choice {
  const q = new URLSearchParams(hash.split("?")[1] ?? "");
  const p = q.get("p");
  const players =
    p == null
      ? f.players.map((_, i) => i)
      : [...new Set(p.split(",").filter(Boolean).map(Number))].filter((i) => Number.isInteger(i) && i >= 0 && i < f.players.length).sort((a, b) => a - b);
  let from = clampDay(q.get("from"), f, f.from);
  let to = clampDay(q.get("to"), f, f.to);
  if (from > to) [from, to] = [to, from];
  const d = Number(q.get("d"));
  const delay = f.delays.includes(d) ? d : f.delays.includes(30) ? 30 : f.delays[0];
  const rule: Rule = q.get("r") === "robot" ? "robot" : "all";
  return { players, from, to, delay, rule };
}

const buys = (n: number) => `${int(n)} ${n === 1 ? "buy" : "buys"}`;

function toHash(c: Choice): string {
  return `#replay?p=${c.players.join(",")}&from=${c.from}&to=${c.to}&d=${c.delay}&r=${c.rule}`;
}

// Robot-like rule: a trusted trader's every buy; others only when another followed trader bought the same answer before.
function passes(tr: ReplayTrade, rule: Rule, safe: boolean[]): boolean {
  return rule === "all" || safe[tr.p] || tr.others.length > 0;
}

export default function Replay({ f }: { f: ReplayTrades }) {
  const [c, setC] = useState<Choice>(() => parseHash(window.location.hash, f));
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<"roi" | "buys" | "result">("roi");

  useEffect(() => {
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}${toHash(c)}`);
  }, [c]);

  const trades = useMemo(() => [...f.trades].sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0)), [f]);
  const safe = useMemo(() => f.players.map((p) => p.safe), [f]);
  const key = String(c.delay);

  // Buys in the period under the rule, per player (does not depend on which players are ticked).
  const inPeriod = useMemo(
    () => trades.filter((tr) => { const d = tr.t.slice(0, 10); return d >= c.from && d <= c.to && passes(tr, c.rule, safe); }),
    [trades, c.from, c.to, c.rule, safe],
  );
  const counts = useMemo(() => {
    const n = f.players.map(() => 0);
    for (const tr of inPeriod) n[tr.p] += 1;
    return n;
  }, [inPeriod, f]);
  const order = useMemo(() => {
    const total = f.players.map(() => 0);
    for (const tr of f.trades) total[tr.p] += 1;
    return f.players.map((_, i) => i).sort((a, b) => total[b] - total[a] || f.players[a].name.localeCompare(f.players[b].name));
  }, [f]);

  const r = useMemo(() => {
    const sel = new Set(c.players);
    const picked = inPeriod.filter((tr) => sel.has(tr.p));
    let cost = 0, result = 0, settled = 0, sold = 0, open = 0;
    const points: { x: number; y: number }[] = [];
    const per = new Map<number, { buys: number; cost: number; result: number }>();
    for (const tr of picked) {
      const tc = tr.cost[key] ?? 0, tres = tr.result[key] ?? 0;
      cost += tc;
      result += tres;
      if (tr.state === "settled") settled += 1;
      else if (tr.state === "sold") sold += 1;
      else open += 1;
      points.push({ x: Date.parse(tr.t), y: Math.round(result * 100) / 100 });
      const p = per.get(tr.p) ?? { buys: 0, cost: 0, result: 0 };
      p.buys += 1;
      p.cost += tc;
      p.result += tres;
      per.set(tr.p, p);
    }
    const rows = [...per].map(([i, p]) => ({ i, ...p, roi: p.cost ? (p.result / p.cost) * 100 : null }));
    return { picked, cost, result, settled, sold, open, points, rows, roi: cost ? (result / cost) * 100 : null };
  }, [inPeriod, c.players, key]);

  const rows = useMemo(() => {
    const v = (x: (typeof r.rows)[number]) => (sortKey === "roi" ? (x.roi ?? -Infinity) : sortKey === "buys" ? x.buys : x.result);
    return [...r.rows].sort((a, b) => v(b) - v(a) || b.buys - a.buys);
  }, [r, sortKey]);

  const set = (part: Partial<Choice>) => setC((old) => ({ ...old, ...part }));
  const setPlayers = (ps: number[]) => set({ players: [...ps].sort((a, b) => a - b) });
  const toggle = (i: number) => setPlayers(c.players.includes(i) ? c.players.filter((x) => x !== i) : [...c.players, i]);
  const lastDays = (n: number) => set({ from: addDays(f.to, -(n - 1)) < f.from ? f.from : addDays(f.to, -(n - 1)), to: f.to });
  const isLast = (n: number) => c.to === f.to && c.from === (addDays(f.to, -(n - 1)) < f.from ? f.from : addDays(f.to, -(n - 1)));

  const q = search.trim().toLowerCase();
  const shown = order.filter((i) => !q || f.players[i].name.toLowerCase().includes(q));
  const trusted = f.players.flatMap((p, i) => (p.safe ? [i] : []));
  const sel = new Set(c.players);
  const capped = (f.capped ?? []).filter((i) => i >= 0 && i < f.players.length).map((i) => f.players[i].name);

  const last = r.points.at(-1)?.y ?? 0;
  const color = last >= 0 ? "#34d399" : "#fb7185";
  const ticks: number[] = [];
  if (r.points.length) {
    const a = r.points[0].x, b = r.points.at(-1)!.x;
    const step = Math.max(1, Math.ceil((b - a) / DAY / 8)) * DAY;
    for (let d = Math.ceil(a / DAY) * DAY; d <= b; d += step) ticks.push(d);
  }
  const empty = c.players.length === 0 ? "Pick at least one trader to see how copying them would have gone." : r.picked.length === 0 ? "No copied buys for this choice. Try a longer period, more traders or Every buy." : null;

  return (
    <div className="grid gap-4">
      <div className="grid gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-200">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="blue">Backtest, not live</Badge>
          {f.sample && <Badge tone="amber">Example data</Badge>}
          {!empty && r.picked.length < SMALL && <Badge tone="amber">Small sample</Badge>}
        </div>
        {f.sample && <p>This tab shows made-up example data, not the real replay.</p>}
        <p>Players were picked today. Looking back at them favours those who already did well.</p>
        <p>Prices are estimated from price history, not a real order book.</p>
        <p>Buys in markets that close within an hour are skipped, which drops most in-game sports buys.</p>
        {capped.length > 0 && <p>Older buys were cut for: {capped.join(", ")}.</p>}
        {!empty && r.picked.length < SMALL && <p>Small sample: {buys(r.picked.length)}. Far too few to tell skill from luck.</p>}
      </div>

      <Card
        title="Replay: what if you had copied them?"
        sub={`Pick traders, a period and a delay. Every copied buy is $${f.stake_usd} plus fee, replayed after the fact over ${dateRange(f.from, f.to)}. Updated ${dateTime(f.generated_at)} UTC.`}
      >
        <div className="grid gap-5 lg:grid-cols-2">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs text-zinc-400">
                Traders <span className="num">({c.players.length} of {f.players.length})</span>
              </span>
              <div className="flex gap-1">
                <SmallButton onClick={() => setPlayers(f.players.map((_, i) => i))}>All</SmallButton>
                <SmallButton onClick={() => setPlayers(trusted)}>Trusted</SmallButton>
                <SmallButton onClick={() => setPlayers([])}>None</SmallButton>
              </div>
            </div>
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search traders"
              aria-label="Search traders"
              className="mt-2 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-sm text-zinc-200 placeholder:text-zinc-500 focus:border-emerald-500 focus:outline-none"
            />
            <ul className="mt-2 max-h-64 overflow-y-auto rounded-lg border border-zinc-800 divide-y divide-zinc-800/60">
              {shown.map((i) => (
                <li key={i}>
                  <label className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm hover:bg-zinc-800/40">
                    <input type="checkbox" checked={sel.has(i)} onChange={() => toggle(i)} className="accent-emerald-400" />
                    <span className="min-w-0 truncate text-zinc-200">{f.players[i].name}</span>
                    {f.players[i].safe && <Badge tone="green">trusted</Badge>}
                    <span className="num ml-auto text-xs text-zinc-500">{buys(counts[i])}</span>
                  </label>
                </li>
              ))}
              {shown.length === 0 && <li className="px-3 py-2 text-xs text-zinc-500">No trader matches.</li>}
            </ul>
            <p className="mt-1 text-xs text-zinc-500">Buys counted in the chosen period, under the chosen rule.</p>
          </div>

          <div className="grid min-w-0 content-start gap-4">
            <div>
              <div className="text-xs text-zinc-400">Period</div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <input type="date" aria-label="From" value={c.from} min={f.from} max={c.to} onChange={(e) => e.target.value && set({ from: clampDay(e.target.value, f, f.from) })} className={DATE} />
                <span className="text-zinc-500">–</span>
                <input type="date" aria-label="To" value={c.to} min={c.from} max={f.to} onChange={(e) => e.target.value && set({ to: clampDay(e.target.value, f, f.to) })} className={DATE} />
              </div>
              <div className="mt-2 flex gap-1">
                {[7, 30, 90].map((n) => (
                  <SmallButton key={n} active={isLast(n)} onClick={() => lastDays(n)}>
                    {n} days
                  </SmallButton>
                ))}
              </div>
            </div>
            <div>
              <div className="text-xs text-zinc-400">Delay after the trader's buy</div>
              <Segmented value={c.delay} options={f.delays.map((d) => ({ value: d, label: `${d} s` }))} onChange={(d) => set({ delay: d })} />
            </div>
            <div>
              <div className="text-xs text-zinc-400">Rule</div>
              <Segmented value={c.rule} options={[{ value: "all", label: "Every buy" }, { value: "robot", label: "Robot-like rule" }]} onChange={(rule) => set({ rule })} />
              <p className="mt-2 text-xs leading-relaxed text-zinc-500">
                {c.rule === "all"
                  ? "Copy every buy from the ticked traders."
                  : "Trusted players' buys always, others only when another followed player bought the same answer within 3 days. Repeat buys are copied too, and the robot's caps and bank are not modelled."}
              </p>
            </div>
          </div>
        </div>
      </Card>

      {empty ? (
        <Card>
          <p className="py-8 text-center text-sm text-zinc-400">{empty}</p>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 sm:gap-3">
            <Stat label="ROI after fees" compact value={pct(r.roi)} valueClass={tone(r.roi)} />
            <Stat label="Result" compact value={usd(r.result, true)} valueClass={tone(r.result)} />
            <Stat label="Buys" compact value={int(r.picked.length)} />
            <Stat label="Settled" compact value={int(r.settled)} />
            <Stat label="Sold" compact value={int(r.sold)} />
            <Stat label="Still open" compact value={int(r.open)} />
          </div>

          <Card title="Cumulative result" sub={`USD, ${c.delay} s delay, ${dateRange(c.from, c.to)}. Each buy's result is counted at its buy time; open buys at today's price.`}>
            <div className="h-56 sm:h-72">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={r.points} margin={{ top: 8, right: 8, bottom: 0, left: -4 }}>
                  <defs>
                    <linearGradient id="rp" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={color} stopOpacity={0.35} />
                      <stop offset="100%" stopColor={color} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#27272a" vertical={false} />
                  <XAxis dataKey="x" type="number" scale="time" domain={["dataMin", "dataMax"]} ticks={ticks} tickFormatter={(v: number) => day(new Date(v).toISOString())} {...AXIS} minTickGap={24} />
                  <YAxis tickFormatter={(v: number) => tick(v, "$")} {...AXIS} width={56} />
                  <ReferenceLine y={0} stroke="#52525b" strokeDasharray="4 4" />
                  <Tooltip {...TIP} labelFormatter={(v) => `${dateTime(new Date(Number(v)).toISOString())} UTC`} formatter={(v) => [usd(Number(v), true), "Result"]} />
                  <Area isAnimationActive={false} type="stepAfter" dataKey="y" stroke={color} strokeWidth={2} fill="url(#rp)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Per trader" sub="Click a column to sort.">
              <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-zinc-500">
                    <tr>
                      <th className="py-2 font-normal">Trader</th>
                      <SortTh active={sortKey === "buys"} onClick={() => setSortKey("buys")}>Buys</SortTh>
                      <SortTh active={sortKey === "result"} onClick={() => setSortKey("result")}>Result</SortTh>
                      <SortTh active={sortKey === "roi"} onClick={() => setSortKey("roi")}>ROI</SortTh>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800">
                    {rows.map((x) => (
                      <tr key={x.i}>
                        <td className="py-2 pr-2">
                          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                            <span className="text-zinc-200 [overflow-wrap:anywhere]">{f.players[x.i].name}</span>
                            {f.players[x.i].safe && <Badge tone="green">trusted</Badge>}
                          </div>
                        </td>
                        <td className="num py-2 pl-3 text-right">{int(x.buys)}</td>
                        <td className={`num py-2 pl-3 text-right ${tone(x.result)}`}>{usd(x.result, true)}</td>
                        <td className={`num py-2 pl-3 text-right font-medium ${tone(x.roi)}`}>{pct(x.roi)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>

            <Card title="Latest 20 buys" sub="Newest first. Times in UTC.">
              <ul className="divide-y divide-zinc-800">
                {r.picked.slice(-20).reverse().map((tr, n) => (
                  <li key={`${tr.t}-${tr.p}-${n}`} className="flex items-center gap-3 py-2 text-sm">
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-zinc-200">{tr.title}</div>
                      <div className="truncate text-xs text-zinc-500">
                        {dateTime(tr.t)} · {f.players[tr.p].name}
                        {tr.state !== "settled" && ` · ${tr.state}`}
                      </div>
                    </div>
                    <span className={`num ${tone(tr.result[key])}`}>{usd(tr.result[key], true)}</span>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        </>
      )}

      <p className="text-xs leading-relaxed text-zinc-500">
        ROI after fees is the sum of results divided by the sum of costs. Delay is the time from the trader's buy to the replayed buy; the
        copy pays at least the trader's price. Sold means the copy followed the trader's sell. Open buys are valued at today's market price.
        The link in the address bar keeps your choice, so you can share it.
      </p>
    </div>
  );
}

const DATE = "num rounded-lg border border-zinc-700 bg-zinc-950 px-2 py-1 text-sm text-zinc-200 focus:border-emerald-500 focus:outline-none";

function SmallButton({ children, onClick, active = false }: { children: ReactNode; onClick: () => void; active?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-md border px-2 py-1 text-xs transition-colors ${active ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-300" : "border-zinc-700 text-zinc-300 hover:border-zinc-500"}`}
    >
      {children}
    </button>
  );
}

function Segmented<T extends string | number>({ value, options, onChange }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="mt-2 inline-flex rounded-lg border border-zinc-700 p-0.5" role="radiogroup">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={`rounded-md px-3 py-1 text-sm transition-colors ${o.value === value ? "bg-emerald-500/15 text-emerald-300" : "text-zinc-400 hover:text-zinc-200"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function SortTh({ children, active, onClick }: { children: ReactNode; active: boolean; onClick: () => void }) {
  return (
    <th className="py-2 pl-3 text-right font-normal" aria-sort={active ? "descending" : "none"}>
      <button type="button" onClick={onClick} className={active ? "text-zinc-200" : "hover:text-zinc-300"}>
        {children}
        {active ? " ↓" : ""}
      </button>
    </th>
  );
}
