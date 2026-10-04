from copy import deepcopy
from importlib import import_module

from sqlalchemy import create_engine, select
from domain.graph import build_fixture
from services.api.db import Base, Entity, State


def test_fixture_scope_migration_preserves_observed_and_frozen_scenarios(monkeypatch):
    migration = import_module("migrations.versions.0002_fixture_feature_scope")
    graph = build_fixture()
    for item in graph["works"]+graph["restrictions"]:
        item.pop("invalidated_features")
    frozen = deepcopy(graph)
    observed = {**deepcopy(graph), "layer": "observed"}
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(Entity.__table__.insert(), [
            {"id": "graph-fixture-v1", "kind": "graph", "layer": "fixture", "data": {"graph": graph}},
            {"id": "graph-observed", "kind": "graph", "layer": "observed", "data": {"graph": observed}},
            {"id": "frozen-scenario", "kind": "scenario", "layer": "fixture", "data": {"graph_snapshot": frozen}},
            {"id": "X", "kind": "restriction", "layer": "fixture", "data": graph["restrictions"][0]},
        ])
        connection.execute(State.__table__.insert().values(key="layer:fixture", value={"graph_id": "graph-fixture-v1", "data_version": 9}))
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        migration.upgrade()
        values = {row.id: row.data for row in connection.execute(select(Entity.__table__))}
        assert all(item["invalidated_features"] == ["open"] for item in values["graph-fixture-v1"]["graph"]["works"]+values["graph-fixture-v1"]["graph"]["restrictions"])
        assert values["X"]["invalidated_features"] == ["open"]
        assert values["frozen-scenario"]["graph_snapshot"] == frozen
        assert values["graph-observed"]["graph"] == observed
        assert connection.execute(select(State.__table__.c.value).where(State.__table__.c.key == "layer:fixture")).scalar_one()["data_version"] == 10
        migration.upgrade()
        assert connection.execute(select(State.__table__.c.value).where(State.__table__.c.key == "layer:fixture")).scalar_one()["data_version"] == 10
    engine.dispose()
