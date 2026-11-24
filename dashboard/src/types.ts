export interface Summary {
  generated_at: string;
  sample: boolean;
  sim_trades: number;
  kalshi_roi_pct: number | null;
  live_run: string | null;
  live_roi_pct: number | null;
  live_roi_fee_pct: number | null;
  live_buys: number;
  live_settled: number;
  players: number;
  players_trusted: number;
}

export interface Run {
  name: string;
  from: string;
  to: string;
  buys: number;
  settled: number;
  roi_pct: number | null;
  roi_fee_pct: number | null;
}

export interface EquityPoint {
  t: string;
  pnl_usd: number;
}

export interface Trader {
  name: string;
  source: string;
  safe: boolean;
  copied: number;
  settled: number;
  roi_pct: number | null;
  roi_fee_pct: number | null;
}

export interface Latency {
  median_s: number | null;
  max_s: number | null;
  buckets: { label: string; count: number }[];
  price_diff_cent_median: number | null;
}

export interface RobotEvent {
  t: string;
  type: "buy" | "sell" | "settled" | "skip";
  title: string | null;
  usd: number | null;
}

export interface Robot {
  spent_usd: number;
  back_usd: number;
  open: number;
  events: RobotEvent[];
}

export interface ReplayRow {
  strategy: string;
  delay_s: number;
  end_usd: number;
  roi_pct: number;
  buys: number;
  sold: number;
  settled: number;
  open: number;
}

export interface Replay {
  name: string;
  from: string;
  to: string;
  start_usd: number;
  rows: ReplayRow[];
}

export interface Data {
  summary: Summary;
  runs: Run[];
  equity: EquityPoint[];
  traders: Trader[];
  latency: Latency;
  robot: Robot | null;
  replay: Replay | null;
}
