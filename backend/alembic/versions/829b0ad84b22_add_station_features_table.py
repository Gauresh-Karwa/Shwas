from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
revision: str = '829b0ad84b22'
down_revision: Union[str, None] = '25e06cb4a5e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass
