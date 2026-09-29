"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { EvidencePanel } from "../../../components/incidents/evidence-panel";
import { MemoryPanel } from "../../../components/incidents/memory-panel";
import { TabOption, Tabs } from "../../../components/tabs";
import { api, getIncidentBundle } from "../../../lib/api";
import {
  AutomationStatus,
  Evidence,
  Hypothesis,
  Incident,
  IncidentEvent,
  JsonRecord,
  MemoryCommitResult,
  Postmortem,
  Recommendation,
  asRecord,
  asString,
  formatTime,
  label,
} from "../../../lib/types";

type IncidentTab = "overview" | "evidence" | "memory" | "diagnosis" | "action" | "timeline" | "postmortem";

const TAB_OPTIONS: readonly TabOption<IncidentTab>[] = [
  { id: "overview", label: "Overview" },
  { id: "evidence", label: "Evidence" },
  { id: "memory", label: "Memory" },
  { id: "diagnosis", label: "Diagnosis" },
  { id: "action", label: "Action" },
  { id: "timeline", label: "Timeline" },
  { id: "postmortem", label: "Postmortem" },
];

const PROGRESS = [
  "Detected",
  "Investigating",
  "Diagnosis",
  "Approval",
  "Mitigation",
  "Verification",
  "Resolved",
  "Postmortem",
  "Memory",
] as const;

const STATUS_STAGE: Record<string, number> = {
  DETECTED: 0,
  TRIAGED: 0,
  INVESTIGATING: 1,
  DIAGNOSIS_PROPOSED: 2,
  MITIGATION_PROPOSED: 2,
  AWAITING_APPROVAL: 3,
  MITIGATING: 4,
  VERIFYING_RECOVERY: 5,
  RESOLVED: 6,
  POSTMORTEM_REVIEW: 7,
  MEMORY_COMMITTED: 8,
};

const POLLING_STATUSES = new Set(["DETECTED", "TRIAGED", "INVESTIGATING", "MITIGATING", "VERIFYING_RECOVERY"]);

export default function IncidentDetail() {
  const { id } = useParams<{ id: string }>();
  const [incident, setIncident] = useState<Incident | null>(null);
  const [events, setEvents] = useState<IncidentEvent[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [postmortem, setPostmortem] = useState<Postmortem | null>(null);
  const [activeTab, setActiveTab] = useState<IncidentTab>("overview");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [operation, setOperation] = useState("");
  const [notice, setNotice] = useState("");
  const [operationFailed, setOperationFailed] = useState(false);
  const [error, setError] = useState("");
  const [approver, setApprover] = useState("operator@example.com");
  const [approvalComment, setApprovalComment] = useState("");
  const [rootCause, setRootCause] = useState("");
  const [verificationComment, setVerificationComment] = useState("");
  const [postmortemComment, setPostmortemComment] = useState("");
  const [memoryCommit, setMemoryCommit] = useState<MemoryCommitResult | null>(null);
  const [automation, setAutomation] = useState<AutomationStatus | null>(null);

  const load = useCallback(async () => {
    try {
      const bundle = await getIncidentBundle(id);
      setIncident(bundle.incident);
      setEvents(bundle.events);
      setEvidence(bundle.evidence);
      setHypotheses(bundle.hypotheses);
      setRecommendations(bundle.recommendations);
      setPostmortem(bundle.postmortem);
      setError(bundle.unavailable.length ? `Some incident data is temporarily unavailable: ${bundle.unavailable.join(", ")}.` : "");
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load incident");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    const initial = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(initial);
  }, [load]);

  useEffect(() => {
    const controller = new AbortController();
    void api.automationStatus(controller.signal).then(setAutomation).catch(() => undefined);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!incident || busy) return;
    const latest = recommendations.at(-1);
    const shouldPoll = POLLING_STATUSES.has(incident.status)
      || (incident.status === "AWAITING_APPROVAL" && latest?.status === "APPROVED" && automation?.mode !== "manual")
      || (incident.status === "RESOLVED" && Boolean(incident.confirmed_root_cause) && automation?.mode !== "manual")
      || (incident.status === "POSTMORTEM_REVIEW" && Boolean(postmortem?.approved_at) && automation?.mode !== "manual");
    if (!shouldPoll) return;
    const timer = window.setInterval(() => void load(), 5_000);
    return () => window.clearInterval(timer);
  }, [automation?.mode, busy, incident, load, postmortem?.approved_at, recommendations]);

  async function runOperation(
    labelText: string,
    action: () => Promise<unknown>,
    onSuccess?: (result: unknown) => void,
  ) {
    setBusy(true);
    setOperation(labelText);
    setNotice("");
    setOperationFailed(false);
    try {
      const result = await action();
      onSuccess?.(result);
      setNotice(`${labelText} completed successfully.`);
      await load();
    } catch (mutationError) {
      setOperationFailed(true);
      setNotice(mutationError instanceof Error ? mutationError.message : "Operation failed");
    } finally {
      setBusy(false);
      setOperation("");
    }
  }

  const diagnosis = useMemo(() => {
    const event = [...events].reverse().find((item) => item.event_type === "DIAGNOSIS_PROPOSED");
    return asRecord(asRecord(event?.payload).diagnosis);
  }, [events]);

  if (loading && !incident) return <main className="mx-auto max-w-7xl p-8">Loading incident command center…</main>;
  if (!incident) return <main className="mx-auto max-w-7xl p-8"><div className="error-banner">{error || "Incident not found."}</div></main>;

  const latestRecommendation = recommendations.at(-1) ?? null;
  const currentStage = STATUS_STAGE[incident.status] ?? 0;
  const diagnosisHypothesis = asRecord(diagnosis.primary_hypothesis);
  const automatic = automation?.mode !== undefined && automation.mode !== "manual";
  const automationCopy = automationMessage(incident, latestRecommendation, postmortem, events);

  return (
    <main className="mx-auto min-h-screen max-w-7xl px-4 py-8 sm:px-6 lg:py-10">
      <Link href="/" className="text-sm text-[var(--accent)]">← SRE console</Link>

      <header className="incident-header">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={`severity ${incident.severity.toLowerCase()}`}>{incident.severity}</span>
            <span className="status">{label(incident.status)}</span>
          </div>
          <h1>{incident.title}</h1>
          <p>{incident.service} · {incident.environment} · detected {formatTime(incident.detected_at)}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="secondary" disabled={busy} onClick={() => void load()}>Refresh</button>
          {incident.status === "VERIFYING_RECOVERY" && !automatic && (
            <button disabled={busy} onClick={() => void runOperation("Recovery verification", () => api.verifyRecovery(id))}>Verify recovery</button>
          )}
        </div>
      </header>

      <div className="warning mt-5">
        <strong>Human approval boundary:</strong> the agent may investigate and propose mitigation. An identified operator must approve disruptive remediation before a separate execution step.
      </div>
      {automation && (
        <div className={`automation-banner mt-4 ${automation.simulated_autopilot ? "autopilot" : ""}`} role="status">
          <span>Automation: {automation.label}</span>
          <strong>{automationCopy}</strong>
          {automation.simulated_autopilot && <small>DEMO AUTOPILOT — SIMULATED ENVIRONMENT ONLY</small>}
        </div>
      )}
      {error && <div className="error-banner mt-4" role="alert">{error}</div>}
      {notice && <div className={`${operationFailed ? "error-banner" : "notice"} mt-4`} role={operationFailed ? "alert" : "status"}>{notice}</div>}
      {busy && <div className="operation-progress mt-4" role="status"><span className="activity-dot" />{operation}</div>}

      <div className="mt-6">
        <Tabs tabs={TAB_OPTIONS} active={activeTab} onChange={setActiveTab} label="Incident detail sections" />
      </div>

      <section className="tab-panel" role="tabpanel" aria-label={TAB_OPTIONS.find((tab) => tab.id === activeTab)?.label}>
        {activeTab === "overview" && (
          <Overview
            incident={incident}
            recommendation={latestRecommendation}
            currentStage={currentStage}
            busy={busy}
            operation={operation}
            automatic={automatic}
            onInvestigate={() => void runOperation(
              "AI investigation",
              () => api.investigate(id),
              () => setActiveTab("diagnosis"),
            )}
          />
        )}
        {activeTab === "evidence" && <EvidencePanel evidence={evidence} />}
        {activeTab === "memory" && <MemoryPanel evidence={evidence} />}
        {activeTab === "diagnosis" && (
          <DiagnosisPanel
            incident={incident}
            hypotheses={hypotheses}
            diagnosis={diagnosis}
            diagnosisHypothesis={diagnosisHypothesis}
            recommendation={latestRecommendation}
          />
        )}
        {activeTab === "action" && (
          <ActionPanel
            recommendations={recommendations}
            events={events}
            approver={approver}
            setApprover={setApprover}
            comment={approvalComment}
            setComment={setApprovalComment}
            incidentStatus={incident.status}
            busy={busy}
            automatic={automatic}
            onDecision={(recommendationId, decision) => void runOperation(
              decision === "approve" ? "Recommendation approval" : "Recommendation rejection",
              () => decision === "approve"
                ? api.approveRecommendation(id, recommendationId, { approver_identifier: approver, comment: approvalComment.trim() || null })
                : api.rejectRecommendation(id, recommendationId, { approver_identifier: approver, comment: approvalComment.trim() || null }),
            )}
            onExecute={(recommendationId) => void runOperation(
              "Controlled remediation",
              () => api.executeRecommendation(id, recommendationId),
            )}
            onVerifyRecovery={() => void runOperation("Recovery verification", () => api.verifyRecovery(id))}
          />
        )}
        {activeTab === "timeline" && <TimelinePanel events={events} />}
        {activeTab === "postmortem" && (
          <PostmortemPanel
            incident={incident}
            postmortem={postmortem}
            approver={approver}
            setApprover={setApprover}
            rootCause={rootCause}
            setRootCause={setRootCause}
            verificationComment={verificationComment}
            setVerificationComment={setVerificationComment}
            postmortemComment={postmortemComment}
            setPostmortemComment={setPostmortemComment}
            memoryCommit={memoryCommit}
            busy={busy}
            automatic={automatic}
            onConfirm={() => void runOperation(
              "Root-cause confirmation",
              () => api.confirmRootCause(id, {
                confirmed_root_cause: rootCause,
                verification_comment: verificationComment,
                approver_identifier: approver,
              }),
            )}
            onGenerate={() => void runOperation("Postmortem generation", () => api.generatePostmortem(id))}
            onApprove={() => void runOperation(
              "Postmortem approval",
              () => api.approvePostmortem(id, {
                approver_identifier: approver,
                comment: postmortemComment.trim() || null,
              }),
            )}
            onCommit={() => void runOperation(
              "Verified memory commit",
              () => api.commitMemory(id),
              (result) => setMemoryCommit(result as MemoryCommitResult),
            )}
          />
        )}
      </section>
    </main>
  );
}

function Overview({
  incident,
  recommendation,
  currentStage,
  busy,
  operation,
  automatic,
  onInvestigate,
}: {
  incident: Incident;
  recommendation: Recommendation | null;
  currentStage: number;
  busy: boolean;
  operation: string;
  automatic: boolean;
  onInvestigate: () => void;
}) {
  const canInvestigate = ["DETECTED", "TRIAGED", "INVESTIGATING"].includes(incident.status);
  return (
    <div className="grid gap-5">
      <div className="overview-grid">
        <section className="panel">
          <p className="eyebrow">Incident state</p>
          <h2 className="section-title">Current summary</h2>
          <p className="prose-copy">{incident.summary || "No operator summary has been recorded yet."}</p>
          <div className="key-value-grid">
            <Info label="Lifecycle" value={label(incident.status)} />
            <Info label="Service" value={incident.service} />
            <Info label="Environment" value={incident.environment} />
            <Info label="Severity" value={incident.severity} />
            <Info label="Detected" value={formatTime(incident.detected_at)} />
            <Info label="Resolved" value={formatTime(incident.resolved_at)} />
          </div>
          {canInvestigate && automatic && <div className="operation-progress mt-5"><span className="activity-dot" />Automatic investigation started</div>}
          {canInvestigate && !automatic && <button className="mt-5" disabled={busy} onClick={onInvestigate}>{busy && operation === "AI investigation" ? "Investigation running…" : "Run AI Investigation"}</button>}
        </section>
        <section className="panel">
          <p className="eyebrow">Human verified</p>
          <h2 className="section-title">Root cause and recommendation</h2>
          <div className="callout-block">
            <span>Confirmed root cause</span>
            <strong>{incident.confirmed_root_cause || "Not human-confirmed"}</strong>
          </div>
          <div className="callout-block">
            <span>Current recommendation</span>
            <strong>{recommendation?.description ?? "No action recommended yet"}</strong>
            {recommendation && <small>{recommendation.risk_level} risk · {label(recommendation.status)}</small>}
          </div>
        </section>
      </div>
      <section className="panel">
        <p className="eyebrow">Investigation progress</p>
        <h2 className="section-title">Bounded incident lifecycle</h2>
        <ol className="progress-track">
          {PROGRESS.map((stage, index) => (
            <li className={index < currentStage ? "complete" : index === currentStage ? "current" : "pending"} key={stage}>
              <span>{index < currentStage ? "✓" : index + 1}</span><strong>{stage}</strong>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

function DiagnosisPanel({
  incident,
  hypotheses,
  diagnosis,
  diagnosisHypothesis,
  recommendation,
}: {
  incident: Incident;
  hypotheses: Hypothesis[];
  diagnosis: JsonRecord;
  diagnosisHypothesis: JsonRecord;
  recommendation: Recommendation | null;
}) {
  if (!hypotheses.length && Object.keys(diagnosis).length === 0) {
    return <div className="empty">No diagnosis has been proposed. Current evidence must be collected first.</div>;
  }
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <section className="panel">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div><p className="eyebrow">AI assessment</p><h2 className="section-title">Proposed diagnosis</h2></div>
          <span className="proposal-badge">PROPOSED · NOT VERIFIED</span>
        </div>
        <div className="key-value-grid mt-5">
          <Info label="Primary hypothesis" value={asString(diagnosisHypothesis.statement) ?? hypotheses.at(-1)?.statement ?? "Not supplied"} />
          <Info label="Confidence" value={asString(diagnosisHypothesis.confidence) ?? hypotheses.at(-1)?.confidence ?? "Not supplied"} />
          <Info label="Hypothesis status" value={asString(diagnosisHypothesis.status) ?? hypotheses.at(-1)?.status ?? "Not supplied"} />
          <Info label="Proposed root cause" value={asString(diagnosis.root_cause_statement) ?? "Not supplied"} />
        </div>
      </section>
      <section className="panel">
        <p className="eyebrow">Verification boundary</p>
        <h2 className="section-title">Human confirmation</h2>
        <div className={incident.confirmed_root_cause ? "confirmed-block" : "empty mt-4"}>
          <strong>{incident.confirmed_root_cause ? "HUMAN CONFIRMED" : "Not confirmed"}</strong>
          <p>{incident.confirmed_root_cause ?? "An operator must verify root cause after recovery before this becomes organizational memory."}</p>
        </div>
      </section>
      <section className="panel">
        <p className="eyebrow">Evidence ledger</p>
        <h2 className="section-title">Support, contradictions, uncertainty</h2>
        <ReferenceList label="Supporting evidence" value={diagnosis.supporting_evidence ?? diagnosisHypothesis.supporting_evidence_ids} />
        <ReferenceList label="Contradicting evidence" value={diagnosis.contradicting_evidence ?? diagnosisHypothesis.contradicting_evidence_ids} />
        <ReferenceList label="Remaining uncertainties" value={diagnosis.remaining_uncertainties} />
      </section>
      <section className="panel">
        <p className="eyebrow">Recommendation context</p>
        <h2 className="section-title">Precedent and rationale</h2>
        <div className="callout-block"><span>Historical precedent</span><strong>{asString(diagnosis.historical_precedent) ?? "None cited"}</strong></div>
        <div className="callout-block"><span>Recommended next step</span><strong>{recommendation?.description ?? asString(diagnosis.recommended_next_step) ?? "None"}</strong></div>
        <div className="callout-block"><span>Recommended action</span><strong>{recommendation?.action_type ?? asString(diagnosis.recommended_action) ?? "None"}</strong></div>
        <div className="callout-block"><span>Rationale</span><strong>{recommendation?.rationale ?? asString(diagnosis.action_rationale) ?? "Not supplied"}</strong></div>
        <div className="callout-block"><span>Risk level</span><strong>{recommendation?.risk_level ?? asString(diagnosis.risk_level) ?? "Not supplied"}</strong></div>
      </section>
    </div>
  );
}

function ActionPanel({
  recommendations,
  events,
  approver,
  setApprover,
  comment,
  setComment,
  incidentStatus,
  busy,
  automatic,
  onDecision,
  onExecute,
  onVerifyRecovery,
}: {
  recommendations: Recommendation[];
  events: IncidentEvent[];
  approver: string;
  setApprover: (value: string) => void;
  comment: string;
  setComment: (value: string) => void;
  incidentStatus: string;
  busy: boolean;
  automatic: boolean;
  onDecision: (recommendationId: string, decision: "approve" | "reject") => void;
  onExecute: (recommendationId: string) => void;
  onVerifyRecovery: () => void;
}) {
  const approvalEvents = events.filter((event) => ["MITIGATION_APPROVED", "MITIGATION_REJECTED"].includes(event.event_type));
  const executionEvents = events.filter((event) => ["MITIGATION_EXECUTED", "MITIGATION_FAILED"].includes(event.event_type));
  return (
    <div className="grid gap-5">
      <div className="warning"><strong>Human approval required before disruptive remediation.</strong> {automatic ? "Approval starts the existing audited execution and recovery workflow automatically." : "Approval and execution remain separate, audited actions."}</div>
      {incidentStatus === "MITIGATING" && <div className="operation-progress"><span className="activity-dot" />Mitigation is in progress. Waiting for the controlled action result.</div>}
      {incidentStatus === "VERIFYING_RECOVERY" && <div className="notice"><strong>{automatic ? "Verifying recovery automatically." : "Recovery verification is ready."}</strong> Current Prometheus telemetry determines whether the incident resolves. {!automatic && <button className="ml-3" disabled={busy} onClick={onVerifyRecovery}>Verify recovery</button>}</div>}
      {incidentStatus === "RESOLVED" && <div className="memory-indicator">✓ Recovery was verified and the incident is resolved.</div>}
      <div className="form-grid">
        <label className="field-label">Approver identifier<input required aria-label="Approver identifier" value={approver} onChange={(event) => setApprover(event.target.value)} /></label>
        <label className="field-label">Optional decision comment<input value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Reason for approval or rejection" /></label>
      </div>
      {!recommendations.length && <div className="empty">No mitigation has been proposed.</div>}
      <div className="grid gap-4 lg:grid-cols-2">
        {recommendations.map((item) => (
          <article className="panel" key={item.id}>
            <div className="flex flex-wrap items-center justify-between gap-2"><span className="status">{label(item.status)}</span><span className="status">{item.risk_level} risk</span></div>
            <h2 className="section-title mt-4">{item.description}</h2>
            <p className="prose-copy">{item.rationale}</p>
            <div className="key-value-grid"><Info label="Action" value={item.action_type} /><Info label="Approval" value={item.approval_required ? "Required" : "Not required"} /></div>
            {item.status === "PENDING" && (
              <div className="mt-4 flex flex-wrap gap-2">
                <button disabled={busy || !approver.trim()} onClick={() => onDecision(item.id, "approve")}>Approve</button>
                <button className="danger" disabled={busy || !approver.trim()} onClick={() => onDecision(item.id, "reject")}>Reject</button>
              </div>
            )}
            {item.status === "APPROVED" && incidentStatus === "AWAITING_APPROVAL" && automatic && <div className="operation-progress mt-4"><span className="activity-dot" />Approval recorded. Executing the allowlisted mitigation automatically.</div>}
            {item.status === "APPROVED" && incidentStatus === "AWAITING_APPROVAL" && !automatic && <button className="mt-4" disabled={busy} onClick={() => onExecute(item.id)}>Execute approved action</button>}
          </article>
        ))}
      </div>
      <div className="overview-grid">
        <EventHistory title="Approval history" events={approvalEvents} empty="No approval decision recorded." />
        <EventHistory title="Execution history" events={executionEvents} empty="No action execution recorded." />
      </div>
    </div>
  );
}

function TimelinePanel({ events }: { events: IncidentEvent[] }) {
  const chronological = [...events].sort((left, right) => Date.parse(left.occurred_at) - Date.parse(right.occurred_at));
  if (!chronological.length) return <div className="empty">No lifecycle events have been persisted.</div>;
  return (
    <ol className="timeline-list">
      {chronological.map((event) => (
        <li key={event.id}>
          <span className="timeline-dot" />
          <article className="record-card">
            <div className="record-card-heading"><strong>{label(event.event_type)}</strong><time>{formatTime(event.occurred_at)}</time></div>
            <p>{event.actor_type} · {event.source}</p>
            {Object.keys(event.payload).length > 0 && <details><summary>View event details</summary><pre className="record">{JSON.stringify(event.payload, null, 2)}</pre></details>}
          </article>
        </li>
      ))}
    </ol>
  );
}

function PostmortemPanel({
  incident,
  postmortem,
  approver,
  setApprover,
  rootCause,
  setRootCause,
  verificationComment,
  setVerificationComment,
  postmortemComment,
  setPostmortemComment,
  memoryCommit,
  busy,
  automatic,
  onConfirm,
  onGenerate,
  onApprove,
  onCommit,
}: {
  incident: Incident;
  postmortem: Postmortem | null;
  approver: string;
  setApprover: (value: string) => void;
  rootCause: string;
  setRootCause: (value: string) => void;
  verificationComment: string;
  setVerificationComment: (value: string) => void;
  postmortemComment: string;
  setPostmortemComment: (value: string) => void;
  memoryCommit: MemoryCommitResult | null;
  busy: boolean;
  automatic: boolean;
  onConfirm: () => void;
  onGenerate: () => void;
  onApprove: () => void;
  onCommit: () => void;
}) {
  return (
    <div className="grid gap-5">
      {!postmortem && <div className="empty"><strong>Postmortem has not been generated yet.</strong>{incident.status !== "RESOLVED" && <span> It becomes available after incident resolution and root-cause confirmation.</span>}</div>}
      {incident.status === "RESOLVED" && !incident.confirmed_root_cause && (
        <section className="panel">
          <p className="eyebrow">Human verification</p><h2 className="section-title">Confirm root cause</h2>
          <p className="prose-copy">This confirmation is required before generating a postmortem or committing verified memory.</p>
          <div className="form-grid">
            <label className="field-label">Approver identifier<input required value={approver} onChange={(event) => setApprover(event.target.value)} /></label>
            <label className="field-label full-width">Confirmed root cause<textarea value={rootCause} onChange={(event) => setRootCause(event.target.value)} placeholder="Describe the human-verified root cause…" /></label>
            <label className="field-label full-width">Verification comment<textarea value={verificationComment} onChange={(event) => setVerificationComment(event.target.value)} placeholder="Describe how the root cause was verified…" /></label>
          </div>
          <button className="mt-4" disabled={busy || !approver.trim() || rootCause.trim().length < 10 || !verificationComment.trim()} onClick={onConfirm}>Confirm root cause</button>
        </section>
      )}
      {incident.status === "RESOLVED" && incident.confirmed_root_cause && !postmortem && (
        <section className="panel"><p className="eyebrow">Review and learning</p><h2 className="section-title">Ready for postmortem</h2><p className="prose-copy">The root cause is human-confirmed. {automatic ? "A reviewable draft is being generated automatically from the persisted incident ledger." : "Generate a reviewable draft from the persisted incident ledger."}</p>{!automatic && <button disabled={busy} onClick={onGenerate}>Generate postmortem</button>}</section>
      )}
      {postmortem && (
        <section className="panel">
          <div className="toolbar"><div><p className="eyebrow">{postmortem.approved_at ? "Final" : "Draft"}</p><h2 className="section-title">Incident postmortem</h2></div><span className="status">{postmortem.approved_at ? "APPROVED" : "REVIEW REQUIRED"}</span></div>
          <div className="key-value-grid mt-4"><Info label="Approved by" value={postmortem.approved_by ?? "Not approved"} /><Info label="Approval time" value={formatTime(postmortem.approved_at)} /></div>
          <pre className="postmortem-copy">{postmortem.final_markdown ?? postmortem.draft_markdown}</pre>
          {incident.status === "POSTMORTEM_REVIEW" && !postmortem.approved_at && (
            <div className="form-grid mt-4"><label className="field-label">Approver identifier<input required value={approver} onChange={(event) => setApprover(event.target.value)} /></label><label className="field-label">Optional approval comment<input value={postmortemComment} onChange={(event) => setPostmortemComment(event.target.value)} /></label><div><button disabled={busy || !approver.trim()} onClick={onApprove}>Approve postmortem</button></div></div>
          )}
          {incident.status === "POSTMORTEM_REVIEW" && postmortem.approved_at && automatic && <div className="operation-progress mt-4"><span className="activity-dot" />Committing verified incident knowledge to Hindsight…</div>}
          {incident.status === "POSTMORTEM_REVIEW" && postmortem.approved_at && !automatic && <button className="mt-4" disabled={busy} onClick={onCommit}>Commit Verified Memory</button>}
          {incident.status === "MEMORY_COMMITTED" && <div className="memory-indicator mt-4">✓ Approved postmortem committed to verified Hindsight memory</div>}
          {memoryCommit && <div className="key-value-grid mt-4"><Info label="Bank" value={memoryCommit.bank_id ?? "Configured Hindsight bank"} /><Info label="Document" value={memoryCommit.document_id} /><Info label="Retained" value={memoryCommit.retained === undefined ? memoryCommit.status ?? "Succeeded" : memoryCommit.retained ? "Yes" : "No"} /></div>}
        </section>
      )}
    </div>
  );
}

function EventHistory({ title, events, empty }: { title: string; events: IncidentEvent[]; empty: string }) {
  return <section className="panel"><p className="eyebrow">Audit trail</p><h2 className="section-title">{title}</h2><div className="records compact-records">{events.map((event) => <div className="record-card" key={event.id}><strong>{label(event.event_type)}</strong><p>{formatTime(event.occurred_at)} · {event.actor_type}</p>{Object.keys(event.payload).length > 0 && <details><summary>View result</summary><pre className="record">{JSON.stringify(event.payload, null, 2)}</pre></details>}</div>)}{!events.length && <p className="empty">{empty}</p>}</div></section>;
}

function ReferenceList({ label: title, value }: { label: string; value: unknown }) {
  const values = Array.isArray(value) ? value.map(String) : [];
  return <div className="reference-list"><strong>{title}</strong>{values.length ? <ul>{values.map((item) => <li key={item}>{item}</li>)}</ul> : <p>None recorded</p>}</div>;
}

function automationMessage(
  incident: Incident,
  recommendation: Recommendation | null,
  postmortem: Postmortem | null,
  events: IncidentEvent[],
): string {
  const failure = [...events].reverse().find((event) => event.event_type === "AUTOMATION_FAILED");
  const laterSuccess = failure
    ? events.some((event) => Date.parse(event.occurred_at) > Date.parse(failure.occurred_at) && event.event_type.startsWith("AUTO_"))
    : false;
  if (failure && !laterSuccess) {
    const stage = asString(asRecord(failure.payload).stage);
    return `Automation stopped safely${stage ? ` during ${label(stage)}` : ""}. Operator review is required.`;
  }
  if (["DETECTED", "TRIAGED"].includes(incident.status)) return "Automatic investigation started";
  if (incident.status === "INVESTIGATING") return "Collecting current evidence and organizational memory…";
  if (["DIAGNOSIS_PROPOSED", "MITIGATION_PROPOSED"].includes(incident.status)) return "Persisting the diagnosis and recommendation…";
  if (incident.status === "AWAITING_APPROVAL") {
    return recommendation?.status === "APPROVED"
      ? "Human approval recorded — automatic mitigation is starting."
      : "AI investigation complete — human approval required.";
  }
  if (incident.status === "MITIGATING") return "Executing the approved allowlisted mitigation…";
  if (incident.status === "VERIFYING_RECOVERY") return "Verifying recovery from current Prometheus telemetry…";
  if (incident.status === "RESOLVED") {
    return incident.confirmed_root_cause
      ? "Root cause confirmed — generating the draft postmortem automatically…"
      : "Recovery verified — human root-cause confirmation required.";
  }
  if (incident.status === "POSTMORTEM_REVIEW") {
    return postmortem?.approved_at
      ? "Committing verified incident knowledge to Hindsight…"
      : "Draft postmortem ready — human review and approval required.";
  }
  if (incident.status === "MEMORY_COMMITTED") return "Verified organizational memory committed.";
  return "Automation is monitoring the incident lifecycle.";
}

function Info({ label: title, value }: { label: string; value: string }) {
  return <div><span>{title}</span><strong>{value}</strong></div>;
}
