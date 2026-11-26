import { useEffect, useState } from "react";
import type { Data } from "./types";

// null only when the file is missing (404); other errors are thrown and shown on the page.
async function fetchJson(name: string): Promise<unknown> {
  const res = await fetch(`data/${name}.json`, { cache: "no-cache" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`data/${name}.json: HTTP ${res.status}`);
  return res.json();
}

async function get<T>(name: string): Promise<T> {
  const v = await fetchJson(name);
  if (v == null) throw new Error(`data/${name}.json: HTTP 404`);
  return v as T;
}

async function optional<T>(name: string): Promise<T | null> {
  return (await fetchJson(name)) as T | null;
}

async function loadAll(): Promise<Data> {
  const [summary, runs, equity, traders, latency, robot, replay, replayTrades] = await Promise.all([
    get<Data["summary"]>("summary"),
    get<Data["runs"]>("runs"),
    get<Data["equity"]>("equity"),
    get<Data["traders"]>("traders"),
    get<Data["latency"]>("latency"),
    optional<NonNullable<Data["robot"]>>("robot"),
    optional<NonNullable<Data["replay"]>>("replay"),
    optional<NonNullable<Data["replayTrades"]>>("replay_trades"),
  ]);
  return { summary, runs, equity, traders, latency, robot, replay, replayTrades };
}

export function useData(): { data: Data | null; error: string | null } {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    loadAll().then(setData, (e: unknown) => setError(String(e)));
  }, []);
  return { data, error };
}
