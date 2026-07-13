"""Feishu Bot — webhook-based push notifications.

Uses Feishu custom bot webhook (open.feishu.cn/open-apis/bot/v2/hook/xxx).
Supports text and interactive card messages.
"""
import logging
from datetime import datetime
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


class FeishuBot:
    """Feishu custom bot via webhook."""

    def __init__(self, webhook_url: str | None = None):
        self._webhook = (webhook_url or settings.feishu_webhook_url).strip()

    @property
    def configured(self) -> bool:
        return bool(self._webhook and self._webhook.startswith("https://open.feishu.cn"))

    async def send_text(self, text: str) -> bool:
        """Send a plain text message."""
        if not self.configured:
            logger.warning("Feishu webhook not configured")
            return False

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    self._webhook,
                    json={"msg_type": "text", "content": {"text": text}},
                )
                data = resp.json()
                if data.get("code") == 0:
                    logger.info("Feishu text sent OK")
                    return True
                logger.error(f"Feishu send failed: {data}")
                return False
        except Exception as e:
            logger.error(f"Feishu send error: {e}")
            return False

    async def send_card(self, card: dict) -> bool:
        """Send an interactive card message.

        Card format: https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot
        """
        if not self.configured:
            return False

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    self._webhook,
                    json={"msg_type": "interactive", "card": card},
                )
                data = resp.json()
                if data.get("code") == 0:
                    logger.info("Feishu card sent OK")
                    return True
                logger.error(f"Feishu card failed: {data}")
                return False
        except Exception as e:
            logger.error(f"Feishu card error: {e}")
            return False

    async def send_market_open(self, indices: list[dict], sentiment: dict) -> bool:
        """Send pre-market open summary."""
        today = datetime.now().strftime("%Y-%m-%d")
        lines = [f"📈 开盘速报 | {today}", ""]

        # Global indices
        lines.append("🌍 全球指数：")
        for idx in indices[:8]:
            name = idx.get("name", idx.get("code", ""))
            pct = idx.get("change_pct", 0)
            emoji = "🔴" if pct > 0 else "🟢" if pct < 0 else "⚪"
            lines.append(f"  {emoji} {name}: {pct:+.2f}%")

        # Sentiment
        if sentiment:
            fg = sentiment.get("fear_greed_index", "N/A")
            label = sentiment.get("fear_greed_label", "")
            nb = sentiment.get("north_bound_flow", 0)
            nb_emoji = "🔴流入" if nb > 0 else "🟢流出" if nb < 0 else ""
            lines.append(f"\n😱 恐慌贪婪指数: {fg} ({label})")
            if nb:
                lines.append(f"💰 北向资金: {nb_emoji} {abs(nb):.1f}亿")

        lines.append(f"\n⏰ A股 9:30 开盘，祝交易顺利！")
        return await self.send_text("\n".join(lines))

    async def send_market_close(self, summary: str, portfolio_pnl: dict = None) -> bool:
        """Send market close summary with portfolio P&L."""
        today = datetime.now().strftime("%Y-%m-%d")
        text = f"📉 收盘总结 | {today}\n\n{summary}"

        if portfolio_pnl:
            total = portfolio_pnl.get("total_value", 0)
            pnl = portfolio_pnl.get("total_pnl", 0)
            pnl_pct = portfolio_pnl.get("total_pnl_pct", 0)
            emoji = "🎉" if pnl > 0 else "😔"
            text += f"\n\n💼 你的持仓：\n  总市值 ¥{total:,.2f}\n  当日盈亏 {emoji} ¥{pnl:+,.2f} ({pnl_pct:+.2f}%)"

        return await self.send_text(text)

    async def send_alert(self, alert_type: str, symbol: str, name: str, value: float, threshold: float) -> bool:
        """Send anomaly alert."""
        emoji_map = {
            "price_up": "🚀",
            "price_down": "📉",
            "volume_spike": "📊",
            "consecutive": "⚠️",
        }
        emoji = emoji_map.get(alert_type, "🔔")

        text = (
            f"{emoji} 异动预警\n\n"
            f"基金：{name}（{symbol}）\n"
            f"触发条件：{alert_type}\n"
            f"当前值：{value:.2f}%（阈值 {threshold:.1f}%）\n"
            f"时间：{datetime.now().strftime('%H:%M:%S')}\n\n"
            f"⚠️ 仅供参考，不构成投资建议"
        )
        return await self.send_text(text)

    async def send_signal(self, signal_type: str, symbol: str, name: str, reason: str, confidence: float) -> bool:
        """Send trading signal notification."""
        emoji_map = {"buy": "🟢买入", "sell": "🔴卖出", "strong_buy": "🟢强烈买入", "strong_sell": "🔴强烈卖出"}
        emoji = emoji_map.get(signal_type, "⚪")

        text = (
            f"{emoji} 交易信号\n\n"
            f"标的：{name}（{symbol}）\n"
            f"信号：{signal_type}\n"
            f"置信度：{confidence:.0%}\n"
            f"原因：{reason}\n"
            f"时间：{datetime.now().strftime('%H:%M:%S')}\n\n"
            f"⚠️ 仅供参考，不构成投资建议"
        )
        return await self.send_text(text)

    async def send_guardian_briefing(self, result: "BriefingResult") -> bool:  # noqa: F821
        """Format and push a Guardian scan result.

        Layout:
          🛡️ 午盘/尾盘/临时体检 | YYYY-MM-DD HH:MM
          <briefing_text>
          <top 5 alerts as bullet lines>
        """
        # Deferred import to avoid a schemas ↔ feishu circular dependency
        from app.schemas.guardian import AlertSeverity, BriefingSlot  # noqa: F401

        if not self.configured:
            return False

        try:
            slot_val = result.slot.value if hasattr(result.slot, "value") else str(result.slot)
        except Exception:
            slot_val = "unknown"
        slot_label = {"midday": "午盘", "close": "尾盘", "manual": "临时"}.get(slot_val, "体检")

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [f"🛡️ {slot_label}体检 | {now}"]

        if result.briefing_text:
            lines.append("")
            lines.append(result.briefing_text.strip())

        if result.alerts:
            lines.append("")
            lines.append(f"⚠️ 预警明细({len(result.alerts)} 条):")
            sev_emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
            for a in result.alerts[:5]:
                sev = a.severity if isinstance(a.severity, str) else a.severity.value
                trig = a.trigger if isinstance(a.trigger, str) else a.trigger.value
                lines.append(f"  {sev_emoji.get(sev, '⚪')} {a.name}({a.code}) — {trig}: {a.note}")
            if len(result.alerts) > 5:
                lines.append(f"  …(还有 {len(result.alerts) - 5} 条,详见前端)")

        return await self.send_text("\n".join(lines))


# Global singleton
feishu_bot = FeishuBot()
