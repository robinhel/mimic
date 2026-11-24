import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { int, pct, tone } from "../format";
import type { Data } from "../types";
import { Card } from "./ui";

interface Node {
  x: number;
  y: number;
  w: number;
  title: string;
  sub: string;
  hl?: boolean;
  dashed?: boolean;
}
interface Layout {
  width: number;
  height: number;
  nodeH: number;
  nodes: Node[];
  edges: { d: string; hl?: boolean }[];
}

function layouts(sim: string, kalshi: string): { wide: Layout; tall: Layout } {
  const main = [
    { title: "Polygon chain", sub: "trader buys" },
    { title: "pm_livetest", sub: "goal: 0–2 s", hl: true },
    { title: "Signal", sub: "order book saved" },
    { title: "Paper buy", sub: "fees + slippage", hl: true },
    { title: "Settled", sub: "ROI measured" },
  ];
  const backtest = { title: `Backtest: ${sim} trades`, sub: `Kalshi, main setup ${kalshi}, dropped`, dashed: true };
  // Wide: one row, robot and backtest below.
  const W = 128, G = 30, H = 54;
  const wide: Layout = {
    width: 5 * W + 4 * G + 8,
    height: 190,
    nodeH: H,
    nodes: [
      ...main.map((n, i) => ({ ...n, x: 4 + i * (W + G), y: 20, w: W })),
      { ...backtest, x: 4, y: 120, w: 2 * W + G },
      { title: "pm_robot: real buys", sub: "$5 per buy, STOP file, --live only", x: 4 + 2 * (W + G), y: 120, w: 3 * W + 2 * G },
    ],
    edges: [
      ...[0, 1, 2, 3].map((i) => ({ d: `M${4 + i * (W + G) + W} ${20 + H / 2}H${4 + (i + 1) * (W + G) - 3}`, hl: i % 2 === 0 })),
      { d: `M${4 + 2 * (W + G) + W / 2} ${20 + H}V117` },
    ],
  };
  // Tall: one column, robot to the right of Signal, backtest at the bottom.
  const TW = 184, TH = 50, TG = 22;
  const tall: Layout = {
    width: 320,
    height: 5 * TH + 4 * TG + 90,
    nodeH: TH,
    nodes: [
      ...main.map((n, i) => ({ ...n, x: 4, y: 4 + i * (TH + TG), w: TW })),
      { title: "pm_robot", sub: "$5 per buy", x: TW + 30, y: 4 + 2 * (TH + TG), w: 320 - TW - 34 },
      { ...backtest, sub: `Kalshi, main setup ${kalshi}`, x: 4, y: 4 + 5 * (TH + TG) + 14, w: 312 },
    ],
    edges: [
      ...[0, 1, 2, 3].map((i) => ({ d: `M${4 + TW / 2} ${4 + i * (TH + TG) + TH}V${4 + (i + 1) * (TH + TG) - 3}`, hl: i % 2 === 0 })),
      { d: `M${4 + TW} ${4 + 2 * (TH + TG) + TH / 2}H${TW + 27}` },
    ],
  };
  return { wide, tall };
}

function Diagram({ l, id, className }: { l: Layout; id: string; className: string }) {
  return (
    <svg viewBox={`0 0 ${l.width} ${l.height}`} width="100%" className={className} role="img" aria-label="Flow from a trader's buy on the Polygon chain to a measured result">
      <defs>
        {[
          ["g", "#71717a"],
          ["h", "#34d399"],
        ].map(([k, c]) => (
          <marker key={k} id={`${id}-${k}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0 0L10 5L0 10z" fill={c} />
          </marker>
        ))}
      </defs>
      {l.edges.map((e) => (
        <path key={e.d} d={e.d} stroke={e.hl ? "#34d399" : "#71717a"} strokeWidth={1.5} fill="none" markerEnd={`url(#${id}-${e.hl ? "h" : "g"})`} />
      ))}
      {l.nodes.map((n) => (
        <g key={n.title}>
          <rect
            x={n.x}
            y={n.y}
            width={n.w}
            height={l.nodeH}
            rx={8}
            fill={n.hl ? "rgba(52,211,153,0.08)" : "#18181b"}
            stroke={n.hl ? "#34d399" : "#3f3f46"}
            strokeDasharray={n.dashed ? "4 4" : undefined}
          />
          <text x={n.x + 12} y={n.y + l.nodeH / 2 - 4} fontSize={13} fill="#f4f4f5" fontWeight={500}>
            {n.title}
          </text>
          <text x={n.x + 12} y={n.y + l.nodeH / 2 + 13} fontSize={11} fill="#a1a1aa">
            {n.sub}
          </text>
        </g>
      ))}
    </svg>
  );
}

const steps = (measured: string) => [
  {
    n: "1",
    title: "Watch the chain",
    text: `pm_livetest reads OrderFilled events from Polymarket's exchange contracts on Polygon. It is built to see a followed trader's buy within 0–2 seconds, instead of waiting for the public Data API, which lagged about 8 minutes when this was built. ${measured}`,
  },
  {
    n: "2",
    title: "Copy on paper",
    text: "Each signal saves the live order book. The copy buys $10 at the prices we could really have got, walking the book, plus Polymarket's fee. Sells follow the trader's sells.",
  },
  {
    n: "3",
    title: "Measure honestly",
    text: "When the market resolves, the copy is settled at 0 or 1. Open copies are valued at today's market price. ROI is counted after fees.",
  },
];

// Seconds without a pointless ".0": 18 s, 2.5 s.
function secs(v: number): string {
  return `${Number(v.toFixed(1))} s`;
}

// Signed cents with a real minus sign: +0.8¢, −0.5¢.
function cents(v: number): string {
  const s = Math.abs(v).toFixed(1);
  return `${Number(s) === 0 ? "" : v > 0 ? "+" : "\u2212"}${s}¢`;
}

export default function HowItWorks({ data }: { data: Data }) {
  const { summary, latency } = data;
  const { wide, tall } = layouts(int(summary.sim_trades), pct(summary.kalshi_roi_pct));
  const measured =
    latency.median_s == null
      ? ""
      : `Measured in the latest live run: median ${secs(latency.median_s)} from the trader's fill to our signal${latency.max_s == null ? "" : `, max ${secs(latency.max_s)}`}.`;
  return (
    <div className="grid gap-4">
      <Card title="From a trader's buy to a measured result" sub="Green steps are where speed and price decide the outcome.">
        <Diagram l={wide} id="wide" className="hidden sm:block" />
        <Diagram l={tall} id="tall" className="mx-auto max-w-[340px] sm:hidden" />
      </Card>

      <div className="grid gap-4 md:grid-cols-3">
        {steps(measured).map((s) => (
          <Card key={s.n}>
            <div className="flex items-center gap-2">
              <span className="flex size-6 items-center justify-center rounded-full bg-emerald-500/15 text-xs font-semibold text-emerald-300">{s.n}</span>
              <h3 className="text-sm font-medium text-zinc-100">{s.title}</h3>
            </div>
            <p className="mt-3 text-sm leading-relaxed text-zinc-400">{s.text}</p>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="How fast is the copy?" sub="Seconds from the trader's fill to our signal, latest live run.">
          <div className="mb-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
            <span>
              Median <span className="num font-semibold text-zinc-50">{latency.median_s == null ? "—" : secs(latency.median_s)}</span>
            </span>
            <span>
              Max <span className="num font-semibold text-zinc-50">{latency.max_s == null ? "—" : secs(latency.max_s)}</span>
            </span>
            {latency.price_diff_cent_median != null && (
              <span>
                Price vs. trader <span className="num font-semibold text-zinc-50">{cents(latency.price_diff_cent_median)}</span>
              </span>
            )}
          </div>
          <div className="h-44">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={latency.buckets} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
                <CartesianGrid stroke="#27272a" vertical={false} />
                <XAxis dataKey="label" stroke="#71717a" fontSize={11} />
                <YAxis allowDecimals={false} stroke="#71717a" fontSize={11} />
                <Tooltip
                  contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: "#a1a1aa" }}
                  cursor={{ fill: "#27272a" }}
                  formatter={(v) => [String(v), "Signals"]}
                />
                <Bar isAnimationActive={false} dataKey="count" fill="#34d399" radius={[3, 3, 0, 0]} maxBarSize={48} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card title="Why not Kalshi?" sub="The first idea, tested at scale.">
          <p className="text-sm leading-relaxed text-zinc-400">
            The project began with a backtest: match top Polymarket traders' buys to the same questions on Kalshi and copy them there.
            It ran <span className="num text-zinc-200">{int(summary.sim_trades)}</span> simulated trades across 4 delays and 3 strategies.
            The main setup (2 min delay, hold to settlement) returned{" "}
            <span className={`num font-medium ${tone(summary.kalshi_roi_pct)}`}>{pct(summary.kalshi_roi_pct)}</span> after fees, so the idea
            was dropped.
          </p>
          <p className="mt-3 text-sm leading-relaxed text-zinc-400">
            The live test on Polymarket copies on the same exchange, with the real order book at the moment of the signal. The robot
            can then buy for real, with hard limits (see the Robot tab).
          </p>
        </Card>
      </div>
    </div>
  );
}
