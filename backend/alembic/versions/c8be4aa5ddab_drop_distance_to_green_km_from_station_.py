from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
revision: str = 'c8be4aa5ddab'
down_revision: Union[str, None] = '829b0ad84b22'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.drop_column('station_features', 'distance_to_green_km')

def downgrade() -> None:
    op.add_column('station_features', sa.Column('distance_to_green_km', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True))
