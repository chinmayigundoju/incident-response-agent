import { Evidence, asRecord, asString } from "../../lib/types";

export function MemoryPanel({ evidence }: { evidence: Evidence[] }) {
  const historical = evidence.filter((item) => item.type === "HISTORICAL_MEMORY");
  const memories = historical.flatMap((item) => {
    const content = asRecord(item.content);
    const details = asRecord(content.details);
    const values = Array.isArray(details.memories) ? details.memories : [];
    return values.map((value) => asRecord(value));
  });

  return (
    <div className="grid gap-5">
      <div className="warning">
        <strong>Historical memory is precedent, not proof.</strong> The agent verifies it against current telemetry before proposing a diagnosis.
      </div>
      <section className="panel nested-panel">
        <p className="eyebrow">Hindsight Organizational Memory</p>
        <h2 className="section-title">Verified historical incidents</h2>
        {!historical.length && <p className="empty mt-4">No historical incident memory was used in this investigation.</p>}
        {historical.length > 0 && memories.length === 0 && (
          <p className="empty mt-4">Hindsight was queried, but no verified historical incident matched.</p>
        )}
        <div className="records compact-records">
          {memories.map((memory, index) => {
            const metadata = asRecord(memory.metadata);
            return (
              <article className="record-card" key={`${asString(memory.source_document) ?? "memory"}-${index}`}>
                <div className="memory-grid">
                  <Info label="Previous incident" value={asString(metadata.incident_id) ?? "Not supplied"} />
                  <Info label="Service" value={asString(metadata.service) ?? "Not supplied"} />
                  <Info label="Environment" value={asString(metadata.environment) ?? "Not supplied"} />
                  <Info label="Verified" value={metadata.verified === true ? "Yes" : metadata.verified === false ? "No" : "Recorded as verified memory"} />
                  <Info label="Relevance" value={typeof memory.relevance === "number" ? memory.relevance.toFixed(3) : "Not supplied"} />
                  <Info label="Source document" value={asString(memory.source_document) ?? "Not supplied"} />
                </div>
                <p className="memory-text">{asString(memory.text) ?? "No memory text was returned."}</p>
                {Object.keys(metadata).length > 0 && (
                  <details><summary>View memory metadata</summary><pre className="record">{JSON.stringify(metadata, null, 2)}</pre></details>
                )}
                {Object.keys(asRecord(memory.ranking)).length > 0 && (
                  <details><summary>View ranking details</summary><pre className="record">{JSON.stringify(memory.ranking, null, 2)}</pre></details>
                )}
              </article>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}
