"""Application accounts and farmer pickup requests."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite

revision = "b4_auth_product"
down_revision = "52408f31620a"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("uq_collection_job_active_field", "collection_jobs", ["field_id"], unique=True,
        sqlite_where=sa.text("state != 'CANCELLED'"),
        postgresql_where=sa.text("state != 'CANCELLED'"))
    op.create_table("user_accounts",
        sa.Column("user_id", sa.String(100), primary_key=True),
        sa.Column("username", sa.String(100), unique=True, nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("field_id", sa.String(100), sa.ForeignKey("fields.field_id")),
        sa.Column("baler_id", sa.String(100), sa.ForeignKey("balers.baler_id")),
        sa.Column("buyer_id", sa.String(100), sa.ForeignKey("buyers.buyer_id")),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False))
    op.create_table("pickup_requests",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("field_id", sa.String(100), sa.ForeignKey("fields.field_id"), unique=True, nullable=False),
        sa.Column("user_id", sa.String(100), sa.ForeignKey("user_accounts.user_id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provenance", sa.String(20), nullable=False))


def downgrade():
    op.drop_table("pickup_requests")
    op.drop_table("user_accounts")
    op.drop_index("uq_collection_job_active_field", table_name="collection_jobs")
