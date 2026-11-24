from alembic import op
import sqlalchemy as sa

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'task_list_id' not in {column['name'] for column in inspector.get_columns('google_links')}:
        op.add_column('google_links', sa.Column('task_list_id', sa.String(1024), nullable=False, server_default='@default'))
    constraints = inspector.get_unique_constraints('google_links')
    for constraint in constraints:
        if constraint['column_names'] == ['owner_id', 'subject', 'kind', 'remote_id']:
            op.drop_constraint(constraint['name'], 'google_links', type_='unique')
    if not any(constraint['name'] == 'uq_google_links_remote_list' for constraint in constraints):
        op.create_unique_constraint('uq_google_links_remote_list', 'google_links',
                                    ['owner_id', 'subject', 'kind', 'task_list_id', 'remote_id'])


def downgrade():
    raise RuntimeError('Restore the pre-migration backup before removing multi-list task links.')
