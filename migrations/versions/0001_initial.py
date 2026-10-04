"""Initial transactional store and PostGIS spatial staging index."""
from alembic import op
from services.api.db import Base
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    Base.metadata.create_all(bind)
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        op.execute("CREATE TABLE IF NOT EXISTS graph_geometries (graph_id varchar(80) NOT NULL, edge_id varchar(100) NOT NULL, asset_id varchar(100), geom geometry(LineString,4326) NOT NULL, PRIMARY KEY(graph_id,edge_id))")
        op.execute("CREATE INDEX IF NOT EXISTS ix_graph_geometries_geom ON graph_geometries USING GIST(geom)")

def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TABLE IF EXISTS graph_geometries")
    Base.metadata.drop_all(op.get_bind())
