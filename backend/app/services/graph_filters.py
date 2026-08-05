from dataclasses import dataclass
from typing import Literal

from app.services.graph_config import GRAPH_CONFIG


@dataclass(frozen=True)
class GraphFilters:
    max_nodes: int = GRAPH_CONFIG.default_node_limit
    max_edges: int = GRAPH_CONFIG.default_edge_limit
    min_depth: int | None = None
    max_depth: int | None = None
    host: str | None = None
    path_prefix: str | None = None
    status: Literal["any", "2xx", "3xx", "4xx", "5xx", "none"] = "any"
    fetch_state: str | None = None
    error_state: Literal["any", "with_errors", "without_errors"] = "any"
    min_inbound: int | None = None
    min_outbound: int | None = None
    include_self_links: bool = True
    include_unfetched: bool = False
    focus_snapshot_id: int | None = None
    focus_hops: int = GRAPH_CONFIG.default_focus_hops
