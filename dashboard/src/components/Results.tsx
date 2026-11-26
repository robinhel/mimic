import { dateRange, int, pct, tone, usd } from "../format";
import type { Data, Replay } from "../types";
import { EquityChart, EquityHead, RoiBars, SmallSample, span } from "./charts";
import { Badge, Card, Stat } from "./ui";

export default function Results({ data }: { data: Data }) {
  const { equity, runs, summary } = data;
  const points = equity.map((p) => ({ x: Date.parse(p.t), y: p.pnl_usd }));
  const live = runs.find((r) => r.name === summary.live_run);
  const bars = runs.map((r) => ({ name: r.name, v: r.roi_fee_pct ?? r.roi_pct ?? 0, run: r }));

  return (
    <div className="grid gap-4">
      <Card
        title="Paper portfolio, largest live run"
        sub={`Cumulative result in USD, $10 per copied buy from all followed traders, after fees and slippage.${summary.live_run ? ` ${summary.live_run}${live ? `, ${dateRange(live.from, live.to)}` : ""}.` : ""}`}
      >
        <EquityHead points={points}>
          <span className="text-zinc-400">
            {summary.live_buys} buys, {summary.live_settled} settled
          </span>
        </EquityHead>
        <SmallSample>
          Small sample: {summary.live_buys} buys, {summary.live_settled} settled, {span(points)}. Far too few to tell skill from luck.
        </SmallSample>
        <EquityChart points={points} id="eq" />
      </Card>

      <Card title="ROI per test run" sub="After fees. Red means the copies lost money. The Kalshi backtest is why the project moved to Polymarket.">
        <RoiBars bars={bars} />
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-zinc-500">
              <tr>
                <th className="py-2 font-normal">Run</th>
                <th className="hidden py-2 font-normal sm:table-cell">Period</th>
                <th className="py-2 text-right font-normal">Buys</th>
                <th className="hidden py-2 text-right font-normal sm:table-cell">Settled</th>
                <th className="hidden py-2 text-right font-normal sm:table-cell">ROI</th>
                <th className="py-2 pl-3 text-right font-normal">After fees</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800">
              {runs.map((r) => (
                <tr key={r.name}>
                  <td className="py-2 pr-2 text-zinc-200">{r.name}</td>
                  <td className="hidden py-2 text-zinc-400 sm:table-cell">{dateRange(r.from, r.to)}</td>
                  <td className="num py-2 text-right">{int(r.buys)}</td>
                  <td className="num hidden py-2 text-right sm:table-cell">{int(r.settled)}</td>
                  <td className={`num hidden py-2 text-right sm:table-cell ${tone(r.roi_pct)}`}>{pct(r.roi_pct)}</td>
                  <td className={`num py-2 pl-3 text-right font-medium ${tone(r.roi_fee_pct)}`}>{pct(r.roi_fee_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {data.replay && <ReplayCard r={data.replay} median={data.latency.median_s} />}
    </div>
  );
}

function ReplayCard({ r, median }: { r: Replay; median: number | null }) {
  const main = r.rows.find((x) => x.strategy === "Robot rules" && x.delay_s === 30) ?? r.rows[0];
  if (!main) return null;
  return (
    <>
      <div className="mt-4 flex items-center gap-3" aria-hidden>
        <span className="h-px flex-1 bg-zinc-800" />
        <span className="text-[11px] uppercase tracking-wider text-sky-300">Backtest</span>
        <span className="h-px flex-1 bg-zinc-800" />
      </div>
      <Card
        className="border-dashed border-sky-500/30"
        title={`Replay of the robot's rules (${r.name}, ${dateRange(r.from, r.to)})`}
        sub={`A script went back over these days and bought after the fact by the robot's rules, from a $${r.start_usd} cash box. The number is the change of that $${r.start_usd} at the end, with open buys valued at the market price. It is not the same measure as the ROI per buy above.`}
      >
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Badge tone="blue">Backtest, not live</Badge>
          <span className="text-xs text-zinc-400">
            Main row: {main.strategy}, {main.delay_s} s delay{main.delay_s === 30 && median != null ? `, closest to the ${Number(median.toFixed(1))} s median delay measured live` : ""}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5 sm:gap-3">
          <div className="col-span-2 grid sm:col-span-1">
            <Stat label={`Change of $${r.start_usd}`} compact value={pct(main.roi_pct)} valueClass={tone(main.roi_pct)} sub={`ends at ${usd(main.end_usd)}`} />
          </div>
          <Stat label="Buys" compact value={int(main.buys)} />
          <Stat label="Settled" compact value={int(main.settled)} />
          <Stat label="Sold" compact value={int(main.sold)} />
          <Stat label="Still open" compact value={int(main.open)} />
        </div>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-zinc-500">
              <tr>
                <th className="py-2 font-normal">Rules</th>
                <th className="py-2 text-right font-normal">Delay</th>
                <th className="hidden py-2 text-right font-normal sm:table-cell">Ends at</th>
                <th className="py-2 pl-3 text-right font-normal">Change</th>
                <th className="py-2 pl-3 text-right font-normal">Buys</th>
                <th className="hidden py-2 text-right font-normal sm:table-cell">Settled</th>
                <th className="hidden py-2 text-right font-normal sm:table-cell">Sold</th>
                <th className="hidden py-2 text-right font-normal sm:table-cell">Open</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800">
              {r.rows.map((x) => (
                <tr key={`${x.strategy}-${x.delay_s}`} className={x === main ? "bg-sky-500/5" : ""}>
                  <td className="py-2 pr-2 text-zinc-200">
                    {x.strategy}
                    <div className="text-xs text-zinc-500 sm:hidden">
                      {x.settled} settled, {x.open} open positions · {x.sold} sells
                    </div>
                  </td>
                  <td className="num py-2 pl-2 text-right text-zinc-400">{x.delay_s} s</td>
                  <td className="num hidden py-2 text-right sm:table-cell">{usd(x.end_usd)}</td>
                  <td className={`num py-2 pl-3 text-right font-medium ${tone(x.roi_pct)}`}>{pct(x.roi_pct)}</td>
                  <td className="num py-2 pl-3 text-right">{int(x.buys)}</td>
                  <td className="num hidden py-2 text-right sm:table-cell">{int(x.settled)}</td>
                  <td className="num hidden py-2 text-right sm:table-cell">{int(x.sold)}</td>
                  <td className="num hidden py-2 text-right sm:table-cell">{int(x.open)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-4 text-xs leading-relaxed text-zinc-500">
          Robot rules: copy a trusted trader's every buy, and other followed traders' buys when a second one bought the same answer.
          Delay is the time from the trader's buy to the replayed buy. Sold means the copy followed the trader's sell; Open means the
          position was still open at the end. Buys and Sold count events: adding to an open position counts as a buy, and a partial sell
          counts as a sell while the position stays open. Settled and Open count positions. A position can appear in both, so the parts do
          not add up to Buys.
        </p>
      </Card>
    </>
  );
}
