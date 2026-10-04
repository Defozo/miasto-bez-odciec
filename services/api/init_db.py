"""Idempotent bootstrap. Never deletes or replaces operational data."""
import argparse
import os
from sqlalchemy import select
from .db import Base, Entity, SessionLocal, State, User, engine
from .security import hasher
from .store import add_entity

def initialize(seed=True):
    Base.metadata.create_all(engine)
    with SessionLocal.begin() as db:
        if not db.get(State, "schema"):
            db.add(State(key="schema", value={"version": "0001"}))
        for role in ("operator", "verifier", "admin"):
            password = os.getenv(f"SMART_CITY_{role.upper()}_PASSWORD")
            existing = db.scalar(select(User).where(User.username == role))
            if password and not existing:
                if len(password) < 12:
                    raise RuntimeError(f"SMART_CITY_{role.upper()}_PASSWORD must have at least 12 characters")
                db.add(User(id=role, username=role, role=role, password_hash=hasher.hash(password)))
        if seed and not db.get(State, "layer:fixture"):
            from domain.graph import fixture_graph
            graph = fixture_graph()
            entity = add_entity(db, "graph", "fixture", {"graph": graph, "status": "published", "quality": {"synthetic": True}}, "graph-fixture-v1")
            db.add(State(key="layer:fixture", value={"graph_id": entity.id, "data_version": 1}))
            add_entity(db, "source", "fixture", {"title": "Kontrolowany przykład dwóch zamknięć", "publisher": "Miasto bez odcięć", "url": None, "published_at": None, "observed_at": None, "license": "CC0-1.0 (dane syntetyczne)", "raw_text": "Graf kontrolny opisany w rozdziale 4 aktualnego planu. Nie opisuje rzeczywistej sytuacji na ulicy.", "status": "fixture"}, "source-fixture")
            for item in graph.get("evidence", []):
                add_entity(db, "evidence", "fixture", {**item, "source_id": "source-fixture", "author": "fixture", "method": "controlled_fixture"}, item["id"])

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", action="store_true")
    args = parser.parse_args()
    initialize(seed=args.seed)
    print("Database initialized; secrets were not logged.")
