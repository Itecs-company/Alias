import base64

import httpx

from app.services import search_providers
from app.services.search_providers import (
    BingWebSearchProvider,
    GoogleWebSearchProvider,
    SearchProvider,
    decode_bing_url,
    decode_duckduckgo_url,
    decode_yahoo_url,
    parse_bing_html,
    parse_duckduckgo_lite_html,
    parse_yahoo_html,
)
from tests.conftest import FakeProvider


def _bing_link(url: str) -> str:
    encoded = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    return f"https://www.bing.com/ck/a?!&&p=abc&u=a1{encoded}&ntb=1"


BING_HTML = f"""
<ol id="b_results">
  <li class="b_algo"><h2><a href="{_bing_link('https://www.st.com/resource/en/datasheet/lm317.pdf')}">LM317 datasheet</a></h2>
    <div class="b_caption"><p>The LM317 is an adjustable regulator from STMicroelectronics</p></div></li>
  <li class="b_ad"><h2><a href="https://ads.example.com">Ad</a></h2></li>
  <li class="b_algo"><h2><a href="https://www.mouser.com/ProductDetail/STMicroelectronics/LM317T">LM317T STMicroelectronics | Mouser</a></h2>
    <p>LM317T Linear Voltage Regulators</p></li>
</ol>
"""

YAHOO_HTML = """
<div class="algo"><div class="compTitle"><h3><a href="https://r.search.yahoo.com/_ylt=x;_ylu=y/RV=2/RE=1/RO=10/RU=https%3a%2f%2fwww.st.com%2fen%2fstm32f103c8.html/RK=2/RS=abc-">STM32F103C8 - Product - STMicroelectronics</a></h3></div>
  <div class="compText"><p>The STM32F103xx medium-density performance line</p></div></div>
<div class="algo"><h3><a href="https://search.yahoo.com/internal">Yahoo internal</a></h3></div>
"""

DDG_HTML = """
<table>
<tr><td><a class="result-link" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.ti.com%2Fproduct%2FLM317&rut=x">LM317 | TI.com</a></td></tr>
<tr><td class="result-snippet">TI's LM317 is a 1.5-A adjustable linear voltage regulator</td></tr>
<tr><td><a class="result-link" href="https://duckduckgo.com/y.js?ad_domain=x">Sponsored</a></td></tr>
</table>
"""


def test_decoders():
    assert decode_bing_url(_bing_link("https://example.com/a?b=1")) == "https://example.com/a?b=1"
    assert decode_bing_url("https://direct.example.com") == "https://direct.example.com"
    assert decode_bing_url("/search?q=x") is None
    assert decode_yahoo_url("https://r.search.yahoo.com/x/RU=https%3a%2f%2fa.com%2fb/RK=2/RS=z") == "https://a.com/b"
    assert decode_duckduckgo_url("//duckduckgo.com/l/?uddg=https%3A%2F%2Fa.com") == "https://a.com"
    assert decode_duckduckgo_url("https://duckduckgo.com/y.js?ad=1") is None


def test_parsers():
    bing = parse_bing_html(BING_HTML, 10)
    assert [item["link"] for item in bing] == [
        "https://www.st.com/resource/en/datasheet/lm317.pdf",
        "https://www.mouser.com/ProductDetail/STMicroelectronics/LM317T",
    ]
    assert "STMicroelectronics" in bing[0]["snippet"]

    yahoo = parse_yahoo_html(YAHOO_HTML, 10)
    assert len(yahoo) == 1 and yahoo[0]["link"] == "https://www.st.com/en/stm32f103c8.html"

    ddg = parse_duckduckgo_lite_html(DDG_HTML, 10)
    assert ddg == [
        {
            "title": "LM317 | TI.com",
            "link": "https://www.ti.com/product/LM317",
            "snippet": "TI's LM317 is a 1.5-A adjustable linear voltage regulator",
        }
    ]


def _mock_client(monkeypatch, handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(search_providers, "get_http_client", lambda: client)
    return client


async def test_google_js_wall_blocks_provider(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(200, text='<html><a href="/httpservice/retry/enablejs">enable js</a></html>')

    _mock_client(monkeypatch, handler)
    provider = GoogleWebSearchProvider()
    assert await provider.search("LM317T") == []
    assert not provider.available
    # Заблокированный провайдер больше не делает запросов
    assert await provider.search("NE555") == []
    assert len(calls) == 1


async def test_bing_captcha_and_cache(monkeypatch):
    responses = iter([BING_HTML, "<html>Please solve the challenge captcha</html>"])
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text=next(responses))

    _mock_client(monkeypatch, handler)
    provider = BingWebSearchProvider()
    first = await provider.search("LM317T")
    cached = await provider.search("  lm317t ")
    assert first == cached and len(calls) == 1  # повторный запрос берётся из кеша
    assert await provider.search("NE555") == []
    assert not provider.available  # капча → провайдер отключён


async def test_http_errors_are_handled(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    _mock_client(monkeypatch, handler)
    monkeypatch.setattr(search_providers.asyncio, "sleep", _no_sleep)
    provider = BingWebSearchProvider()
    assert await provider.search("LM317T") == []
    assert provider.available  # 5xx не блокирует провайдера


async def _no_sleep(_seconds: float) -> None:
    return None


async def test_irrelevant_streak_blocks_web_provider():
    provider = FakeProvider("junk")
    provider.mark_irrelevant()
    assert provider.available
    provider.mark_irrelevant()
    assert not provider.available
    api = FakeProvider("paid", kind="api")
    api.mark_irrelevant()
    api.mark_irrelevant()
    assert api.available  # платные API не блокируются по этому признаку
    SearchProvider.reset_state()
    assert provider.available


async def test_yahoo_bot_verification_blocks_provider(monkeypatch):
    from app.services.search_providers import YahooSearchProvider

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search":
            return httpx.Response(302, headers={"location": "https://search.yahoo.com/_bv/v.gif?orig=x"})
        return httpx.Response(500, text="INKApi Error")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    monkeypatch.setattr(search_providers, "get_http_client", lambda: client)
    monkeypatch.setattr(search_providers.asyncio, "sleep", _no_sleep)
    provider = YahooSearchProvider()
    assert await provider.search("ATMEGA328P-PU") == []
    assert not provider.available
