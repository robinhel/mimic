export interface Summary {
  generated_at: string;
  sample: boolean;
  sim_trades: number;
  kalshi_roi_pct: number | null;
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
  median_s: number;
  max_s: number;
  buckets: { label: string; count: number }[];
  price_diff_cent_median: number | null;
}

export interface RobotEvent {
  t: string;
  type: "buy" | "sell" | "settled" | "skip";
  title: string;
  usd: number | null;
}

export interface Robot {
  spent_usd: number;
  back_usd: number;
  open: number;
  events: RobotEvent[];
}

export interface Data {
  summary: Summary;
  runs: Run[];
  equity: EquityPoint[];
  traders: Trader[];
  latency: Latency;
  robot: Robot | null;
}
