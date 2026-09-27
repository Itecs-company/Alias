from sqlalchemy import select

from app.models.part import Manufacturer, Part
from app.models.search_log import SearchLog
from app.schemas.part import PartBase
from app.services import optimized_search_engine as engine_module
from app.services.optimized_search_engine import OptimizedPartSearchEngine, normalize_stages
from app.services.search_providers import SearchProvider
from tests.conftest import FakeProvider, hit

STM_HITS = [
    hit("STM32F103C8 - Product - STMicroelectronics", "https://www.st.com/en/microcontrollers/stm32f103c8.html",
        "STM32F103C8T6 mainstream performance line"),
    hit("STM32F103C8T6 STMicroelectronics | Microcontrollers | DigiKey",
        "https://www.digikey.com/en/products/detail/stmicroelectronics/STM32F103C8T6/1646338", "Buy now"),
]
NE555_HITS = [
    hit("NE555 data sheet, product information | TI.com", "https://www.ti.com/product/NE555", "NE555P precision timer"),
    hit("NE555P Texas Instruments | Mouser", "https://www.mouser.com/ProductDetail/Texas-Instruments/NE555P", ""),
]
JUNK = [hit("Walmart | Save Money", "https://www.walmart.com/", "Shop Walmart.com today")]


def make_engine(session, providers, **kwargs):
    kwargs.setdefault("use_ai", False)
    return OptimizedPartSearchEngine(session, web_providers=providers, serpapi_provider=None, **kwargs)


def test_normalize_stages():
    assert normalize_stages(None) is None
    assert normalize_stages(["OpenAI", "google", "bogus"]) == ["OpenAI", "googlesearch"]
    assert normalize_stages(["bogus"]) is None


async def test_batch_search_is_concurrent_safe_and_persists(db_session):
    provider = FakeProvider("web", {"STM32F103C8T6": STM_HITS, "NE555P": NE555_HITS, "NE555P TI": NE555_HITS})
    engine = make_engine(db_session, [provider], concurrency=4)
    items = [
        PartBase(part_number="STM32F103C8T6"),
        PartBase(part_number="NE555P", manufacturer_hint="TI"),
        PartBase(part_number=" stm32f103c8t6 "),  # дубликат — ищется один раз
        PartBase(part_number="UNKNOWN-0001", manufacturer_hint="Acme"),
    ]
    results = await engine.search_many(items, debug=True)

    assert [r.manufacturer_name for r in results] == [
        "STMicroelectronics", "Texas Instruments", "STMicroelectronics", None,
    ]
    assert results[1].match_status == "matched" and results[1].alias_used == "TI"
    assert results[3].match_status == "pending"
    assert [stage.name for stage in results[0].stage_history] == ["Internet", "googlesearch", "OpenAI"]
    assert results[0].search_stage == "Internet"
    assert results[0].country == "Швейцария"  # справочная информация без OpenAI
    assert results[0].debug_log and "Кандидаты" in results[0].debug_log

    parts = (await db_session.execute(select(Part).order_by(Part.id))).scalars().all()
    assert sorted(p.part_number for p in parts) == ["NE555P", "STM32F103C8T6", "UNKNOWN-0001"]
    manufacturers = (await db_session.execute(select(Manufacturer))).scalars().all()
    assert {m.name for m in manufacturers} == {"STMicroelectronics", "Texas Instruments"}
    logs = (await db_session.execute(select(SearchLog))).scalars().all()
    assert logs, "логи запросов должны сохраняться"


async def test_cache_and_forced_stages(db_session):
    provider = FakeProvider("web", {"STM32F103C8T6": STM_HITS})
    engine = make_engine(db_session, [provider])
    await engine.search_many([PartBase(part_number="STM32F103C8T6")])
    calls = len(provider.calls)

    cached = await engine.search_many([PartBase(part_number="STM32F103C8T6", manufacturer_hint="ST")])
    assert cached[0].search_stage == "cache"
    assert cached[0].match_status == "matched"
    assert cached[0].country == "Швейцария"
    assert len(provider.calls) == calls

    # Явно выбранный этап игнорирует кеш
    SearchProvider.reset_state()
    forced = await engine.search_many([PartBase(part_number="STM32F103C8T6")], stages=["Internet"])
    assert forced[0].search_stage == "Internet"
    assert len(provider.calls) > calls

    # Этап googlesearch без настроек — пропускается, прежний результат сохраняется
    google_only = await engine.search_many([PartBase(part_number="STM32F103C8T6")], stages=["googlesearch"])
    assert google_only[0].stage_history[0].status == "skipped"
    assert google_only[0].stage_history[1].status == "skipped"
    assert google_only[0].manufacturer_name == "STMicroelectronics"


async def test_junk_results_fall_back_to_next_provider(db_session):
    poisoned = FakeProvider("poisoned")
    poisoned.default = JUNK
    good = FakeProvider("good", {"STM32F103C8T6": STM_HITS, "NE555P": NE555_HITS})
    engine = make_engine(db_session, [poisoned, good], concurrency=1)
    results = await engine.search_many([PartBase(part_number="STM32F103C8T6"), PartBase(part_number="NE555P")])
    assert [r.manufacturer_name for r in results] == ["STMicroelectronics", "Texas Instruments"]
    assert not poisoned.available  # два раза подряд мусор → провайдер отключён


async def test_ai_stage_uses_context(db_session, monkeypatch):
    captured = {}

    async def fake_chat_json(messages, **kwargs):
        captured["prompt"] = messages[-1]["content"]
        return {"manufacturer": "Sibeco", "confidence": 0.9, "source_url": None, "reason": "brand in snippet"}

    monkeypatch.setattr(engine_module, "chat_json", fake_chat_json)
    provider = FakeProvider("web")
    provider.default = [hit("Зонд 0563-1234", "https://shop.example.ru/0563-1234", "Артикул 0563-1234, зонд Sibeco")]
    engine = make_engine(db_session, [provider], use_ai=True)
    engine.info_extractor.use_ai = False
    results = await engine.search_many([PartBase(part_number="0563-1234")], stages=["OpenAI"])
    result = results[0]
    assert result.manufacturer_name == "Sibeco"
    assert result.search_stage == "OpenAI"
    assert "0563-1234" in captured["prompt"]
    assert [stage.status for stage in result.stage_history][:2] == ["skipped", "skipped"]


async def test_failure_of_one_item_does_not_break_batch(db_session, monkeypatch):
    provider = FakeProvider("web", {"STM32F103C8T6": STM_HITS})
    engine = make_engine(db_session, [provider])
    original = engine.search_part

    async def flaky(part, **kwargs):
        if part.part_number == "BOOM":
            raise RuntimeError("boom")
        return await original(part, **kwargs)

    monkeypatch.setattr(engine, "search_part", flaky)
    results = await engine.search_many([PartBase(part_number="BOOM"), PartBase(part_number="STM32F103C8T6")])
    assert results[0].manufacturer_name is None
    assert "boom" in (results[0].stage_history[0].message or "")
    assert results[1].manufacturer_name == "STMicroelectronics"


async def test_cyrillic_part_and_unknown_manufacturer_are_reused(db_session):
    results_for = [hit("К155ЛА3 ООО Ромашка", "https://shop.example.ru/k155la3", "Производитель: ООО Ромашка. К155ЛА3")]
    provider = FakeProvider("web")
    provider.default = results_for
    engine = make_engine(db_session, [provider])
    await engine.search_many([PartBase(part_number="К155ЛА3")], stages=["Internet"])
    # Повторный поиск того же артикула и того же неизвестного производителя не должен
    # создавать дубликаты (SQLite lower() не работает с кириллицей)
    SearchProvider.reset_state()
    await engine.search_many([PartBase(part_number="К155ЛА3")], stages=["Internet"])
    parts = (await db_session.execute(select(Part))).scalars().all()
    manufacturers = (await db_session.execute(select(Manufacturer))).scalars().all()
    assert len(parts) == 1
    assert len(manufacturers) == 1
    assert parts[0].manufacturer_name == manufacturers[0].name
