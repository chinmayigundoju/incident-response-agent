import { Evidence, asRecord, asString, formatTime, label } from "../../lib/types";

const GROUPS = ["METRIC", "LOG", "TRACE", "DEPLOYMENT", "RUNBOOK", "RECOVERY", "TOOL_UNAVAILABLE"];

export function EvidencePanel({ evidence }: { evidence: Evidence[] }) {
  const currentEvidence = evidence.filter((item) => item.type !== "HISTORICAL_MEMORY");
  const populatedGroups = GROUPS.filter((type) => currentEvidence.some((item) => item.type === type));

  if (!currentEvidence.length) {
    return <div className="empty">No current telemetry has been persisted yet. Start an investigation to collect evidence.</div>;
  }

  return (
    <div className="grid gap-5">
      {populatedGroups.map((type) => (
        <section key={type}>
          <div className="group-heading">
            <h2>{label(type)}</h2>
            <span>{currentEvidence.filter((item) => item.type === type).length}</span>
          </div>
          <div className="records compact-records">
            {currentEvidence.filter((item) => item.type === type).map((item) => (
              <EvidenceCard item={item} key={item.id} />
            ))}
          </div>
        </section>
      ))}
      {currentEvidence.some((item) => !GROUPS.includes(item.type)) && (
        <section>
          <div className="group-heading"><h2>Other evidence</h2></div>
          <div className="records compact-records">
            {currentEvidence.filter((item) => !GROUPS.includes(item.type)).map((item) => (
              <EvidenceCard item={item} key={item.id} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function EvidenceCard({ item }: { item: Evidence }) {
  const content = asRecord(item.content);
  const summary = asString(content.summary) ?? "Structured evidence captured";
  return (
    <article className="record-card">
      <div className="record-card-heading">
        <div><strong>{item.source}</strong><p>{summary}</p></div>
        <time>{formatTime(item.observed_at)}</time>
      </div>
      <details>
        <summary>View details</summary>
        <pre className="record">{JSON.stringify(content.details ?? content, null, 2)}</pre>
      </details>
    </article>
  );
}
