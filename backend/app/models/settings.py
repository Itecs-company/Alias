from sqlalchemy import Boolean, Column, Float, Integer, String

from .base import Base


class Settings(Base):
    """Настройки системы"""
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)

    # Telegram настройки
    telegram_bot_token = Column(String, nullable=True)
    telegram_chat_id = Column(String, nullable=True)
    telegram_enabled = Column(Boolean, default=False)

    # Пороги баланса
    openai_balance_threshold = Column(Float, nullable=True, default=5.0)  # USD
    google_balance_threshold = Column(Float, nullable=True, default=10.0)  # USD

    # Уведомления
    notify_on_errors = Column(Boolean, default=True)
    notify_on_low_balance = Column(Boolean, default=True)

    # Последние отправленные уведомления (чтобы не спамить)
    last_openai_balance_alert = Column(Float, nullable=True)
    last_google_balance_alert = Column(Float, nullable=True)
