from dataclasses import dataclass

GRAPH_STATUS_FILTERS = ("any", "2xx", "3xx", "4xx", "5xx", "none")
GRAPH_ERROR_FILTERS = ("any", "with_errors", "without_errors")
GRAPH_NODE_SIZE_MODES = (
    "uniform",
    "inbound_sources",
    "inbound_occurrences",
    "outbound_targets",
    "outbound_occurrences",
    "response_time",
    "depth_inverse",
)
GRAPH_NODE_CATEGORY_MODES = ("status", "fetch_state", "depth", "host", "path", "error", "seed")


@dataclass(frozen=True)
class GraphConfiguration:
    default_node_limit: int = 100
    maximum_node_limit: int = 3000
    default_edge_limit: int = 250
    maximum_edge_limit: int = 10000
    default_focus_hops: int = 1
    maximum_focus_hops: int = 3
    sample_anchor_limit: int = 5
    occurrence_page_default: int = 50
    occurrence_page_maximum: int = 200
    response_warning_node_threshold: int = 1000
    response_warning_edge_threshold: int = 3000

    def validate(self) -> None:
        pairs = [
            ("default_node_limit", self.default_node_limit),
            ("maximum_node_limit", self.maximum_node_limit),
            ("default_edge_limit", self.default_edge_limit),
            ("maximum_edge_limit", self.maximum_edge_limit),
            ("default_focus_hops", self.default_focus_hops),
            ("maximum_focus_hops", self.maximum_focus_hops),
            ("sample_anchor_limit", self.sample_anchor_limit),
            ("occurrence_page_default", self.occurrence_page_default),
            ("occurrence_page_maximum", self.occurrence_page_maximum),
        ]
        for name, value in pairs:
            if value < 0:
                raise ValueError(f"{name} cannot be negative.")
        if self.default_node_limit < 1:
            raise ValueError("default_node_limit must be at least 1.")
        if self.maximum_node_limit < self.default_node_limit:
            raise ValueError("maximum_node_limit cannot be below default_node_limit.")
        if self.maximum_edge_limit < self.default_edge_limit:
            raise ValueError("maximum_edge_limit cannot be below default_edge_limit.")
        if self.maximum_focus_hops < self.default_focus_hops:
            raise ValueError("maximum_focus_hops cannot be below default_focus_hops.")
        if self.occurrence_page_maximum < self.occurrence_page_default:
            raise ValueError("occurrence_page_maximum cannot be below occurrence_page_default.")


GRAPH_CONFIG = GraphConfiguration()
GRAPH_CONFIG.validate()
