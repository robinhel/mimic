import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, LabelList, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { dateRange, dateTime, day, int, pct, tone, usd } from "../format";
import type { Data } from "../types";
import { Card } from "./ui";

const AXIS = { stroke: "#71717a", fontSize: 11 };
const TIP = {
  contentStyle: { background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8, fontSize: 12 },
  labelStyle: { color: "#a1a1aa" },
};

export default function Results({ data }: { data: Data }) {
  const { equity, runs, summary } = data;
  const points = equity.map((p) => ({ x: Date.parse(p.t), y: p.pnl_usd }));
  const last = equity.at(-1)?.pnl_usd ?? 0;
  const low = Math.min(0, ...equity.map((p) => p.pnl_usd));
  const live = runs.at(-1);
  const bars = runs.map((r) => ({ name: r.name, v: r.roi_fee_pct ?? r.roi_pct ?? 0, run: r }));
  const DAY = 86400000;
  const ticks: number[] = [];
  if (points.length) for (let d = Math.ceil(points[0].x / DAY) * DAY; d <= points.at(-1)!.x; d += DAY) ticks.push(d);
  const color = last >= 0 ? "#34d399" : "#fb7185";

  return (
    <div className="grid gap-4">
      <Card
        title="Paper portfolio, latest live run"
        sub={`Cumulative result in USD, $10 per copied buy, after fees and slippage.${live ? ` ${live.name}, ${dateRange(live.from, live.to)}.` : ""}`}
      >
        <div className="mb-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
          <span>
            Result <span className={`num font-semibold ${tone(last)}`}>{usd(last, true)}</span>
          </span>
          <span>
            Worst point <span className={`num font-semibold ${tone(low)}`}>{usd(low, true)}</span>
          </span>
          <span className="text-zinc-400">
            {summary.live_buys} buys, {summary.live_settled} settled
          </span>
        </div>
        <div className="h-56 sm:h-72">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
              <defs>
                <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={color} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={color} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#27272a" vertical={false} />
              <XAxis dataKey="x" type="number" scale="time" domain={["dataMin", "dataMax"]} ticks={ticks} tickFormatter={(v: number) => day(new Date(v).toISOString())} {...AXIS} minTickGap={24} />
              <YAxis tickFormatter={(v: number) => `$${v}`} {...AXIS} width={48} />
              <ReferenceLine y={0} stroke="#52525b" strokeDasharray="4 4" />
              <Tooltip
                {...TIP}
                labelFormatter={(v) => `${dateTime(new Date(Number(v)).toISOString())} UTC`}
                formatter={(v) => [usd(Number(v), true), "Result"]}
              />
              <Area isAnimationActive={false} type="stepAfter" dataKey="y" stroke={color} strokeWidth={2} fill="url(#eq)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-2 text-xs text-zinc-500">
          Each buy's final result is counted at its buy time. Open positions count as zero until the market settles.
        </p>
      </Card>

      <Card title="ROI per test run" sub="After fees. Red means the copies lost money. The Kalshi backtest is why the project moved to Polymarket.">
        <div style={{ height: Math.max(180, bars.length * 44) }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={bars} layout="vertical" margin={{ top: 0, right: 52, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#27272a" horizontal={false} />
              <XAxis type="number" tickFormatter={(v: number) => `${v}%`} {...AXIS} />
              <YAxis type="category" dataKey="name" width={104} {...AXIS} tick={{ fill: "#d4d4d8", fontSize: 12 }} />
              <ReferenceLine x={0} stroke="#71717a" />
              <Tooltip {...TIP} cursor={{ fill: "#27272a" }} formatter={(v) => [pct(Number(v)), "ROI after fees"]} />
              <Bar isAnimationActive={false} dataKey="v" radius={3} maxBarSize={22}>
                {bars.map((b) => (
                  <Cell key={b.name} fill={b.v >= 0 ? "#34d399" : "#fb7185"} />
                ))}
                <LabelList dataKey="v" content={BarLabel} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-zinc-500">
              <tr>
                <th className="py-2 font-normal">Run</th>
                <th className="hidden py-2 font-normal sm:table-cell">Period</th>
                <th className="py-2 text-right font-normal">Buys</th>
                <th className="py-2 text-right font-normal">Settled</th>
                <th className="hidden py-2 text-right font-normal sm:table-cell">ROI</th>
                <th className="py-2 text-right font-normal">After fees</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800">
              {runs.map((r) => (
                <tr key={r.name}>
                  <td className="py-2 pr-2 text-zinc-200">{r.name}</td>
                  <td className="hidden py-2 text-zinc-400 sm:table-cell">{dateRange(r.from, r.to)}</td>
                  <td className="num py-2 text-right">{int(r.buys)}</td>
                  <td className="num py-2 text-right">{int(r.settled)}</td>
                  <td className={`num hidden py-2 text-right sm:table-cell ${tone(r.roi_pct)}`}>{pct(r.roi_pct)}</td>
                  <td className={`num py-2 text-right font-medium ${tone(r.roi_fee_pct)}`}>{pct(r.roi_fee_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

// Value label just right of the bar's right edge (for losses: right of the zero line), so it never hits the axis labels.
function BarLabel(p: { x?: unknown; y?: unknown; width?: unknown; height?: unknown; value?: unknown }) {
  const x = Number(p.x), w = Number(p.width), y = Number(p.y), h = Number(p.height), v = Number(p.value);
  return (
    <text x={Math.max(x, x + w) + 6} y={y + h / 2} dy={4} fill="#d4d4d8" fontSize={11}>
      {pct(v)}
    </text>
  );
}
