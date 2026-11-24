import { dateTime, usd } from "../format";
import type { Data, RobotEvent } from "../types";
import { Badge, Card, Stat } from "./ui";

const TYPE: Record<RobotEvent["type"], { label: string; tone: "green" | "red" | "amber" | "blue" | "gray" }> = {
  buy: { label: "buy", tone: "blue" },
  sell: { label: "sell", tone: "amber" },
  settled: { label: "settled", tone: "green" },
  skip: { label: "skip", tone: "gray" },
};

const LIMITS = [
  { title: "$5 max per buy", text: "2 % of the cash per buy, at least 5 shares, never more than $5." },
  { title: "About $100 in total", text: "The robot's wallet holds about $100. No new buy if the cash would drop below 20 % of the start." },
  { title: "STOP file halts everything", text: "If a file named STOP exists in the robot's folder, it buys nothing." },
  { title: "Orders only with --live", text: "The default is a dry run. Real orders need the --live flag, and it refuses to start where Polymarket blocks the country." },
  { title: "No chasing", text: "Skips the buy if the price has moved more than 5 cents since the trader's buy, or the signal is older than 15 minutes." },
  { title: "At most 40 open buys", text: "Caps how many positions can be open at the same time." },
];

export default function Robot({ data }: { data: Data }) {
  const r = data.robot;
  return (
    <div className="grid gap-4 lg:grid-cols-5">
      <div className="grid min-w-0 content-start gap-4 lg:col-span-3">
        {r ? (
          <>
            <div className="grid grid-cols-3 gap-2 sm:gap-3">
              <Stat label="Spent" compact value={usd(r.spent_usd)} />
              <Stat label="Back" compact value={usd(r.back_usd)} />
              <Stat label="Open buys" compact value={String(r.open)} />
            </div>
            <Card title="Robot log" sub="Newest first. Times in UTC.">
              <ul className="divide-y divide-zinc-800">
                {[...r.events].reverse().map((e) => (
                  <li key={e.t + e.title} className="flex items-start gap-3 py-2.5">
                    <span className="w-14 shrink-0 pt-0.5">
                      <Badge tone={TYPE[e.type].tone}>{TYPE[e.type].label}</Badge>
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm text-zinc-200 [overflow-wrap:anywhere]">{e.title}</span>
                      <span className="num block text-xs text-zinc-500">{dateTime(e.t)}</span>
                    </span>
                    <span className={`num shrink-0 text-sm ${e.type === "buy" ? "text-zinc-300" : "text-emerald-400"}`}>
                      {e.usd == null ? "" : e.type === "buy" ? usd(-e.usd) : usd(e.usd, true)}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          </>
        ) : (
          <Card title="Robot log" sub="No robot data is published yet.">
            <p className="text-sm leading-relaxed text-zinc-400">
              The log appears here when the robot has run. Until then, this is how it works and what stops it.
            </p>
          </Card>
        )}
        <Card title="How the robot works">
          <ol className="grid gap-2 text-sm leading-relaxed text-zinc-400">
            <li>
              <span className="text-zinc-200">1.</span> Reads the signals and sells that the live test writes, seconds after a followed trader acts.
            </li>
            <li>
              <span className="text-zinc-200">2.</span> Copies only when a second followed trader bought the same answer within 3 days, or the trader is trusted.
            </li>
            <li>
              <span className="text-zinc-200">3.</span> Fetches a fresh order book and buys with a price limit, then follows the trader's sells.
            </li>
            <li>
              <span className="text-zinc-200">4.</span> Records every buy, sell, skip and settlement, so the real result can be compared with the paper result.
            </li>
          </ol>
        </Card>
      </div>
      <div className="min-w-0 lg:col-span-2">
        <Card title="Safety limits" sub="Hard-coded in scripts/pm_robot.py.">
          <ul className="grid gap-3">
            {LIMITS.map((l) => (
              <li key={l.title} className="flex gap-3">
                <span className="mt-1.5 size-2 shrink-0 rounded-full bg-emerald-400" />
                <span>
                  <span className="block text-sm text-zinc-100">{l.title}</span>
                  <span className="block text-xs leading-relaxed text-zinc-400">{l.text}</span>
                </span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}
