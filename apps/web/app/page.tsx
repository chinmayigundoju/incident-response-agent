"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { SystemStatus } from "../components/system-status";
import { TabOption, Tabs } from "../components/tabs";
import { api } from "../lib/api";
import { AutomationStatus, Incident, formatTime, label } from "../lib/types";

const completedStatuses = new Set(["RESOLVED", "POSTMORTEM_REVIEW", "MEMORY_COMMITTED"]);

type DashboardTab = "active" | "resolved" | "scenarios" | "health";

const SCENARIOS = [
  {
    id: "healthy-baseline",
    title: "Healthy Baseline / Reset",
    description: "Returns simulated services to a healthy baseline.",
    disruptive: false,
  },
  {
    id: "recurring-db-pool",
    title: "Recurring DB Pool",
    description: "Simulates checkout database connection exhaustion after a risky deployment.",
    disruptive: true,
  },
  {
    id: "payment-latency",
    title: "Payment Latency",
    description: "Simulates excessive downstream payment-provider latency.",
    disruptive: true,
  },
  {
    id: "misleading-memory",
    title: "Misleading Memory",
    description: "Produces symptoms similar to a historical incident but with a different live root cause.",
    disruptive: true,
  },
] as const;

export default function Home() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [activeTab, setActiveTab] = useState<DashboardTab>("active");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [scenarioMessage, setScenarioMessage] = useState("");
  const [scenarioFailed, setScenarioFailed] = useState(false);
  const [scenarioBusy, setScenarioBusy] = useState<string | null>(null);
  const [pendingScenario, setPendingScenario] = useState<string | null>(null);
  const [simulatorState, setSimulatorState] = useState<{ scenario: string; state: string } | null>(null);
  const [search, setSearch] = useState("");
  const [automation, setAutomation] = useState<AutomationStatus | null>(null);

  const load = useCallback(async () => {
    try {
      setIncidents(await api.incidents());
      setError("");
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load incidents");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const initial = window.setTimeout(() => void load(), 0);
    const polling = window.setInterval(() => void load(), 5_000);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(polling);
    };
  }, [load]);

  useEffect(() => {
    const controller = new AbortController();
    void api.automationStatus(controller.signal).then(setAutomation).catch(() => undefined);
    return () => controller.abort();
  }, []);

  const newestFirst = useMemo(
    () => [...incidents].sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at)),
    [incidents],
  );
  const active = newestFirst.filter((incident) => !completedStatuses.has(incident.status));
  const resolved = newestFirst.filter((incident) => completedStatuses.has(incident.status));
  const filteredResolved = resolved.filter((incident) => {
    const query = search.trim().toLowerCase();
    return !query || [incident.title, incident.service, incident.environment, incident.status, incident.confirmed_root_cause ?? ""]
      .some((value) => value.toLowerCase().includes(query));
  });

  const tabs: readonly TabOption<DashboardTab>[] = [
    { id: "active", label: "Active Incidents", count: active.length },
    { id: "resolved", label: "Resolved", count: resolved.length },
    { id: "scenarios", label: "Demo Scenarios" },
    { id: "health", label: "System Health" },
  ];

  async function activateScenario(scenario: (typeof SCENARIOS)[number]) {
    if (scenario.disruptive && pendingScenario !== scenario.id) {
      setPendingScenario(scenario.id);
      setScenarioFailed(false);
      setScenarioMessage(`Confirm ${scenario.title} to change the controlled demo environment.`);
      return;
    }
    setPendingScenario(null);
    const existingIds = new Set(incidents.map((incident) => incident.id));
    setScenarioBusy(scenario.id);
    setScenarioFailed(false);
    setScenarioMessage(`Activating ${scenario.title}…`);
    try {
      const result = await api.activateScenario(scenario.id);
      setSimulatorState({ scenario: result.scenario, state: result.state });
      if (!scenario.disruptive) {
        setScenarioMessage(`${scenario.title} activated. Alertmanager will close matching active incidents after its next evaluation.`);
        await load();
        return;
      }
      setScenarioMessage(`${scenario.title} activated. Waiting for Alertmanager to create the incident…`);
      for (let attempt = 0; attempt < 12; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 5_000));
        const refreshed = await api.incidents();
        setIncidents(refreshed);
        const created = refreshed.find(
          (incident) => !existingIds.has(incident.id) && !completedStatuses.has(incident.status),
        );
        if (created) {
          setScenarioMessage(`${scenario.title} created ${created.title}. Open it from Active Incidents.`);
          setActiveTab("active");
          return;
        }
      }
      setScenarioMessage(`${scenario.title} is active, but no new incident was observed within 60 seconds. Check System Health and try Refresh.`);
    } catch (scenarioError) {
      setScenarioFailed(true);
      setScenarioMessage(scenarioError instanceof Error ? scenarioError.message : "Scenario activation failed");
    } finally {
      setScenarioBusy(null);
    }
  }

  return (
    <main className="mx-auto min-h-screen max-w-7xl px-4 py-8 sm:px-6 lg:py-12">
      <header className="flex flex-wrap items-end justify-between gap-6 border-b border-[var(--border)] pb-8">
        <div>
          <p className="eyebrow">Production reliability</p>
          <h1 className="mt-2 text-4xl font-semibold tracking-tight sm:text-5xl">Incident Response Agent</h1>
          <p className="mt-3 text-[var(--muted)]">Evidence-led investigation with human-gated mitigation.</p>
        </div>
        <div className="grid w-full max-w-md gap-3">
          <SystemStatus />
          <div className={`automation-banner ${automation?.simulated_autopilot ? "autopilot" : ""}`}>
            <span>Automation</span>
            <strong>{automation?.label ?? "Loading…"}</strong>
            {automation?.simulated_autopilot && <small>SIMULATED ENVIRONMENT ONLY</small>}
          </div>
        </div>
      </header>

      <div className="mt-7">
        <Tabs tabs={tabs} active={activeTab} onChange={setActiveTab} label="SRE console sections" />
      </div>

      {error && <div className="error-banner mt-5" role="alert">{error}</div>}

      <section className="mt-6" role="tabpanel" aria-label={tabs.find((tab) => tab.id === activeTab)?.label}>
        {activeTab === "active" && (
          <IncidentCollection
            eyebrow="Operations"
            title="Active incidents"
            incidents={active}
            loading={loading}
            empty="No active incidents. Production is stable."
            onRefresh={load}
          />
        )}

        {activeTab === "resolved" && (
          <div className="grid gap-5">
            <div className="toolbar">
              <div><p className="eyebrow">Historical record</p><h2 className="section-title">Resolved incidents</h2></div>
              <input
                type="search"
                className="search-input"
                aria-label="Filter resolved incidents"
                placeholder="Filter title, service, root cause…"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>
            {loading && <div className="empty">Loading resolved incidents…</div>}
            {!loading && filteredResolved.length === 0 && <div className="empty">No resolved incidents match this filter.</div>}
            <div className="incident-grid">
              {filteredResolved.map((incident) => <IncidentCard incident={incident} resolved key={incident.id} />)}
            </div>
          </div>
        )}

        {activeTab === "scenarios" && (
          <div className="grid gap-5">
            <div className="toolbar">
              <div><p className="eyebrow">Controlled environment</p><h2 className="section-title">Demo scenarios</h2></div>
              <div className="simulator-state">
                <span>Simulator state</span>
                <strong>{simulatorState ? `${label(simulatorState.state)} · ${label(simulatorState.scenario)}` : "Reported after activation"}</strong>
              </div>
            </div>
            {scenarioMessage && <p className={scenarioFailed ? "error-banner" : "notice"} role={scenarioFailed ? "alert" : "status"}>{scenarioMessage}</p>}
            <div className="scenario-grid">
              {SCENARIOS.map((scenario) => (
                <article className="scenario-card" key={scenario.id}>
                  <div><p className="eyebrow">{scenario.disruptive ? "Fault simulation" : "Environment control"}</p><h3>{scenario.title}</h3><p>{scenario.description}</p></div>
                  <button disabled={scenarioBusy !== null} className={pendingScenario === scenario.id ? "danger" : scenario.disruptive ? "" : "secondary"} onClick={() => void activateScenario(scenario)}>
                    {scenarioBusy === scenario.id ? "Working…" : pendingScenario === scenario.id ? "Confirm activation" : scenario.disruptive ? "Activate scenario" : "Reset demo"}
                  </button>
                </article>
              ))}
            </div>
          </div>
        )}

        {activeTab === "health" && (
          <div className="grid gap-5">
            <div><p className="eyebrow">Runtime dependencies</p><h2 className="section-title">System health</h2></div>
            <div className="max-w-2xl"><SystemStatus /></div>
            <div className="panel">
              <h3 className="m-0 text-lg">Observability and persistence</h3>
              <p className="mt-2 text-[var(--muted)]">Prometheus, Loki, Tempo, and PostgreSQL do not currently expose health statuses through the console API. Their availability is inspected through bounded tools during incident investigation.</p>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}

function IncidentCollection({
  eyebrow,
  title,
  incidents,
  loading,
  empty,
  onRefresh,
}: {
  eyebrow: string;
  title: string;
  incidents: Incident[];
  loading: boolean;
  empty: string;
  onRefresh: () => Promise<void>;
}) {
  return (
    <div className="grid gap-5">
      <div className="toolbar">
        <div><p className="eyebrow">{eyebrow}</p><h2 className="section-title">{title}</h2></div>
        <button className="secondary" onClick={() => void onRefresh()}>Refresh</button>
      </div>
      {loading && <div className="empty">Loading incident ledger…</div>}
      {!loading && incidents.length === 0 && <div className="empty stable-empty"><strong>{empty}</strong><span>Alertmanager is not reporting an active incident.</span></div>}
      <div className="incident-grid">
        {incidents.map((incident) => <IncidentCard incident={incident} key={incident.id} />)}
      </div>
    </div>
  );
}

function IncidentCard({ incident, resolved = false }: { incident: Incident; resolved?: boolean }) {
  return (
    <article className="incident-card">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className={`severity ${incident.severity.toLowerCase()}`}>{incident.severity}</span>
        <span className="status">{label(incident.status)}</span>
      </div>
      <div>
        <h3>{incident.title}</h3>
        <p className="incident-meta">{incident.service} · {incident.environment}</p>
      </div>
      {incident.summary && <p className="incident-summary">{incident.summary}</p>}
      {resolved && incident.confirmed_root_cause && <p className="root-cause-preview"><strong>Confirmed root cause:</strong> {incident.confirmed_root_cause}</p>}
      <dl className="incident-times">
        <div><dt>Detected</dt><dd>{formatTime(incident.detected_at)}</dd></div>
        {resolved && <div><dt>Resolved</dt><dd>{formatTime(incident.resolved_at)}</dd></div>}
      </dl>
      {incident.status === "MEMORY_COMMITTED" && <div className="memory-indicator">✓ Verified memory committed</div>}
      <Link className="button-link" href={`/incidents/${incident.id}`}>Open Incident</Link>
    </article>
  );
}
