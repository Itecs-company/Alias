from pydantic import BaseModel, Field


class SettingsBase(BaseModel):
    """Базовая схема настроек"""
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_enabled: bool = False
    openai_balance_threshold: float | None = Field(default=5.0, ge=0)
    google_balance_threshold: float | None = Field(default=10.0, ge=0)
    notify_on_errors: bool = True
    notify_on_low_balance: bool = True


class SettingsUpdate(BaseModel):
    """Схема для обновления настроек"""
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_enabled: bool | None = None
    openai_balance_threshold: float | None = Field(default=None, ge=0)
    google_balance_threshold: float | None = Field(default=None, ge=0)
    notify_on_errors: bool | None = None
    notify_on_low_balance: bool | None = None


class SettingsRead(SettingsBase):
    """Схема для чтения настроек"""
    id: int

    class Config:
        from_attributes = True


class TelegramTestRequest(BaseModel):
    """Схема для тестирования Telegram уведомлений"""
    message: str = "Тестовое сообщение из AliasFinder"
