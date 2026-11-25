import type { ReactNode } from "react";

export function Card({ title, sub, children, className = "" }: { title?: string; sub?: string; children: ReactNode; className?: string }) {
  return (
    <section className={`min-w-0 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 sm:p-5 ${className}`}>
      {title && <h3 className="text-sm font-medium text-zinc-100">{title}</h3>}
      {sub && <p className="mt-1 text-xs text-zinc-400">{sub}</p>}
      <div className={title || sub ? "mt-4" : ""}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, sub, valueClass = "text-zinc-50", compact = false }: { label: string; value: string; sub?: ReactNode; valueClass?: string; compact?: boolean }) {
  return (
    <div className={`min-w-0 rounded-xl border border-zinc-800 bg-zinc-900/60 ${compact ? "p-3 sm:p-4" : "p-4"}`}>
      <div className="text-xs text-zinc-400">{label}</div>
      <div className={`num mt-1 font-semibold tracking-tight sm:text-3xl ${compact ? "text-lg" : "text-2xl"} ${valueClass}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-zinc-400">{sub}</div>}
    </div>
  );
}

const TONES = {
  green: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  red: "border-rose-500/30 bg-rose-500/10 text-rose-300",
  amber: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  blue: "border-sky-500/30 bg-sky-500/10 text-sky-300",
  gray: "border-zinc-700 bg-zinc-800/60 text-zinc-300",
};

export function Badge({ tone = "gray", children }: { tone?: keyof typeof TONES; children: ReactNode }) {
  return <span className={`inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium ${TONES[tone]}`}>{children}</span>;
}
