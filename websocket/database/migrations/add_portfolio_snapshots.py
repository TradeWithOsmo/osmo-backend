"""Add portfolio_snapshots table

Revision ID: add_portfolio_snapshots
Revises: add_agent_leaderboard
Create Date: 2026-01-29

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import Index


# revision identifiers
revision = 'add_portfolio_snapshots'
down_revision = 'add_agent_leaderboard'
branch_labels = None
depends_on = None


def upgrade():
    # Create portfolio_snapshots table
    op.create_table(
        'portfolio_snapshots',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_address', sa.String(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('portfolio_value', sa.Float(), nullable=False),
        sa.Column('cash_balance', sa.Float(), default=0),
        sa.Column('position_value', sa.Float(), default=0),
        sa.Column('unrealized_pnl', sa.Float(), default=0),
        sa.Column('realized_pnl', sa.Float(), default=0),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes
    op.create_index('idx_portfolio_user_time', 'portfolio_snapshots', ['user_address', 'timestamp'])
    op.create_index(op.f('ix_portfolio_snapshots_user_address'), 'portfolio_snapshots', ['user_address'])
    op.create_index(op.f('ix_portfolio_snapshots_timestamp'), 'portfolio_snapshots', ['timestamp'])


def downgrade():
    op.drop_index(op.f('ix_portfolio_snapshots_timestamp'), table_name='portfolio_snapshots')
    op.drop_index(op.f('ix_portfolio_snapshots_user_address'), table_name='portfolio_snapshots')
    op.drop_index('idx_portfolio_user_time', table_name='portfolio_snapshots')
    op.drop_table('portfolio_snapshots')
