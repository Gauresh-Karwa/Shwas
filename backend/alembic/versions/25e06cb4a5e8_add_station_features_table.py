from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
revision: str = '25e06cb4a5e8'
down_revision: Union[str, None] = 'f1d915638a76'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table('station_features', sa.Column('station_id', sa.String(), nullable=False), sa.Column('distance_to_water_km', sa.Float(), nullable=True), sa.Column('distance_to_green_km', sa.Float(), nullable=True), sa.Column('computed_at', sa.DateTime(), nullable=True), sa.ForeignKeyConstraint(['station_id'], ['stations.station_id']), sa.PrimaryKeyConstraint('station_id'))
    op.alter_column('raw_readings', 'pollutant_id', existing_type=sa.VARCHAR(), nullable=False)

def downgrade() -> None:
    op.alter_column('raw_readings', 'pollutant_id', existing_type=sa.VARCHAR(), nullable=True)
    op.drop_table('station_features')
