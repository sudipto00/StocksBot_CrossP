"""enforce unique external broker order id

Revision ID: c9f7a1a2d4b1
Revises: 3d43b1b27967
Create Date: 2026-02-23 18:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c9f7a1a2d4b1"
down_revision: Union[str, None] = "3d43b1b27967"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    duplicate_rows = bind.execute(
        sa.text(
            """
            SELECT external_id, COUNT(*) AS cnt
            FROM orders
            WHERE external_id IS NOT NULL
            GROUP BY external_id
            HAVING COUNT(*) > 1
            LIMIT 5
            """
        )
    ).fetchall()
    if duplicate_rows:
        details = ", ".join(f"{row[0]}({row[1]})" for row in duplicate_rows)
        raise RuntimeError(
            "Cannot enforce unique orders.external_id because duplicates exist: "
            f"{details}"
        )

    op.drop_index(op.f("ix_orders_external_id"), table_name="orders")
    op.create_index(op.f("ix_orders_external_id"), "orders", ["external_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_orders_external_id"), table_name="orders")
    op.create_index(op.f("ix_orders_external_id"), "orders", ["external_id"], unique=False)
