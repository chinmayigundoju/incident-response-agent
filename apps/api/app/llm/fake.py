from app.agent.schemas import (
    ActionType,
    AgentHypothesis,
    Confidence,
    Diagnosis,
    EvidenceType,
    HypothesisStatus,
    InvestigationEvidence,
    ToolRequest,
)


class FakeProvider:
    """Deterministic provider for tests and generated offline evaluation only."""

    def _plan(self, service: str) -> list[str]:
        diagnostic_log = (
            "search_payment_latency_logs"
            if service.removeprefix("demo-") == "payment"
            else "search_connection_timeout_logs"
        )
        return [
            "get_db_pool_state",
            "get_payment_latency",
            diagnostic_log,
            "search_recent_traces",
            "get_recent_deployments" if service != "payment" else "search_error_logs",
            "get_runbook",
            "recall_incidents",
        ]

    async def next_step(
        self,
        *,
        incident: dict[str, object],
        evidence: list[InvestigationEvidence],
        called_tools: list[str],
        force_diagnosis: bool = False,
    ) -> ToolRequest | Diagnosis:
        plan = self._plan(str(incident.get("service", "checkout")))
        for tool in plan:
            if tool not in called_tools:
                return ToolRequest(
                    name=tool,
                    arguments={},
                    rationale=f"Collect bounded {tool} evidence",
                )
        service = str(incident.get("service", "checkout")).removeprefix("demo-")
        usable = [item for item in evidence if item.type != EvidenceType.TOOL_UNAVAILABLE]
        supporting = [item.id for item in usable]
        historical = next(
            (item for item in evidence if item.type == EvidenceType.HISTORICAL_MEMORY), None
        )
        if service == "payment":
            contradicting = [
                item.id
                for item in evidence
                if item.source in {"get_db_pool_state", "search_connection_timeout_logs"}
            ]
            hypothesis = AgentHypothesis(
                statement="Payment dependency latency is exhausting the checkout request budget",
                status=HypothesisStatus.SUPPORTED,
                confidence=Confidence.HIGH,
                supporting_evidence_ids=supporting,
                contradicting_evidence_ids=contradicting,
            )
            return Diagnosis(
                primary_hypothesis=hypothesis,
                root_cause_statement=(
                    "Current payment latency evidence supports a payment-provider impairment; "
                    "healthy DB evidence contradicts historical DB-pool transfer"
                ),
                supporting_evidence=supporting,
                contradicting_evidence=contradicting,
                remaining_uncertainties=["External provider cause is outside the demo boundary"],
                historical_precedent=(historical.summary if historical else None),
                recommended_next_step="Request approval to reset the simulated payment fault",
                recommended_action=ActionType.RESET_PAYMENT_FAULT,
                action_rationale="Bound downstream latency while the provider is impaired",
                risk_level="MEDIUM",
            )
        hypothesis = AgentHypothesis(
            statement="Checkout v2.18 configuration reduced the DB pool and exhausted capacity",
            status=HypothesisStatus.SUPPORTED,
            confidence=Confidence.HIGH,
            supporting_evidence_ids=supporting,
        )
        return Diagnosis(
            primary_hypothesis=hypothesis,
            root_cause_statement=(
                "Checkout DB pool exhaustion is associated with the recent v2.18 pool reduction"
            ),
            supporting_evidence=supporting,
            remaining_uncertainties=["Human confirmation remains required"],
            historical_precedent=historical.summary if historical else None,
            recommended_next_step="Request approval for the controlled demo rollback",
            recommended_action=ActionType.ROLLBACK_CHECKOUT_DEMO,
            action_rationale="Current telemetry and deployment timing support rollback",
            risk_level="MEDIUM",
        )
