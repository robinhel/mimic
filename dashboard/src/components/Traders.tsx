import { pct, source, tone } from "../format";
import type { Data } from "../types";
import { Badge, Card } from "./ui";

export default function Traders({ data }: { data: Data }) {
  const rows = [...data.traders].sort((a, b) => b.copied - a.copied || b.settled - a.settled);
  const s = data.summary;

  return (
    <div className="grid gap-4">
      <Card title="How we pick traders">
        <div className="grid gap-3 text-sm leading-relaxed text-zinc-400">
          <p>The traders were picked by the project's analysis agent, not by hand.</p>
          <p>
            29 come from Polymarket's public leaderboards (all-time and month, by profit and by volume), fetched on 10 Nov 2026. Each of
            their buys was copied on paper with $10 between 13 Jun and 16 Sep 2026, selling when they sold. Only traders with at least 20
            settled positions were kept (39). The 29 with a positive copy ROI were followed.
          </p>
          <p>The 8 trusted are the ones where even the lower 5 % bound of a bootstrap of that ROI was above zero.</p>
          <p>19 come from Polyrank's Copy Engine list: 25 were listed, 4 marked "In-play" were removed and 2 could not be found.</p>
          <div className="grid gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-200">
            <div>
              <Badge tone="amber">Biased pick</Badge>
            </div>
            <p>Leaderboards show people who already made money, so the pick is biased.</p>
            <p>
              A test on 461 randomly picked traders outside the leaderboards, copied by the same rule, returned {pct(-3.1)} (17 Nov 2026). A
              later, larger final test on 3,848 traders also came out negative.
            </p>
            <p>
              Traders from Polyrank's list returned about {pct(4, 0)} with a 2-minute delay and {pct(1, 0)} with a 10-minute delay, measured
              from day 15 to day 90.
            </p>
          </div>
        </div>
      </Card>
      <Card
        title="Traders followed"
        sub={`${s.players} traders followed, ${s.players_trusted} trusted. The paper result counts every buy from all followed traders. The list shows the ${rows.length} traders with copied buys.`}
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
                <th className="py-2 pl-3 text-right font-normal">After fees</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800">
              {rows.map((t, i) => (
                <tr key={`${i}-${t.name}`}>
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
                  <td className={`num py-2 pl-3 text-right font-medium ${tone(t.roi_fee_pct)}`}>{pct(t.roi_fee_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-4 text-xs text-zinc-500">
          Names are public Polymarket names or aliases. No wallet addresses are published. ROI includes open buys, valued at today's market price.
          With a few settled buys per trader, single results swing a lot.
        </p>
      </Card>
    </div>
  );
}
