"""merge audit_logs heads

Revision ID: 8f422dbf621f
Revises: e5b0841d36d8, 20260209173357
Create Date: 2026-02-09 21:11:23.274965

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f422dbf621f'
down_revision: Union[str, None] = ('e5b0841d36d8', '20260209173357')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
