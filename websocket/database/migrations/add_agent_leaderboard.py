"""
Alembic migration: Add agent tracking and leaderboard tables

Run with: alembic upgrade head
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'add_agent_leaderboard'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Add agent columns to orders table
    op.add_column('orders', sa.Column('is_agent_trade', sa.Boolean(), server_default='false', nullable=True))
    op.add_column('orders', sa.Column('agent_model', sa.String(), nullable=True))
    op.add_column('orders', sa.Column('agent_session_id', sa.String(), nullable=True))
    
    # Add index for agent queries
    op.create_index('idx_agent_model', 'orders', ['agent_model'], unique=False)
    
    # Create leaderboard_snapshots table
    op.create_table(
        'leaderboard_snapshots',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.Column('timeframe', sa.String(), nullable=False),
        sa.Column('user_address', sa.String(), nullable=False),
        sa.Column('account_value', sa.Float(), server_default='0', nullable=True),
        sa.Column('pnl', sa.Float(), server_default='0', nullable=True),
        sa.Column('roi', sa.Float(), server_default='0', nullable=True),
        sa.Column('volume', sa.Float(), server_default='0', nullable=True),
        sa.Column('agent_model', sa.String(), nullable=True),
        sa.Column('rank', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_snapshot_user', 'leaderboard_snapshots', ['snapshot_date', 'timeframe', 'user_address'], unique=True)
    op.create_index('idx_snapshot_rank', 'leaderboard_snapshots', ['snapshot_date', 'timeframe', 'rank'], unique=False)
    
    # Create model_leaderboard_snapshots table
    op.create_table(
        'model_leaderboard_snapshots',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.Column('timeframe', sa.String(), nullable=False),
        sa.Column('agent_model', sa.String(), nullable=False),
        sa.Column('total_users', sa.Integer(), server_default='0', nullable=True),
        sa.Column('account_value', sa.Float(), server_default='0', nullable=True),
        sa.Column('pnl', sa.Float(), server_default='0', nullable=True),
        sa.Column('roi', sa.Float(), server_default='0', nullable=True),
        sa.Column('volume', sa.Float(), server_default='0', nullable=True),
        sa.Column('rank', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_model_snapshot', 'model_leaderboard_snapshots', ['snapshot_date', 'timeframe', 'agent_model'], unique=True)
    op.create_index('idx_model_rank', 'model_leaderboard_snapshots', ['snapshot_date', 'timeframe', 'rank'], unique=False)

def downgrade():
    # Drop model leaderboard table
    op.drop_index('idx_model_rank', table_name='model_leaderboard_snapshots')
    op.drop_index('idx_model_snapshot', table_name='model_leaderboard_snapshots')
    op.drop_table('model_leaderboard_snapshots')
    
    # Drop trader leaderboard table
    op.drop_index('idx_snapshot_rank', table_name='leaderboard_snapshots')
    op.drop_index('idx_snapshot_user', table_name='leaderboard_snapshots')
    op.drop_table('leaderboard_snapshots')
    
    # Drop agent columns and index
    op.drop_index('idx_agent_model', table_name='orders')
    op.drop_column('orders', 'agent_session_id')
    op.drop_column('orders', 'agent_model')
    op.drop_column('orders', 'is_agent_trade')
