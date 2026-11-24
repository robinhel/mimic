import { useEffect, useState } from "react";
import type { Data } from "./types";

async function get<T>(name: string): Promise<T> {
  const res = await fetch(`data/${name}.json`, { cache: "no-cache" });
  if (!res.ok) throw new Error(`data/${name}.json: HTTP ${res.status}`);
  return (await res.json()) as T;
}

async function optional<T>(name: string): Promise<T | null> {
  try {
    return await get<T>(name);
  } catch {
    return null;
  }
}

async function loadAll(): Promise<Data> {
  const [summary, runs, equity, traders, latency, robot] = await Promise.all([
    get<Data["summary"]>("summary"),
    get<Data["runs"]>("runs"),
    get<Data["equity"]>("equity"),
    get<Data["traders"]>("traders"),
    get<Data["latency"]>("latency"),
    optional<NonNullable<Data["robot"]>>("robot"),
  ]);
  return { summary, runs, equity, traders, latency, robot };
}

export function useData(): { data: Data | null; error: string | null } {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    loadAll().then(setData, (e: unknown) => setError(String(e)));
  }, []);
  return { data, error };
}
