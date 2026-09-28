"""Users and current personal profiles; no document or session tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_profiles"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("users", sa.Column("telegram_id", sa.BigInteger(), primary_key=True),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("extraction_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("original_instruction", sa.Text(), nullable=False),
        sa.Column("fields", postgresql.JSONB(), nullable=False),
        sa.Column("guidance", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("version >= 1", name="ck_profile_version"))
    op.create_index("ix_extraction_profiles_owner_id", "extraction_profiles", ["owner_id"])


def downgrade():
    op.drop_index("ix_extraction_profiles_owner_id", table_name="extraction_profiles")
    op.drop_table("extraction_profiles")
    op.drop_table("users")
