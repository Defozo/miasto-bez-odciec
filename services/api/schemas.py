"""Validated, documented JSON contracts that retain the API's plain dictionaries.

Optional extension fields remain available for versioned graph and planning data.
Required identifiers, mutation versions, value types and state enums are explicit.
Domain validation still checks topology, temporal meaning and state transitions.
"""
from typing import Annotated, Any, Literal
from typing_extensions import Required, TypedDict
from pydantic import ConfigDict, Field

Layer = Literal['fixture', 'observed', 'planned', 'scenario']
Role = Literal['operator', 'verifier', 'admin']
Feature = Literal['open', 'steps', 'width_m', 'width_cm', 'kerb_cm', 'slope_pct', 'surface', 'lit', 'entrance_open', 'elevator_operational']
InvalidatedFeature = Literal['open', 'steps', 'width_m', 'kerb_cm', 'slope_pct', 'surface', 'lit', 'entrance_open', 'elevator_operational']
Identifier = Annotated[str, Field(min_length=1, max_length=200)]
Version = Annotated[int, Field(ge=1, description='Version last read by the caller. Stale versions return HTTP 409.')]
Timestamp = Annotated[str, Field(description='ISO 8601 timestamp with an explicit UTC offset.', json_schema_extra={'format': 'date-time'})]
ShortText = Annotated[str, Field(min_length=3, max_length=300)]
Reason = Annotated[str, Field(min_length=3, max_length=4000)]
Measurement = bool | float | str


class LayerPayload(TypedDict, total=False):
    layer: Layer


class VersionPayload(LayerPayload, total=False):
    expected_version: Required[Version]


class DemoLogin(TypedDict, total=False):
    role: Role


class Horizon(TypedDict):
    start: Timestamp
    end: Timestamp


class MobilityProfile(TypedDict, total=False):
    id: Identifier
    name: str
    allow_steps: bool
    min_width_m: Annotated[float, Field(ge=0)]
    max_kerb_cm: Annotated[float, Field(ge=0)]
    max_uphill_pct: Annotated[float, Field(ge=0)]
    max_downhill_pct: Annotated[float, Field(ge=0)]
    allowed_surfaces: list[str]
    max_distance_m: Annotated[float, Field(gt=0)]
    max_duration_s: Annotated[float, Field(gt=0)]
    require_lit: bool


class Destination(TypedDict, total=False):
    id: Identifier
    category: Identifier
    place_id: Identifier
    entrance_id: Identifier


class Restriction(TypedDict, total=False):
    id: Identifier
    asset_id: Identifier
    kind: Literal['closure', 'warning']
    status: str
    start: Timestamp
    end: Timestamp
    verified_open_at: Timestamp | None
    invalidated_features: list[InvalidatedFeature] | None
    source_id: Identifier
    reason: str


class Action(TypedDict, total=False):
    id: Identifier
    asset_id: Identifier
    feature: Feature
    value: Measurement
    unit: str | None
    features: list[dict[str, Any]]
    cost: Annotated[float, Field(ge=0)] | None
    valid_from: Timestamp
    valid_until: Timestamp


class ScheduleVariant(TypedDict, total=False):
    id: Required[Identifier]
    name: str
    restrictions: list[Restriction]
    actions: list[Action]
    cost: Annotated[float, Field(ge=0)] | None
    assumptions: list[str]


class AnalysisRequest(LayerPayload, total=False):
    origins: list[str | dict[str, Any]]
    profiles: list[str | MobilityProfile]
    destinations: list[str | Destination]
    horizon: Horizon
    restrictions: list[Restriction]
    actions: list[Action]
    variants: list[ScheduleVariant]
    catalog: Annotated[list[dict[str, Any]], Field(description='Finite groups of alternatives, evaluated jointly with resources, dependencies and exclusions.')]
    resources: dict[str, Any]
    budget: Annotated[float, Field(ge=0)] | None
    critical: dict[str, Any] | list[Any]
    weights: dict[str, Annotated[float, Field(ge=0)]]
    time_limit_s: Annotated[float, Field(gt=0)]
    max_labels: Annotated[int, Field(gt=0)]
    baseline_kind: str
    search_method: str
    solver: Literal['auto', 'cp_sat', 'exhaustive']
    critical_relation_ids: list[str]
    max_variants: Annotated[int, Field(gt=0)]
    max_paths_per_relation: Annotated[int, Field(gt=0)]
    max_local_assignments: Annotated[int, Field(gt=0)]


class ReportCreate(LayerPayload, total=False):
    description: Required[Annotated[str, Field(min_length=5, max_length=4000)]]
    asset_id: Required[Identifier]
    kind: Literal['barrier', 'opening', 'measurement', 'other']
    feature: Feature | None


class ReportReview(VersionPayload, total=False):
    action: Required[Literal['locate_warning', 'confirm', 'reject', 'resolve', 'needs_recheck']]
    reason: Required[Reason]
    asset_id: Identifier
    evidence_id: Identifier
    start: Timestamp
    end: Timestamp


class TaskCreate(LayerPayload, total=False):
    title: Required[ShortText]
    asset_id: Required[Identifier]
    method: Required[Annotated[str, Field(min_length=3, max_length=2000)]]
    property: Feature
    feature: Feature
    unit: str | None
    report_id: Identifier | None
    positive_effect: str
    negative_effect: str
    assignee: str
    due_at: Timestamp | None


class ObservationCreate(VersionPayload, total=False):
    value: Required[Measurement]
    method: Required[Annotated[str, Field(min_length=3, max_length=2000)]]
    observed_at: Required[Timestamp]
    valid_until: Required[Timestamp]
    unit: str | None
    notes: str
    photo_id: Annotated[str, Field(min_length=1, max_length=80)] | None
    work_minutes: Annotated[float, Field(ge=0)]


class EvidencePublish(VersionPayload, total=False):
    reason: Required[Reason]
    supersedes: list[Identifier]


class SourceCreate(LayerPayload, total=False):
    title: Required[ShortText]
    publisher: Required[Annotated[str, Field(min_length=2, max_length=300)]]
    url: str | None
    raw_text: str
    published_at: str | None
    observed_at: str | None
    license: str
    fetch: bool
    provider: Literal['direct', 'firecrawl']
    refresh_enabled: bool
    refresh_interval_s: Annotated[int, Field(gt=0)]


class SourceExtract(LayerPayload, total=False):
    use_ai: bool


class RestrictionCreate(LayerPayload, total=False):
    asset_id: Required[Identifier]
    source_id: Required[Identifier]
    start: Required[Timestamp]
    end: Required[Timestamp]
    reason: Required[Reason]
    pedestrian_impact: bool | None
    geometry_reviewed: bool
    side: str | None
    level: str | float | None
    invalidated_features: Annotated[list[InvalidatedFeature] | None, Field(description='Features requiring fresh evidence after the work. Omitted/null conservatively invalidates all accessibility features.')]


class RestrictionOpen(VersionPayload, total=False):
    evidence_id: Required[Identifier]
    observed_at: Timestamp
    reason: str


class ImportCreate(LayerPayload, total=False):
    format: Required[Literal['osm', 'geojson', 'csv']]
    content: Required[str | dict[str, Any]]
    source_id: Identifier
    bindings: dict[str, Any]


class GraphStage(LayerPayload, total=False):
    graph: Required[dict[str, Any]]
    bindings: dict[str, Any]


class GraphEdit(VersionPayload, total=False):
    graph: dict[str, Any]
    graph_patch: dict[str, Any]
    bindings: dict[str, Any]


class GraphValidate(VersionPayload, total=False):
    bindings: dict[str, Any] | None


class ScenarioCreate(LayerPayload, total=False):
    name: Required[ShortText]
    request: AnalysisRequest
    assumptions: list[str]


class ScenarioEvaluate(VersionPayload, total=False):
    request: AnalysisRequest


class ScenarioDecision(VersionPayload, total=False):
    status: Required[Literal['approved_plan', 'in_progress', 'performed', 'effect_reviewed']]
    variant_id: Identifier | None
    owner: str
    executor: str
    conditions: str
    due_at: Timestamp | None
    evidence_ids: list[Identifier]
    notes: str


class RecordReply(TypedDict, total=False):
    id: Required[str]
    version: Required[int]
    layer: Layer
    status: str
    created_at: str
    updated_at: str


class ReportReply(RecordReply, total=False):
    description: str
    asset_id: str
    kind: str
    physical_status: str
    history: list[dict[str, Any]]
    photo_ids: list[str]
    token: Annotated[str, Field(description='Private case token, returned only on creation or its idempotent replay.')]


class ObservationReply(TypedDict):
    task: RecordReply
    evidence: RecordReply


class JobReply(TypedDict, total=False):
    job_id: Required[str]
    status: Required[Literal['queued', 'running', 'completed', 'failed', 'stale']]
    id: str
    scenario_id: str
    version: int
    progress: float
    attempts: int
    result: dict[str, Any] | None
    error: str | None
    created_at: str
    finished_at: str | None


class RouteReply(TypedDict, total=False):
    status: Required[str]
    layer: Required[Layer]
    data_version: Required[int]
    graph_version: Required[str]
    complete: bool
    conservative_window: bool
    distance_m: float
    duration_s: float
    edge_ids: list[str]
    reasons: list[dict[str, Any]]
    evidence: list[dict[str, Any]]


class AnalysisReply(TypedDict, total=False):
    baseline: dict[str, Any]
    variants: list[dict[str, Any]]
    horizon: Horizon
    recommended_id: str | None
    recommendation_status: str
    nondominated_ids: list[str]
    ranking_criteria: list[str]
    work_impacts: list[dict[str, Any]]
    search: dict[str, Any]


# Pydantic validates TypedDict without replacing the plain dictionaries consumed
# by idempotency hashing and domain code. Unknown versioned graph extensions are
# preserved rather than silently discarded.
for _payload in list(globals().values()):
    if isinstance(_payload, type) and hasattr(_payload, '__required_keys__'):
        _payload.__pydantic_config__ = ConfigDict(extra='allow', allow_inf_nan=False)
