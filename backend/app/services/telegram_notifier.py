"""Сервис для отправки уведомлений в Telegram"""
from __future__ import annotations

import asyncio
import html
import time

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.http import httpx_client_kwargs
from app.models.settings import Settings

# Telegram ограничивает длину сообщения 4096 символами
MAX_MESSAGE_LENGTH = 4000


class TelegramNotifier:
    """Класс для отправки уведомлений в Telegram"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.base_url = "https://api.telegram.org/bot{token}/{method}"

    async def get_settings(self) -> Settings | None:
        """Получает настройки из БД"""
        stmt = select(Settings).order_by(Settings.id).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def send_message(self, message: str, force: bool = False) -> tuple[bool, str | None]:
        """
        Отправляет сообщение в Telegram (``message`` — HTML, пользовательские данные
        должны быть экранированы вызывающим кодом).

        Returns:
            (успех, описание ошибки)
        """
        settings = await self.get_settings()

        if not settings:
            return False, "Telegram настройки не сконфигурированы"

        if not force and not settings.telegram_enabled:
            logger.debug("Telegram notifications are disabled")
            return False, "Уведомления Telegram отключены"

        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            return False, "Не указан токен бота или chat ID"

        url = self.base_url.format(token=settings.telegram_bot_token.strip(), method="sendMessage")
        payload = {
            "chat_id": settings.telegram_chat_id.strip(),
            "text": message[:MAX_MESSAGE_LENGTH],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            async with httpx.AsyncClient(**httpx_client_kwargs(timeout=httpx.Timeout(10.0))) as client:
                response = await client.post(url, json=payload)
            try:
                result = response.json()
            except ValueError:
                result = {}
            if response.status_code == 200 and result.get("ok"):
                logger.info("Telegram message sent to chat {chat}", chat=settings.telegram_chat_id)
                return True, None
            description = result.get("description") or f"HTTP {response.status_code}"
            logger.error("Telegram API returned error: {error}", error=description)
            return False, f"Telegram API: {description}"
        except httpx.HTTPError as e:
            logger.error("Failed to send Telegram message: {error!r}", error=e)
            return False, f"Ошибка соединения с Telegram: {e.__class__.__name__}"

    async def notify_error(self, error_message: str, details: str | None = None) -> bool:
        """Отправляет уведомление об ошибке"""
        settings = await self.get_settings()
        if not settings or not settings.notify_on_errors:
            return False

        message = f"🚨 <b>Ошибка в AliasFinder</b>\n\n{html.escape(error_message)}"
        if details:
            message += f"\n\n<i>Детали:</i>\n<code>{html.escape(details[:1500])}</code>"

        success, _ = await self.send_message(message)
        return success

    async def notify_quota(self, service: str, details: str | None = None) -> bool:
        """Уведомление об исчерпании баланса/квоты внешнего сервиса."""
        settings = await self.get_settings()
        if not settings or not settings.notify_on_low_balance:
            return False
        message = (
            f"⚠️ <b>Низкий баланс / исчерпана квота: {html.escape(service)}</b>\n\n"
            "Пополните баланс или увеличьте лимит, чтобы поиск продолжал работать."
        )
        if details:
            message += f"\n\n<code>{html.escape(details[:1500])}</code>"
        success, _ = await self.send_message(message)
        return success

    async def notify_low_balance(self, service: str, current_balance: float, threshold: float) -> bool:
        """Отправляет уведомление о низком балансе"""
        settings = await self.get_settings()
        if not settings or not settings.notify_on_low_balance:
            return False

        # Проверяем, отправляли ли мы уже уведомление для этого баланса
        if service == "OpenAI":
            if settings.last_openai_balance_alert is not None and settings.last_openai_balance_alert <= current_balance:
                return False
            settings.last_openai_balance_alert = current_balance
        elif service == "Google":
            if settings.last_google_balance_alert is not None and settings.last_google_balance_alert <= current_balance:
                return False
            settings.last_google_balance_alert = current_balance

        await self.session.commit()

        message = (
            f"⚠️ <b>Низкий баланс {html.escape(service)}</b>\n\n"
            f"Текущий баланс: <b>${current_balance:.2f}</b>\n"
            f"Пороговое значение: ${threshold:.2f}\n\n"
            f"Пожалуйста, пополните баланс для продолжения работы."
        )
        success, _ = await self.send_message(message)
        return success

    async def test_connection(self, text: str | None = None) -> tuple[bool, str]:
        """Тестирует подключение к Telegram"""
        body = html.escape(text or "Тестовое сообщение из AliasFinder")
        success, error = await self.send_message(f"✅ {body}\n\nПодключение успешно!", force=True)
        if success:
            return True, "Сообщение успешно отправлено в Telegram"
        return False, error or "Не удалось отправить сообщение. Проверьте настройки."


# --- Фоновые уведомления из поискового движка ------------------------------------------

_last_sent: dict[str, float] = {}
_background_tasks: set[asyncio.Task] = set()
NOTIFY_THROTTLE_SECONDS = 3600.0


async def _send_admin_notification(title: str, details: str | None, low_balance: bool) -> None:
    from app.core.database import async_session_factory

    try:
        # Отдельная сессия: основная сессия поиска используется параллельно
        async with async_session_factory() as session:
            notifier = TelegramNotifier(session)
            if low_balance:
                await notifier.notify_quota(title, details)
            else:
                await notifier.notify_error(title, details)
    except Exception as exc:  # noqa: BLE001 - уведомления не должны ломать поиск
        logger.debug("Failed to send admin notification: {exc!r}", exc=exc)


def notify_admins(kind: str, title: str, details: str | None = None, *, low_balance: bool = False) -> None:
    """Отправляет уведомление в Telegram в фоне, не чаще раза в час для одного типа."""
    now = time.monotonic()
    if now - _last_sent.get(kind, float("-inf")) < NOTIFY_THROTTLE_SECONDS:
        return
    _last_sent[kind] = now
    try:
        task = asyncio.get_running_loop().create_task(_send_admin_notification(title, details, low_balance))
    except RuntimeError:
        return
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
