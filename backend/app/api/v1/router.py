"""Aggregate all v1 API routes."""
from fastapi import APIRouter
from app.api.v1 import market
from app.api.v1 import yangjibao
from app.api.v1 import agent
from app.api.v1 import backtest
from app.api.v1 import feishu
from app.api.v1 import trading_room
from app.api.v1 import conversation

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(market.router)
api_router.include_router(yangjibao.router)
api_router.include_router(agent.router)
api_router.include_router(backtest.router)
api_router.include_router(feishu.router)
api_router.include_router(trading_room.router)
api_router.include_router(conversation.router)
