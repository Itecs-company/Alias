"""
Rate limiting и кэширование для поисковых провайдеров.

Включает:
- RateLimiter: Ограничение частоты запросов с временными окнами
- SearchCache: In-memory кэш для результатов поиска
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from cachetools import TTLCache
from loguru import logger


@dataclass
class RateLimitConfig:
    """Конфигурация rate limiter"""
    max_requests: int  # Максимум запросов
    time_window: float  # Временное окно в секундах
    min_interval: float = 0.0  # Минимальный интервал между запросами


class RateLimiter:
    """
    Rate limiter с временным окном и минимальным интервалом между запросами.

    Примеры использования:
    - Google Search: 100 запросов в день = ~4 запроса в час
    - Google Custom Search: 100 запросов в день
    - OpenAI: зависит от tier, обычно 3500 RPM
    """

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self.requests: deque[float] = deque()
        self.lock = asyncio.Lock()
        self.last_request_time: float = 0.0

    async def acquire(self) -> None:
        """
        Ожидает, пока не станет возможным выполнить запрос.

        Учитывает:
        1. Максимальное количество запросов в временном окне
        2. Минимальный интервал между запросами
        """
        async with self.lock:
            now = time.time()

            # Удаляем старые запросы за пределами временного окна
            cutoff = now - self.config.time_window
            while self.requests and self.requests[0] < cutoff:
                self.requests.popleft()

            # Проверяем минимальный интервал
            if self.last_request_time > 0:
                time_since_last = now - self.last_request_time
                if time_since_last < self.config.min_interval:
                    wait_time = self.config.min_interval - time_since_last
                    logger.debug(
                        "Rate limiter: waiting {wait:.2f}s for min_interval",
                        wait=wait_time
                    )
                    await asyncio.sleep(wait_time)
                    now = time.time()

            # Ждем, если достигли лимита запросов
            if len(self.requests) >= self.config.max_requests:
                oldest_request = self.requests[0]
                wait_time = oldest_request + self.config.time_window - now
                if wait_time > 0:
                    logger.warning(
                        "Rate limit reached: waiting {wait:.2f}s (window: {window}s, max: {max})",
                        wait=wait_time,
                        window=self.config.time_window,
                        max=self.config.max_requests
                    )
                    await asyncio.sleep(wait_time)
                    now = time.time()
                    # Очищаем старые запросы после ожидания
                    cutoff = now - self.config.time_window
                    while self.requests and self.requests[0] < cutoff:
                        self.requests.popleft()

            # Регистрируем текущий запрос
            self.requests.append(now)
            self.last_request_time = now

    def get_stats(self) -> dict[str, Any]:
        """Возвращает статистику rate limiter"""
        now = time.time()
        cutoff = now - self.config.time_window
        active_requests = sum(1 for t in self.requests if t >= cutoff)

        return {
            "max_requests": self.config.max_requests,
            "time_window": self.config.time_window,
            "active_requests": active_requests,
            "available_requests": max(0, self.config.max_requests - active_requests),
            "min_interval": self.config.min_interval,
            "last_request_ago": now - self.last_request_time if self.last_request_time > 0 else None,
        }


class SearchCache:
    """
    In-memory кэш для результатов поиска с TTL (Time To Live).

    Использует cachetools.TTLCache для автоматической очистки устаревших записей.
    """

    def __init__(self, maxsize: int = 1000, ttl: int = 3600):
        """
        Args:
            maxsize: Максимальное количество элементов в кэше
            ttl: Время жизни записи в секундах (по умолчанию 1 час)
        """
        self.cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)
        self.lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0

    def _make_key(self, provider: str, query: str, **kwargs: Any) -> str:
        """
        Создает ключ для кэша на основе провайдера, запроса и параметров.

        Args:
            provider: Название провайдера (google, openai, etc.)
            query: Поисковый запрос
            **kwargs: Дополнительные параметры (max_results, etc.)
        """
        # Сортируем kwargs для стабильности ключа
        params_str = "&".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
        key_str = f"{provider}:{query}:{params_str}"
        # Используем хэш для компактности ключа
        return hashlib.md5(key_str.encode()).hexdigest()

    async def get(
        self,
        provider: str,
        query: str,
        **kwargs: Any
    ) -> list[dict[str, Any]] | None:
        """
        Получает результат из кэша.

        Returns:
            Закэшированный результат или None, если не найден
        """
        key = self._make_key(provider, query, **kwargs)
        async with self.lock:
            result = self.cache.get(key)
            if result is not None:
                self._hits += 1
                logger.debug(
                    "Cache HIT for {provider}:{query} (hit rate: {rate:.1%})",
                    provider=provider,
                    query=query[:50],
                    rate=self.hit_rate
                )
                return result
            else:
                self._misses += 1
                logger.debug(
                    "Cache MISS for {provider}:{query}",
                    provider=provider,
                    query=query[:50]
                )
                return None

    async def set(
        self,
        provider: str,
        query: str,
        value: list[dict[str, Any]],
        **kwargs: Any
    ) -> None:
        """Сохраняет результат в кэш"""
        key = self._make_key(provider, query, **kwargs)
        async with self.lock:
            self.cache[key] = value
            logger.debug(
                "Cache SET for {provider}:{query} ({size} results)",
                provider=provider,
                query=query[:50],
                size=len(value)
            )

    async def clear(self) -> None:
        """Очищает весь кэш"""
        async with self.lock:
            self.cache.clear()
            self._hits = 0
            self._misses = 0
            logger.info("Search cache cleared")

    @property
    def hit_rate(self) -> float:
        """Возвращает процент попаданий в кэш"""
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    def get_stats(self) -> dict[str, Any]:
        """Возвращает статистику кэша"""
        return {
            "size": len(self.cache),
            "maxsize": self.cache.maxsize,
            "ttl": self.cache.ttl,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self.hit_rate,
        }


# Глобальные экземпляры для использования в провайдерах

# Google Web Search: консервативный лимит (100 запросов в день)
# Распределяем: 100 запросов / 24 часа = ~4 запроса в час
# Используем окно в 1 час с минимальным интервалом 2 секунды
GOOGLE_WEB_RATE_LIMITER = RateLimiter(
    RateLimitConfig(
        max_requests=10,  # 10 запросов в час (консервативно)
        time_window=3600.0,  # 1 час
        min_interval=2.0,  # Минимум 2 секунды между запросами
    )
)

# Google Custom Search: 100 запросов в день (официальный лимит)
GOOGLE_CSE_RATE_LIMITER = RateLimiter(
    RateLimitConfig(
        max_requests=10,  # 10 запросов в час
        time_window=3600.0,  # 1 час
        min_interval=1.5,  # Минимум 1.5 секунды между запросами
    )
)

# SerpAPI: более щедрый лимит (зависит от плана)
SERPAPI_RATE_LIMITER = RateLimiter(
    RateLimitConfig(
        max_requests=20,  # 20 запросов в час
        time_window=3600.0,  # 1 час
        min_interval=1.0,  # Минимум 1 секунда между запросами
    )
)

# OpenAI: зависит от tier, используем консервативный лимит
# Tier 1: 500 RPM, Tier 2: 5000 RPM
OPENAI_RATE_LIMITER = RateLimiter(
    RateLimitConfig(
        max_requests=100,  # 100 запросов в минуту (консервативно для Tier 1)
        time_window=60.0,  # 1 минута
        min_interval=0.5,  # Минимум 0.5 секунды между запросами
    )
)

# Глобальный кэш для всех поисковых запросов
# maxsize=1000 записей, TTL=3600 секунд (1 час)
SEARCH_CACHE = SearchCache(maxsize=1000, ttl=3600)
