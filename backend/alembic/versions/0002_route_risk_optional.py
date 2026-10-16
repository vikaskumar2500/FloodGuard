"""Allow routes to exist before the Phase 6 risk engine."""

import sqlalchemy as sa

from alembic import op

revision = "0002_route_risk_optional"
down_revision = "0001_database_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("routes", "risk_score", existing_type=sa.Float(), nullable=True)
    op.alter_column("route_segments", "risk_score", existing_type=sa.Float(), nullable=True)


def downgrade() -> None:
    op.alter_column("route_segments", "risk_score", existing_type=sa.Float(), nullable=False)
    op.alter_column("routes", "risk_score", existing_type=sa.Float(), nullable=False)
