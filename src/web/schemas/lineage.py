"""Data lineage models for tracking analysis provenance.

Provides immutable data snapshots, lineage nodes (operations), and
lineage graphs for full traceability of how analysis conclusions
were derived from source data.

Part of v14.0 Institutional Contracts layer.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field


class DataSnapshot(BaseModel):
    """An immutable point-in-time snapshot of data used in an analysis.

    Once created, the content_hash ensures integrity: any modification
    to the payload will produce a different hash.

    Attributes:
        id: Unique snapshot identifier.
        source: Data source name (e.g. "akshare", "sina_realtime", "redis").
        source_type: Category of the data source.
        symbol: Stock symbol if applicable.
        timestamp: ISO timestamp when the snapshot was captured.
        content_hash: SHA-256 hash of the serialized payload.
        payload_summary: Truncated human-readable summary of the data.
        payload_size_bytes: Size of the full payload in bytes.
        ttl_seconds: Cache TTL that was active when data was fetched.
    """

    id: str
    source: str
    source_type: Literal[
        "market_data", "technical", "news", "llm", "user_input", "computed"
    ] = "market_data"
    symbol: str = ""
    timestamp: str = ""
    content_hash: str = ""
    payload_summary: str = ""
    payload_size_bytes: int = 0
    ttl_seconds: int | None = None

    @staticmethod
    def compute_hash(payload: Any) -> str:
        """Compute SHA-256 hash of a JSON-serializable payload."""
        serialized = json.dumps(
            payload, sort_keys=True, default=str, ensure_ascii=False
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def summarize_payload(payload: Any, max_length: int = 200) -> str:
        """Create a truncated summary of a payload for display."""
        text = json.dumps(payload, default=str, ensure_ascii=False)
        if len(text) <= max_length:
            return text
        return text[:max_length] + "..."


class LineageNode(BaseModel):
    """A single operation in a lineage graph.

    Represents a transformation step: tool call, LLM inference,
    validation pass, or aggregation.

    Attributes:
        id: Unique node identifier.
        operation: Name of the operation (e.g. "get_realtime_quote", "llm_inference").
        operation_type: Category of the operation.
        input_snapshot_ids: IDs of DataSnapshots consumed by this operation.
        output_snapshot_id: ID of the DataSnapshot produced.
        agent_name: Name of the agent that performed this operation.
        thread_id: Chat thread ID if applicable.
        timestamp: ISO timestamp of the operation.
        duration_ms: Time taken in milliseconds.
        metadata: Additional operation-specific metadata.
    """

    id: str
    operation: str
    operation_type: Literal[
        "tool_call", "llm_inference", "validation", "aggregation", "user_action"
    ] = "tool_call"
    input_snapshot_ids: list[str] = Field(default_factory=list)
    output_snapshot_id: str = ""
    agent_name: str = "master"
    thread_id: str = ""
    timestamp: str = ""
    duration_ms: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class LineageGraph(BaseModel):
    """A directed acyclic graph of lineage nodes for one analysis session.

    Attributes:
        thread_id: The chat thread this lineage belongs to.
        message_id: The specific message that triggered this analysis.
        snapshots: All data snapshots referenced in this graph.
        nodes: All operation nodes in topological order.
        root_node_id: ID of the first node (user query).
        leaf_node_id: ID of the final node (agent reply).
    """

    thread_id: str = ""
    message_id: str = ""
    snapshots: list[DataSnapshot] = Field(default_factory=list)
    nodes: list[LineageNode] = Field(default_factory=list)
    root_node_id: str = ""
    leaf_node_id: str = ""
