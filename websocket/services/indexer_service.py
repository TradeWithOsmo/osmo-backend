
import asyncio
import json
import logging
from web3 import Web3
from config import settings
from .ledger_service import ledger_service
from database.connection import AsyncSessionLocal
from sqlalchemy import select

logger = logging.getLogger(__name__)

# Minimal ABIs for Events
TRADING_VAULT_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "user", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "newBalance", "type": "uint256"}
        ],
        "name": "CollateralDeposited",
        "type": "event"
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "user", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "remainingBalance", "type": "uint256"}
        ],
        "name": "CollateralWithdrawn",
        "type": "event"
    }
]

# Position Manager ABI
POSITION_MANAGER_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "bytes32", "name": "positionId", "type": "bytes32"},
            {"indexed": True, "internalType": "address", "name": "user", "type": "address"},
            {"indexed": False, "internalType": "string", "name": "symbol", "type": "string"},
            {"indexed": False, "internalType": "uint8", "name": "side", "type": "uint8"},
            {"indexed": False, "internalType": "uint256", "name": "size", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "entryPrice", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "leverage", "type": "uint256"}
        ],
        "name": "PositionOpened",
        "type": "event"
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "bytes32", "name": "positionId", "type": "bytes32"},
            {"indexed": True, "internalType": "address", "name": "user", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "exitPrice", "type": "uint256"},
            {"indexed": False, "internalType": "int256", "name": "pnl", "type": "int256"}
        ],
        "name": "PositionClosed",
        "type": "event"
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "bytes32", "name": "positionId", "type": "bytes32"},
            {"indexed": False, "internalType": "uint256", "name": "sizeDelta", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "marginDelta", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "newSize", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "newEntryPrice", "type": "uint256"}
        ],
        "name": "PositionIncreased",
        "type": "event"
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "bytes32", "name": "positionId", "type": "bytes32"},
            {"indexed": False, "internalType": "uint256", "name": "sizeDelta", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "marginDelta", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "newSize", "type": "uint256"},
            {"indexed": False, "internalType": "int256", "name": "realizedPnl", "type": "int256"}
        ],
        "name": "PositionDecreased",
        "type": "event"
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "bytes32", "name": "positionId", "type": "bytes32"},
            {"indexed": False, "internalType": "uint8", "name": "newSide", "type": "uint8"},
            {"indexed": False, "internalType": "uint256", "name": "newSize", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "newEntryPrice", "type": "uint256"}
        ],
        "name": "PositionFlipped",
        "type": "event"
    }
]

class IndexerService:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(settings.ARBITRUM_RPC_URL))
        self.is_running = False
        self.last_block = 0
        
    async def _get_block_number(self):
        return await asyncio.to_thread(lambda: self.w3.eth.block_number)

    async def _get_logs(self, event, from_block, to_block):
        return await asyncio.to_thread(lambda: event.get_logs(from_block=from_block, to_block=to_block))

    async def start(self):
        """Start the indexing loop"""
        if self.is_running:
            return
            
        logger.info("Starting On-Chain Indexer...")
        self.is_running = True
        
        # Initial block: Latest - 500 (faster catchup, usually enough for recent testing)
        try:
            latest = await self._get_block_number()
            # Catch up from 100 blocks ago
            self.last_block = latest - 100
        except Exception as e:
            logger.error(f"Failed to get block number: {e}")
            self.last_block = 0
            
        logger.info(f"Indexer starting from block {self.last_block}")
        
        while self.is_running:
            try:
                current_block = await self._get_block_number()
                
                if current_block > self.last_block:
                    # Process in chunks of 2000
                    target_block = min(current_block, self.last_block + 2000)
                    logger.debug(f"Indexer: Scanning blocks {self.last_block + 1} to {target_block} (Latest: {current_block})")
                    await self.process_block_range(self.last_block + 1, target_block)
                    self.last_block = target_block
                
                await asyncio.sleep(5) # Poll less frequently to be kind to RPC
                
            except Exception as e:
                logger.error(f"Indexer loop error: {e}")
                await asyncio.sleep(10)

    async def process_block_range(self, start_block, end_block):
        # 1. Check Vault Events
        if settings.TRADING_VAULT_ADDRESS:
            vault_addr = Web3.to_checksum_address(settings.TRADING_VAULT_ADDRESS)
            vault = self.w3.eth.contract(address=vault_addr, abi=TRADING_VAULT_ABI)
            
            try:
                logs = await self._get_logs(vault.events.CollateralDeposited, start_block, end_block)
                for log in logs:
                    args = log['args']
                    tx_hash = log['transactionHash'].hex()
                    amount_human = args['amount'] / 1e6 
                    logger.info(f"Indexer: Processing Deposit {amount_human} for {args['user']}")
                    await ledger_service.process_deposit(args['user'], amount_human, tx_hash)

                logs = await self._get_logs(vault.events.CollateralWithdrawn, start_block, end_block)
                for log in logs:
                    args = log['args']
                    tx_hash = log['transactionHash'].hex()
                    amount_human = args['amount'] / 1e6
                    logger.info(f"Indexer: Processing Withdrawal {amount_human} for {args['user']}")
                    await ledger_service.process_withdrawal(args['user'], amount_human, tx_hash)
            except Exception as e:
                logger.error(f"Error indexing Vault events: {e}")

        # 2. Check PositionManager Events
        if settings.POSITION_MANAGER_ADDRESS:
            pm_addr = Web3.to_checksum_address(settings.POSITION_MANAGER_ADDRESS)
            pm = self.w3.eth.contract(address=pm_addr, abi=POSITION_MANAGER_ABI)
            try:
                # --- PositionOpened ---
                logs = await self._get_logs(pm.events.PositionOpened, start_block, end_block)
                for log in logs:
                    args = log['args']
                    tx_hash = log['transactionHash'].hex()
                    side_str = 'Long' if args['side'] == 0 else 'Short'
                    price_human = args['entryPrice'] / 1e6
                    size_usd_human = args['size'] / 1e6
                    size_token = size_usd_human / price_human if price_human > 0 else 0
                    leverage = args['leverage']
                    margin_used = size_usd_human / leverage if leverage > 0 else 0
                    
                    logger.info(f"Indexer: PositionOpened detected: {args['symbol']} {side_str} for {args['user']}")
                    await ledger_service.process_trade_open(
                        user_address=args['user'],
                        symbol=args['symbol'],
                        side=side_str,
                        size_token=size_token,
                        entry_price=price_human,
                        leverage=leverage,
                        margin_used=margin_used,
                        order_id=tx_hash,
                        position_id=args['positionId'].hex(),
                        exchange='onchain'
                    )

                # --- PositionIncreased ---
                logs = await self._get_logs(pm.events.PositionIncreased, start_block, end_block)
                for log in logs:
                    args = log['args']
                    tx_hash = log['transactionHash'].hex()
                    logger.info(f"Indexer: PositionIncreased detected: {args['positionId'].hex()}")
                    # Here we need to find the user/symbol from DB since the event doesn't provide them
                    from database.models import Position
                    async with AsyncSessionLocal() as session:
                        res = await session.execute(select(Position).where(Position.position_id == args['positionId'].hex()))
                        pos = res.scalar_one_or_none()
                        if pos:
                            price_human = args['newEntryPrice'] / 1e6
                            size_delta_usd = args['sizeDelta'] / 1e6
                            size_delta_token = size_delta_usd / pos.entry_price if pos.entry_price > 0 else 0
                            margin_delta = args['marginDelta'] / 1e6
                            
                            await ledger_service.process_trade_open(
                                user_address=pos.user_address,
                                symbol=pos.symbol,
                                side=pos.side,
                                size_token=size_delta_token,
                                entry_price=price_human,
                                leverage=pos.leverage,
                                margin_used=margin_delta,
                                order_id=tx_hash,
                                position_id=args['positionId'].hex(),
                                exchange='onchain'
                            )

                # --- PositionFlipped ---
                logs = await self._get_logs(pm.events.PositionFlipped, start_block, end_block)
                for log in logs:
                    args = log['args']
                    tx_hash = log['transactionHash'].hex()
                    logger.info(f"Indexer: PositionFlipped detected: {args['positionId'].hex()}")
                    from database.models import Position
                    async with AsyncSessionLocal() as session:
                        res = await session.execute(select(Position).where(Position.position_id == args['positionId'].hex()))
                        pos = res.scalar_one_or_none()
                        if pos:
                            # 1. First close the old position locally
                            await ledger_service.process_position_close_event(
                                position_id_hex=args['positionId'].hex(),
                                user_address=pos.user_address,
                                price=args['newEntryPrice'] / 1e6,
                                pnl=0 # PnL already handled by Decreased event if emitted before, or custom logic
                            )
                            # 2. Then open the new one
                            side_str = 'Long' if args['newSide'] == 0 else 'Short'
                            price_human = args['newEntryPrice'] / 1e6
                            size_usd = args['newSize'] / 1e6
                            size_token = size_usd / price_human if price_human > 0 else 0
                            
                            await ledger_service.process_trade_open(
                                user_address=pos.user_address,
                                symbol=pos.symbol,
                                side=side_str,
                                size_token=size_token,
                                entry_price=price_human,
                                leverage=pos.leverage,
                                margin_used=size_usd / pos.leverage if pos.leverage > 0 else 0,
                                order_id=tx_hash,
                                position_id=args['positionId'].hex(),
                                exchange='onchain'
                            )

                # --- PositionClosed ---
                logs = await self._get_logs(pm.events.PositionClosed, start_block, end_block)
                for log in logs:
                    args = log['args']
                    logger.info(f"Indexer: PositionClosed detected: {args['positionId'].hex()}")
                    await ledger_service.process_position_close_event(
                        position_id_hex=args['positionId'].hex(),
                        user_address=args['user'],
                        price=args['exitPrice'] / 1e6,
                        pnl=args['pnl'] / 1e6
                    )

            except Exception as e:
                logger.error(f"Error indexing PositionManager events: {e}")

    async def stop(self):
        self.is_running = False

indexer_service = IndexerService()
