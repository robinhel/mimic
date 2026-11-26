import type { ReactNode } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, LabelList, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { dateTime, day, pct, tick, tone, usd } from "../format";

export const AXIS = { stroke: "#71717a", fontSize: 11 };
export const TIP = {
  contentStyle: { background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8, fontSize: 12 },
  labelStyle: { color: "#a1a1aa" },
};
const DAY = 86400000;

export type Point = { x: number; y: number };

// "within one day" or "over N days", from the first to the last point.
export function span(points: Point[]): string {
  const hours = points.length ? (points.at(-1)!.x - points[0].x) / 3600000 : 0;
  return hours <= 24 ? "within one day" : `over ${Math.ceil(hours / 24)} days`;
}

// The line above an equity chart: result, worst point and counts.
export function EquityHead({ points, children }: { points: Point[]; children: ReactNode }) {
  const last = points.at(-1)?.y ?? 0;
  const low = Math.min(0, ...points.map((p) => p.y));
  return (
    <div className="mb-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
      <span>
        Result <span className={`num font-semibold ${tone(last)}`}>{usd(last, true)}</span>
      </span>
      <span>
        Worst point <span className={`num font-semibold ${tone(low)}`}>{usd(low, true)}</span>
      </span>
      {children}
    </div>
  );
}

export function SmallSample({ children }: { children: ReactNode }) {
  return <p className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-200">{children}</p>;
}

// Cumulative result in USD as a step line, green when it ends at or above zero, red below.
export function EquityChart({ points, id }: { points: Point[]; id: string }) {
  const color = (points.at(-1)?.y ?? 0) >= 0 ? "#34d399" : "#fb7185";
  // Room for the longest $ label, such as "−$1200", without cutting it.
  const big = Math.max(0, ...points.map((p) => Math.abs(p.y)));
  const axisWidth = Math.max(48, 16 + 7 * (String(Math.round(big)).length + 2));
  const ticks: number[] = [];
  if (points.length) {
    const a = points[0].x, b = points.at(-1)!.x;
    const step = Math.max(1, Math.ceil((b - a) / DAY / 8)) * DAY;
    for (let d = Math.ceil(a / DAY) * DAY; d <= b; d += step) ticks.push(d);
  }
  return (
    <>
      <div className="h-56 sm:h-72">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
            <defs>
              <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.35} />
                <stop offset="100%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#27272a" vertical={false} />
            <XAxis dataKey="x" type="number" scale="time" domain={["dataMin", "dataMax"]} ticks={ticks} tickFormatter={(v: number) => day(new Date(v).toISOString())} {...AXIS} minTickGap={24} />
            <YAxis tickFormatter={(v: number) => tick(v, "$")} {...AXIS} width={axisWidth} />
            <ReferenceLine y={0} stroke="#52525b" strokeDasharray="4 4" />
            <Tooltip {...TIP} labelFormatter={(v) => `${dateTime(new Date(Number(v)).toISOString())} UTC`} formatter={(v) => [usd(Number(v), true), "Result"]} />
            <Area isAnimationActive={false} type="stepAfter" dataKey="y" stroke={color} strokeWidth={2} fill={`url(#${id})`} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-2 text-xs text-zinc-500">Each buy's result is counted at its buy time. Open buys are valued at today's market price until the market settles.</p>
    </>
  );
}

// Horizontal ROI bars, one row per name. With cut, longer names are shortened so they fit the axis.
export function RoiBars({ bars, cut, labelWidth = 104 }: { bars: { name: string; v: number }[]; cut?: number; labelWidth?: number }) {
  return (
    <div style={{ height: Math.max(180, bars.length * 44) }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={bars} layout="vertical" margin={{ top: 0, right: bars.some((b) => Math.abs(b.v) >= 100) ? 64 : 52, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#27272a" horizontal={false} />
          <XAxis type="number" tickFormatter={(v: number) => tick(v, "", "%")} {...AXIS} />
          <YAxis
            type="category"
            dataKey="name"
            width={labelWidth}
            interval={0}
            tickFormatter={(v: string) => (cut && v.length > cut ? `${v.slice(0, cut - 1)}…` : v)}
            {...AXIS}
            tick={{ fill: "#d4d4d8", fontSize: 12 }}
          />
          <ReferenceLine x={0} stroke="#71717a" />
          <Tooltip {...TIP} cursor={{ fill: "#27272a" }} formatter={(v) => [pct(Number(v)), "ROI after fees"]} />
          <Bar isAnimationActive={false} dataKey="v" radius={3} maxBarSize={22} minPointSize={1}>
            {bars.map((b) => (
              <Cell key={b.name} fill={b.v === 0 ? "#71717a" : b.v > 0 ? "#34d399" : "#fb7185"} />
            ))}
            <LabelList dataKey="v" content={BarLabel} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
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
