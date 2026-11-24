const MINUS = "\u2212";

export function pct(v: number | null | undefined, digits = 1): string {
  if (v == null) return "—";
  const s = Math.abs(v).toFixed(digits);
  if (Number(s) === 0) return `0 %`;
  return `${v > 0 ? "+" : MINUS}${s} %`;
}

export function usd(v: number | null | undefined, signed = false): string {
  if (v == null) return "—";
  const s = `$${Math.abs(v).toFixed(2)}`;
  if (v < 0) return MINUS + s;
  return signed && v > 0 ? `+${s}` : s;
}

export function int(v: number): string {
  return v.toLocaleString("en-US");
}

export function tone(v: number | null | undefined): string {
  if (v == null || v === 0) return "text-zinc-300";
  return v > 0 ? "text-emerald-400" : "text-rose-400";
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function day(iso: string): string {
  const d = new Date(iso);
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
}

export function dateTime(iso: string): string {
  const d = new Date(iso);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${day(iso)}, ${hh}:${mm}`;
}

export function dateRange(from: string, to: string): string {
  const f = `${from}T00:00:00Z`;
  const t = `${to}T00:00:00Z`;
  const fy = from.slice(0, 4);
  const ty = to.slice(0, 4);
  return fy === ty ? `${day(f)} – ${day(t)} ${ty}` : `${day(f)} ${fy} – ${day(t)} ${ty}`;
}

const SOURCES: Record<string, string> = { "vår": "own list" };

export function source(s: string): string {
  return SOURCES[s] ?? s;
}
