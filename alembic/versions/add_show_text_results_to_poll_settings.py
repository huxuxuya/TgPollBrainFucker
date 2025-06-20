from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_show_text_results'
down_revision = '3e7b4f9c2a9d'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('poll_settings') as batch:
        batch.add_column(sa.Column('show_text_results', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    with op.batch_alter_table('poll_settings') as batch:
        batch.drop_column('show_text_results')
