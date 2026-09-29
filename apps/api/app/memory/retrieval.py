from typing import Any

from app.memory.schemas import MemoryRecord


def normalize_recall_response(response: Any) -> list[MemoryRecord]:
    records: list[MemoryRecord] = []
    for item in getattr(response, "results", []) or []:
        metadata = getattr(item, "metadata", None) or {}
        scores = getattr(item, "scores", None)
        ranking = (
            scores.model_dump(exclude_none=True)
            if hasattr(scores, "model_dump")
            else {
                key: value
                for key in ("final", "reranker", "semantic", "keyword")
                if (value := getattr(scores, key, None)) is not None
            }
        )
        records.append(
            MemoryRecord(
                text=getattr(item, "text", ""),
                source_document=(
                    getattr(item, "document_id", None)
                    or metadata.get("incident_id")
                    or metadata.get("document_id")
                ),
                metadata=metadata,
                relevance=ranking.get("final"),
                ranking=ranking,
            )
        )
    return records
