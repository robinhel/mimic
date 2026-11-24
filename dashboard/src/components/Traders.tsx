import { useState } from "react";
import { pct, source, tone } from "../format";
import type { Data } from "../types";
import { Badge, Card } from "./ui";

export default function Traders({ data }: { data: Data }) {
  const [all, setAll] = useState(false);
  const sorted = [...data.traders].sort((a, b) => b.copied - a.copied || b.settled - a.settled);
  const active = sorted.filter((t) => t.copied > 0);
  const rows = all ? sorted : active;
  const trusted = data.traders.filter((t) => t.safe).length;

  return (
    <div className="grid gap-4">
      <Card
        title="Traders followed"
        sub={`${data.traders.length} traders, ${trusted} trusted. Trusted traders are copied on every buy; the others only when a second followed trader buys the same answer within 3 days.`}
      >
        <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-zinc-500">
              <tr>
                <th className="py-2 font-normal">Trader</th>
                <th className="hidden py-2 font-normal sm:table-cell">Source</th>
                <th className="py-2 text-right font-normal">Copied</th>
                <th className="hidden py-2 text-right font-normal sm:table-cell">Settled</th>
                <th className="hidden py-2 text-right font-normal md:table-cell">ROI</th>
                <th className="py-2 text-right font-normal">After fees</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800">
              {rows.map((t) => (
                <tr key={t.name}>
                  <td className="py-2 pr-2">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span className="text-zinc-200">{t.name}</span>
                      {t.safe && <Badge tone="green">trusted</Badge>}
                    </div>
                    <div className="text-xs text-zinc-500 sm:hidden">
                      {source(t.source)} · {t.settled} settled
                    </div>
                  </td>
                  <td className="hidden py-2 text-zinc-400 sm:table-cell">{source(t.source)}</td>
                  <td className="num py-2 text-right">{t.copied}</td>
                  <td className="num hidden py-2 text-right sm:table-cell">{t.settled}</td>
                  <td className={`num hidden py-2 text-right md:table-cell ${tone(t.roi_pct)}`}>{pct(t.roi_pct)}</td>
                  <td className={`num py-2 text-right font-medium ${tone(t.roi_fee_pct)}`}>{pct(t.roi_fee_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {active.length < sorted.length && (
          <button
            onClick={() => setAll(!all)}
            className="mt-4 rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:border-zinc-500 hover:text-zinc-100"
          >
            {all ? "Show only copied traders" : `Show all ${sorted.length} (${sorted.length - active.length} with no copied buys)`}
          </button>
        )}
        <p className="mt-4 text-xs text-zinc-500">
          Names are public Polymarket names or aliases. No wallet addresses are published. ROI is “—” until a copied buy has settled.
          With a few settled buys per trader, single results swing a lot.
        </p>
      </Card>
    </div>
  );
}
