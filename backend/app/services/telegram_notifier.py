"""Сервис для отправки уведомлений в Telegram"""
import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.http import httpx_client_kwargs
from app.models.settings import Settings


class TelegramNotifier:
    """Класс для отправки уведомлений в Telegram"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.base_url = "https://api.telegram.org/bot{token}/{method}"

    async def get_settings(self) -> Settings | None:
        """Получает настройки из БД"""
        stmt = select(Settings).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def send_message(self, message: str, force: bool = False) -> bool:
        """
        Отправляет сообщение в Telegram

        Args:
            message: Текст сообщения
            force: Отправить даже если уведомления отключены (для тестирования)

        Returns:
            True если сообщение отправлено успешно
        """
        settings = await self.get_settings()

        if not settings:
            logger.warning("Telegram settings not found in database")
            return False

        if not force and not settings.telegram_enabled:
            logger.debug("Telegram notifications are disabled")
            return False

        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            logger.warning("Telegram bot token or chat ID not configured")
            return False

        url = self.base_url.format(
            token=settings.telegram_bot_token,
            method="sendMessage"
        )

        payload = {
            "chat_id": settings.telegram_chat_id,
            "text": message,
            "parse_mode": "HTML"
        }

        try:
            async with httpx.AsyncClient(**httpx_client_kwargs(timeout=httpx.Timeout(10.0))) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()

                result = response.json()
                if result.get("ok"):
                    logger.info(f"Telegram message sent successfully to {settings.telegram_chat_id}")
                    return True
                else:
                    logger.error(f"Telegram API returned error: {result}")
                    return False

        except httpx.HTTPError as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending Telegram message: {e}")
            return False

    async def notify_error(self, error_message: str, details: str | None = None) -> bool:
        """Отправляет уведомление об ошибке"""
        settings = await self.get_settings()
        if not settings or not settings.notify_on_errors:
            return False

        message = f"🚨 <b>Ошибка в AliasFinder</b>\n\n{error_message}"
        if details:
            message += f"\n\n<i>Детали:</i>\n{details}"

        return await self.send_message(message)

    async def notify_low_balance(
        self,
        service: str,
        current_balance: float,
        threshold: float
    ) -> bool:
        """
        Отправляет уведомление о низком балансе

        Args:
            service: Название сервиса (OpenAI, Google Search)
            current_balance: Текущий баланс
            threshold: Пороговое значение
        """
        settings = await self.get_settings()
        if not settings or not settings.notify_on_low_balance:
            return False

        # Проверяем, отправляли ли мы уже уведомление для этого баланса
        if service == "OpenAI":
            if settings.last_openai_balance_alert and settings.last_openai_balance_alert <= current_balance:
                logger.debug(f"Already notified about OpenAI balance {current_balance}")
                return False
            settings.last_openai_balance_alert = current_balance
        elif service == "Google":
            if settings.last_google_balance_alert and settings.last_google_balance_alert <= current_balance:
                logger.debug(f"Already notified about Google balance {current_balance}")
                return False
            settings.last_google_balance_alert = current_balance

        await self.session.commit()

        message = (
            f"⚠️ <b>Низкий баланс {service}</b>\n\n"
            f"Текущий баланс: <b>${current_balance:.2f}</b>\n"
            f"Пороговое значение: ${threshold:.2f}\n\n"
            f"Пожалуйста, пополните баланс для продолжения работы."
        )

        return await self.send_message(message)

    async def test_connection(self) -> tuple[bool, str]:
        """
        Тестирует подключение к Telegram

        Returns:
            (success, message)
        """
        settings = await self.get_settings()

        if not settings or not settings.telegram_bot_token or not settings.telegram_chat_id:
            return False, "Telegram настройки не сконфигурированы"

        test_message = "✅ Тестовое сообщение из AliasFinder\n\nПодключение успешно!"

        success = await self.send_message(test_message, force=True)

        if success:
            return True, "Сообщение успешно отправлено в Telegram"
        else:
            return False, "Не удалось отправить сообщение. Проверьте настройки."
