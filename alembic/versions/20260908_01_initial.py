"""initial MediDrone schema"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision, down_revision, branch_labels, depends_on = "20260908_01", None, None, None
status_enum = sa.Enum("RECEIVED","DRONE_ASSIGNED","MISSION_GENERATED","DISPATCHED","EN_ROUTE","APPROACHING","ARRIVED","AED_DELIVERED","COMPLETED","FAILED", name="emergency_status")
def upgrade():
    status_enum.create(op.get_bind(), checkfirst=True)
    op.create_table("drones", sa.Column("id",sa.String(128),primary_key=True), sa.Column("callsign",sa.String(128),nullable=False), sa.Column("last_lat",sa.Float(),nullable=False), sa.Column("last_lng",sa.Float(),nullable=False), sa.Column("status",sa.String(64),nullable=False), sa.Column("battery_pct",sa.Float()))
    op.create_table("emergencies", sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True), sa.Column("lat",sa.Float(),nullable=False), sa.Column("lng",sa.Float(),nullable=False), sa.Column("accuracy",sa.Float(),nullable=False), sa.Column("timestamp",sa.DateTime(timezone=True),nullable=False), sa.Column("name",sa.String(256),nullable=False), sa.Column("phone",sa.String(64),nullable=False), sa.Column("aadhaar_last4",sa.String(4),nullable=False), sa.Column("status",status_enum,nullable=False), sa.Column("drone_id",sa.String(128),sa.ForeignKey("drones.id")), sa.Column("mission_json",postgresql.JSONB()), sa.Column("telemetry",postgresql.JSONB()), sa.Column("rescue_report",postgresql.JSONB()), sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False), sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.func.now(),onupdate=sa.func.now(),nullable=False))
    op.bulk_insert(sa.table("drones",sa.column("id",sa.String),sa.column("callsign",sa.String),sa.column("last_lat",sa.Float),sa.column("last_lng",sa.Float),sa.column("status",sa.String),sa.column("battery_pct",sa.Float)),[{"id":"medidrone-001","callsign":"MEDIDRONE-01","last_lat":0.0,"last_lng":0.0,"status":"AVAILABLE","battery_pct":None}])
def downgrade():
    op.drop_table("emergencies"); op.drop_table("drones"); status_enum.drop(op.get_bind(),checkfirst=True)