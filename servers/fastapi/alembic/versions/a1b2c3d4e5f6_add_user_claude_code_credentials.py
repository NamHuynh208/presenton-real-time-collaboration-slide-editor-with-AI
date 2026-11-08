"""add per-user Claude Code credentials"""

from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "d0a2b4c6e8f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "claude_code_credentials" in inspector.get_table_names():
        return
    op.create_table(
        "claude_code_credentials",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", name="uq_claude_code_user"),
    )
    op.create_index("ix_claude_code_credentials_user_id", "claude_code_credentials", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_claude_code_credentials_user_id", table_name="claude_code_credentials")
    op.drop_table("claude_code_credentials")
