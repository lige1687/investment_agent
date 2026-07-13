"""Portfolio evaluation tasks — daily P&L push and Yangjibao sync."""
import logging
from app.tasks.scheduler import is_trading_day
from app.feishu.bot import feishu_bot

logger = logging.getLogger(__name__)


async def daily_pnl_push():
    """Push daily portfolio P&L summary to Feishu."""
    if not is_trading_day():
        return

    if not feishu_bot.configured:
        return

    try:
        from app.database import async_session
        from app.services.yangjibao_service import YangjibaoService

        async with async_session() as db:
            service = YangjibaoService(db)
            portfolio = await service.get_local_portfolio()

            if not portfolio.get("connected"):
                return

            total_value = portfolio.get("total_value", 0)
            total_pnl = portfolio.get("total_pnl", 0)
            total_pnl_pct = portfolio.get("total_pnl_pct", 0)
            positions = portfolio.get("positions", [])

            emoji = "🎉" if total_pnl > 0 else "😔"
            text = (
                f"💼 持仓日报\n\n"
                f"总市值：¥{total_value:,.2f}\n"
                f"持仓盈亏：{emoji} ¥{total_pnl:+,.2f}（{total_pnl_pct:+.2f}%）\n\n"
            )

            # Top and bottom performers
            if positions:
                sorted_positions = sorted(positions, key=lambda x: x.get("unrealized_pnl_pct", 0) or 0, reverse=True)
                text += "📈 今日最佳：\n"
                for p in sorted_positions[:3]:
                    name = p.get("name", p["symbol"])
                    pnl_pct = p.get("unrealized_pnl_pct", 0) or 0
                    text += f"  • {name}（{p['symbol']}）: {pnl_pct:+.2f}%\n"

                text += "\n📉 今日最差：\n"
                for p in sorted_positions[-3:]:
                    name = p.get("name", p["symbol"])
                    pnl_pct = p.get("unrealized_pnl_pct", 0) or 0
                    text += f"  • {name}（{p['symbol']}）: {pnl_pct:+.2f}%\n"

            await feishu_bot.send_text(text)
            logger.info("Daily P&L pushed")

    except Exception as e:
        logger.error(f"Daily P&L push failed: {e}")


async def sync_yangjibao():
    """Auto-sync portfolio from Yangjibao daily at 20:00."""
    try:
        from app.database import async_session
        from app.services.yangjibao_service import YangjibaoService

        async with async_session() as db:
            service = YangjibaoService(db)
            result = await service.sync_portfolio()

            if result.get("success"):
                logger.info(f"Yangjibao auto-sync: {result.get('positions_count')} positions, ¥{result.get('total_value', 0):.2f}")

                # Push summary to Feishu
                if feishu_bot.configured:
                    await feishu_bot.send_text(
                        f"🔄 养基宝自动同步完成\n\n"
                        f"持仓数：{result.get('positions_count', 0)}\n"
                        f"总市值：¥{result.get('total_value', 0):,.2f}"
                    )
            else:
                error = result.get("error", "unknown")
                if error == "not_authenticated":
                    logger.warning("Yangjibao sync skipped: not authenticated")
                else:
                    logger.error(f"Yangjibao sync failed: {error}")

    except Exception as e:
        logger.error(f"Yangjibao auto-sync failed: {e}")
