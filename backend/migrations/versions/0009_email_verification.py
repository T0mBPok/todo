from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('email_verified_at', sa.DateTime(timezone=True)))
    op.create_table(
        'email_challenges',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('email', sa.String(254), nullable=False),
        sa.Column('password_hash', sa.Text()),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE')),
        sa.Column('code_hash', sa.String(64), nullable=False),
        sa.Column('expires', sa.DateTime(timezone=True), nullable=False),
        sa.Column('code_expires', sa.DateTime(timezone=True), nullable=False),
        sa.Column('resend_after', sa.DateTime(timezone=True), nullable=False),
        sa.Column('attempts_left', sa.Integer(), nullable=False),
        sa.CheckConstraint('(user_id IS NULL) <> (password_hash IS NULL)', name='email_challenge_purpose'),
    )
    op.create_index('ix_email_challenges_expires', 'email_challenges', ['expires'])
    op.create_index('ix_email_challenges_user_id', 'email_challenges', ['user_id'])


def downgrade():
    op.drop_table('email_challenges')
    op.drop_column('users', 'email_verified_at')
