"""Declare the original synthetic fixture's unchanged geometry explicitly.

Only the canonical active fixture and its X/Y restriction records are amended.
Historical scenario snapshots and every observed-layer record remain untouched.
"""
from copy import deepcopy
from datetime import datetime, timezone

from alembic import op
from sqlalchemy import select, update
from services.api.db import Entity, OutboxEvent, State

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    entities, states = Entity.__table__, State.__table__
    row = connection.execute(select(entities).where(entities.c.id == "graph-fixture-v1", entities.c.kind == "graph", entities.c.layer == "fixture")).mappings().first()
    changed = False
    now = datetime.now(timezone.utc).isoformat()
    if row:
        data = deepcopy(row["data"])
        graph = data.get("graph", {})
        if graph.get("version") == "fixture-v1" and graph.get("coverage", {}).get("status") == "synthetic":
            for item in graph.get("works", []) + graph.get("restrictions", []):
                if item.get("id") in {"X", "Y"} and item.get("asset_id") == "crossing-"+item["id"].lower() and "invalidated_features" not in item:
                    item["invalidated_features"] = ["open"]
                    changed = True
            if changed:
                connection.execute(update(entities).where(entities.c.id == row["id"]).values(data=data, version=row["version"]+1, updated_at=now))
            for restriction in connection.execute(select(entities).where(entities.c.id.in_(["X", "Y"]), entities.c.kind == "restriction", entities.c.layer == "fixture")).mappings():
                value = deepcopy(restriction["data"])
                if value.get("asset_id") == "crossing-"+restriction["id"].lower() and "invalidated_features" not in value:
                    value["invalidated_features"] = ["open"]
                    connection.execute(update(entities).where(entities.c.id == restriction["id"]).values(data=value, version=restriction["version"]+1, updated_at=now))
                    changed = True
    active = connection.execute(select(states).where(states.c.key == "layer:fixture")).mappings().first()
    if changed and active and active["value"].get("graph_id") == "graph-fixture-v1":
        value = {**active["value"], "data_version": active["value"]["data_version"]+1, "updated_at": now}
        connection.execute(update(states).where(states.c.key == "layer:fixture").values(value=value))
        connection.execute(OutboxEvent.__table__.insert().values(layer="fixture", event="fixture_invalidation_scope_migrated", version=value["data_version"], data={"migration": revision}))
    schema = connection.execute(select(states.c.key).where(states.c.key == "schema")).first()
    if schema:
        connection.execute(update(states).where(states.c.key == "schema").values(value={"version": revision}))
    else:
        connection.execute(states.insert().values(key="schema", value={"version": revision}))


def downgrade():
    # The explicit synthetic assumption is additive data. Older application
    # versions ignore it; reverting a release must not erase recorded metadata.
    states = State.__table__
    op.get_bind().execute(update(states).where(states.c.key == "schema").values(value={"version": down_revision}))
