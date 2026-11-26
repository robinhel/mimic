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

// replay_trades.json: every replayed copy buy, so the Replay tab can pick players, period and delay.
export interface ReplayTrade {
  p: number;
  t: string;
  title: string;
  trader_price: number;
  others: number[];
  state: "settled" | "sold" | "open";
  cost: Record<string, number>;
  result: Record<string, number>;
}

export interface ReplayTrades {
  generated_at: string;
  sample: boolean;
  from: string;
  to: string;
  delays: number[];
  stake_usd: number;
  players: { name: string; safe: boolean }[];
  capped?: number[]; // players whose oldest buys were cut by the export (missing in older files)
  trades: ReplayTrade[];
}

export interface Data {
  summary: Summary;
  runs: Run[];
  equity: EquityPoint[];
  traders: Trader[];
  latency: Latency;
  robot: Robot | null;
  replay: Replay | null;
  replayTrades: ReplayTrades | null;
}
