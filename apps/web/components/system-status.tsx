"use client";

import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { StatusCard } from "./status-card";

type State = "checking" | "online" | "unavailable";

export function SystemStatus() {
  const [apiState, setApiState] = useState<State>("checking");
  const [memory, setMemory] = useState<State>("checking");
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      const [health, memoryHealth] = await Promise.allSettled([
        api.health(controller.signal),
        api.memoryHealth(controller.signal),
      ]);
      if (controller.signal.aborted) return;
      setApiState(health.status === "fulfilled" ? "online" : "unavailable");
      setMemory(
        memoryHealth.status === "fulfilled" && memoryHealth.value.available
          ? "online"
          : "unavailable",
      );
    }
    void load();
    return () => controller.abort();
  }, []);

  const apiLabel = apiState === "checking" ? "API: Checking" : apiState === "online" ? "API: Online" : "API: Unavailable";
  const memoryLabel = memory === "checking" ? "Memory: Checking" : memory === "online" ? "Memory: Online" : "Memory: Unavailable";

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <StatusCard label="Application backend" value={apiLabel} tone={apiState} />
      <StatusCard label="Verified incident memory" value={memoryLabel} tone={memory} />
    </div>
  );
}
