"""Извлечение и агрегация признаков («улик») производителя из выдачи и документов.

Каждый результат поиска или скачанный документ может дать несколько улик вида
«производитель X, вес w». Вес зависит от типа признака (официальный домен,
карточка дистрибьютора, упоминание рядом с артикулом, копирайт в даташите…) и
от того, насколько точно рядом найден сам артикул. Улики с одного домена не
суммируются, а голоса разных доменов объединяются как независимые:
``S = 1 - Π(1 - w)``. Так несколько независимых подтверждений дают высокую
уверенность, а единичное упоминание — низкую.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urlparse

from app.services.manufacturers import (
    find_manufacturer_mentions,
    get_entry,
    hostname,
    is_distributor,
    is_trusted_short_name,
    manufacturer_from_slug,
    manufacturer_from_url,
    manufacturer_similarity,
    normalize_manufacturer_name,
    part_number_key,
    part_number_strength,
)


@dataclass
class SearchHit:
    url: str
    title: str = ""
    snippet: str = ""
    provider: str = ""
    query: str = ""
    rank: int = 0

    @property
    def host(self) -> str:
        return hostname(self.url)

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.snippet}"


@dataclass
class Evidence:
    manufacturer: str
    weight: float
    source_url: str
    kind: str
    detail: str = ""

    @property
    def host(self) -> str:
        return hostname(self.source_url) or self.source_url


@dataclass
class CandidateScore:
    manufacturer: str
    support: float
    confidence: float = 0.0
    evidence: list[Evidence] = field(default_factory=list)

    @property
    def best_evidence(self) -> Evidence | None:
        return max(self.evidence, key=lambda item: item.weight) if self.evidence else None

    def describe(self, limit: int = 4) -> str:
        items = sorted(self.evidence, key=lambda item: item.weight, reverse=True)[:limit]
        return "; ".join(f"{item.kind} ({item.host}, {item.weight:.2f})" for item in items)


# Имена, которые шаблоны иногда захватывают вместо производителя
_GENERIC_NAMES = {
    "the", "all", "all rights", "all rights reserved", "datasheet", "pdf", "data sheet", "product", "products",
    "home", "search", "results", "buy", "price", "stock", "in stock", "new", "original", "manufacturer",
    "brand", "unknown", "n a", "na", "none", "various", "generic", "other", "others", "oem", "see", "details",
    "производитель", "бренд", "неизвестно", "нет", "купить", "цена",
}

# Слова, которых не бывает в названии производителя, но много в заголовках выдачи
_GENERIC_WORDS = {
    "datasheet", "datasheets", "pdf", "html", "price", "prices", "buy", "stock", "sale", "shop", "store",
    "search", "results", "specification", "specifications", "specs", "catalog", "catalogue", "manual",
    "product", "products", "details", "detail", "review", "reviews", "download", "free", "online", "order",
    "купить", "цена", "цены", "каталог", "описание", "характеристики", "даташит", "инструкция", "магазин",
}

_LABEL_RE = re.compile(
    r"(?:manufacturer|mfr\.?|mfg\.?|brand|vendor|made by|hersteller|marque|fabricant|fabricante|"
    r"производитель|изготовитель|бренд|торговая марка|марка)\s*[:：\-–]\s*"
    r"(?P<name>[^\n|;,•·()\[\]]{2,60})",
    re.IGNORECASE,
)
_DATASHEET_DASH_RE = re.compile(r"data\s*sheet\s*(?:\((?:pdf|html)\))?\s*[-–|]\s*(?P<name>[^\n|;,•·()\[\]]{2,60})", re.IGNORECASE)
_COPYRIGHT_RE = re.compile(
    r"(?:©|\(c\)|copyright)\s*(?:©\s*)?(?:\d{4}(?:\s*[-–,]\s*\d{4})*[,.]?\s*)?(?:by\s+)?"
    r"(?P<name>[A-Z][A-Za-z0-9&.,'’\- ]{1,60}?)(?=\s*(?:[.,]?\s*all rights|\.\s|,\s|\n|$|\|))",
)
_STOP_TAIL_RE = re.compile(
    r"\s+(?:is|are|was|and|or|in|at|for|from|with|all|datasheet|pdf|buy|price|stock|инструкция|купить)\b.*$",
    re.IGNORECASE,
)

_WEIGHTS = {
    "official-domain": 0.9,          # страница на сайте производителя с артикулом
    "official-domain-weak": 0.15,    # сайт производителя без явного артикула в выдаче
    "distributor-url": 0.6,          # /detail/<manufacturer>/<part>/ у дистрибьютора
    "listing-title": 0.55,           # "<part> <manufacturer> | Mouser"
    "label": 0.6,                    # "Manufacturer: X"
    "datasheet-title": 0.55,         # "<part> Datasheet (PDF) - X"
    "mention-title": 0.45,
    "mention-snippet": 0.35,
    "hint-in-text": 0.3,
    "doc-official": 0.9,
    "doc-copyright": 0.55,
    "doc-label": 0.6,
    "doc-mentions": 0.5,
}


_LEADING_NOISE_RE = re.compile(r"^(?:(?:©|\(c\)|copyright|by|\d{4}(?:\s*[-–]\s*\d{4})?)[\s,.]*)+", re.IGNORECASE)


def clean_candidate_name(raw: str) -> str | None:
    name = _LEADING_NOISE_RE.sub("", raw.strip())
    # "Производитель: ООО Ромашка. Артикул ..." — название заканчивается на ". "
    name = re.split(r"\.\s+(?=\S)", name, maxsplit=1)[0]
    name = name.strip().strip("\"'«»“”:;,.-–|•· ")
    name = _STOP_TAIL_RE.sub("", name).strip(" ,.;:-–")
    if not name or len(name) < 2 or len(name) > 60:
        return None
    if len(name.split()) > 6:
        return None
    lowered = re.sub(r"[^\w]+", " ", name.lower()).strip()
    if not lowered or lowered in _GENERIC_NAMES or lowered.isdigit():
        return None
    if any(word in _GENERIC_WORDS for word in lowered.split()):
        return None
    if not re.search(r"[A-Za-zА-Яа-яЁё]", name):
        return None
    if len(re.sub(r"[^\w]", "", name)) <= 3 and not is_trusted_short_name(name):
        return None
    return normalize_manufacturer_name(name)


def _looks_like_part(name: str, part_number: str) -> bool:
    key = part_number_key(name)
    target = part_number_key(part_number)
    return bool(key) and bool(target) and (key == target or key.startswith(target) or target.startswith(key))


def _mention_evidence(
    text: str,
    part_strength: float,
    url: str,
    *,
    kind: str,
    weight: float,
) -> list[Evidence]:
    mentions = find_manufacturer_mentions(text)
    if not mentions:
        return []
    distinct = list(dict.fromkeys(mention.canonical for mention in mentions))
    # Несколько разных производителей в одном фрагменте — голос делится между ними
    share = 1.0 / len(distinct)
    return [
        Evidence(name, weight * part_strength * share, url, kind, f"упоминание «{name}»")
        for name in distinct
    ]


def _distributor_url_evidence(hit: SearchHit, part_number: str) -> list[Evidence]:
    try:
        path = unquote(urlparse(hit.url).path)
    except ValueError:
        return []
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return []
    part_strength = part_number_strength(part_number, " ".join(segments).replace("-", " "))
    if part_strength <= 0:
        return []
    evidence: list[Evidence] = []
    for segment in segments:
        if _looks_like_part(segment, part_number):
            continue
        manufacturer = manufacturer_from_slug(segment)
        if manufacturer:
            evidence.append(
                Evidence(
                    manufacturer,
                    _WEIGHTS["distributor-url"] * part_strength,
                    hit.url,
                    "distributor-url",
                    f"сегмент URL «{segment}»",
                )
            )
            break
    return evidence


def _pattern_evidence(text: str, part_number: str, part_strength: float, url: str, *, doc: bool = False) -> list[Evidence]:
    evidence: list[Evidence] = []
    for regex, kind in ((_LABEL_RE, "doc-label" if doc else "label"), (_DATASHEET_DASH_RE, "datasheet-title")):
        for match in regex.finditer(text):
            name = clean_candidate_name(match.group("name"))
            if name and not _looks_like_part(name, part_number):
                evidence.append(Evidence(name, _WEIGHTS[kind] * part_strength, url, kind, f"шаблон «{match.group(0)[:80]}»"))
                break
    return evidence


def _listing_title_evidence(hit: SearchHit, part_number: str, part_strength: float) -> list[Evidence]:
    """Заголовки карточек дистрибьюторов: "LM317T STMicroelectronics | Mouser"."""
    if not hit.title or not is_distributor(hit.url):
        return []
    first_segment = re.split(r"\s[|–]\s|\s-\s", hit.title, maxsplit=1)[0]
    tokens = first_segment.split()
    if len(tokens) < 2:
        return []
    # Артикул — первый токен, дальше — производитель
    if part_number_strength(part_number, tokens[0]) < 0.5:
        return []
    name = clean_candidate_name(" ".join(tokens[1:5]))
    if not name or _looks_like_part(name, part_number):
        return []
    entry = get_entry(name)
    if entry is None and len(tokens) > 4:
        return []  # длинный хвост без известного производителя — скорее описание товара
    return [Evidence(name, _WEIGHTS["listing-title"] * part_strength, hit.url, "listing-title", f"заголовок «{hit.title[:80]}»")]


def evidence_from_hit(hit: SearchHit, part_number: str, hint: str | None = None) -> list[Evidence]:
    """Улики из одного результата поиска (URL, заголовок, сниппет) — без скачивания страницы."""
    evidence: list[Evidence] = []
    url_text = unquote(hit.url).replace("-", " ").replace("_", " ")
    title_strength = part_number_strength(part_number, hit.title)
    snippet_strength = part_number_strength(part_number, hit.snippet)
    url_strength = part_number_strength(part_number, url_text)
    part_strength = max(title_strength, snippet_strength, url_strength)

    official = manufacturer_from_url(hit.url)
    if official:
        if part_strength > 0:
            weight = _WEIGHTS["official-domain"] * (0.6 + 0.4 * part_strength)
            evidence.append(Evidence(official, weight, hit.url, "official-domain", f"официальный сайт {hit.host}"))
        elif hit.rank < 3:
            evidence.append(
                Evidence(official, _WEIGHTS["official-domain-weak"], hit.url, "official-domain-weak", f"сайт {hit.host}")
            )
        return evidence

    if part_strength <= 0:
        return evidence

    if is_distributor(hit.url):
        evidence.extend(_distributor_url_evidence(hit, part_number))
        evidence.extend(_listing_title_evidence(hit, part_number, part_strength))

    evidence.extend(_pattern_evidence(hit.text, part_number, part_strength, hit.url))

    if title_strength > 0:
        evidence.extend(_mention_evidence(hit.title, title_strength, hit.url, kind="mention-title", weight=_WEIGHTS["mention-title"]))
    if snippet_strength > 0 or (title_strength > 0 and hit.snippet):
        evidence.extend(
            _mention_evidence(
                hit.snippet,
                max(snippet_strength, title_strength * 0.8),
                hit.url,
                kind="mention-snippet",
                weight=_WEIGHTS["mention-snippet"],
            )
        )

    if hint and not get_entry(hint):
        # Неизвестный справочнику производитель из подсказки оператора
        hint_clean = normalize_manufacturer_name(hint)
        if len(hint_clean) >= 3 and re.search(
            r"(?<![\w])" + re.escape(hint_clean) + r"(?![\w])", hit.text, re.IGNORECASE
        ):
            evidence.append(
                Evidence(hint_clean, _WEIGHTS["hint-in-text"] * part_strength, hit.url, "hint-in-text", "подсказка в выдаче")
            )
    return evidence


def _window_texts(text: str, part_number: str, radius: int = 400, limit: int = 12) -> list[str]:
    """Фрагменты текста вокруг упоминаний артикула."""
    key = part_number_key(part_number)
    if not key:
        return []
    windows: list[str] = []
    folded = text.upper()
    # Быстрый поиск по первому «якорю» артикула (первые символы ключа)
    anchor = key[: min(len(key), 5)]
    pattern = re.compile(r"[\s\-_./]?".join(re.escape(ch) for ch in anchor), re.IGNORECASE)
    for match in pattern.finditer(folded):
        start = max(0, match.start() - radius)
        end = min(len(text), match.end() + radius)
        window = text[start:end]
        if part_number_strength(part_number, window) > 0:
            windows.append(window)
            if len(windows) >= limit:
                break
    return windows


def evidence_from_document(url: str, text: str, part_number: str, hint: str | None = None) -> list[Evidence]:
    """Улики из скачанной страницы или PDF."""
    if not text:
        return []
    head = text[:20000]
    part_strength = part_number_strength(part_number, text[:400000])
    if part_strength <= 0:
        return []
    evidence: list[Evidence] = []
    official = manufacturer_from_url(url)
    if official:
        evidence.append(Evidence(official, _WEIGHTS["doc-official"] * (0.6 + 0.4 * part_strength), url, "doc-official", "документ на сайте производителя"))

    tail = text[-6000:]
    for source in (head[:6000], tail):
        for match in _COPYRIGHT_RE.finditer(source):
            name = clean_candidate_name(match.group("name"))
            if name and not _looks_like_part(name, part_number):
                evidence.append(Evidence(name, _WEIGHTS["doc-copyright"] * part_strength, url, "doc-copyright", f"копирайт «{match.group(0)[:80]}»"))
                break

    evidence.extend(_pattern_evidence(head, part_number, part_strength, url, doc=True))

    windows = _window_texts(text, part_number)
    counts: dict[str, int] = {}
    for window in windows or [head[:4000]]:
        for mention in find_manufacturer_mentions(window):
            counts[mention.canonical] = counts.get(mention.canonical, 0) + 1
    # Упоминания по всему началу документа (шапка/логотип даташита)
    for mention in find_manufacturer_mentions(head[:3000]):
        counts[mention.canonical] = counts.get(mention.canonical, 0) + 1
    total = sum(counts.values())
    for name, count in counts.items():
        share = count / total
        weight = _WEIGHTS["doc-mentions"] * part_strength * share * min(1.0, 0.5 + 0.1 * count)
        if weight >= 0.05:
            evidence.append(Evidence(name, weight, url, "doc-mentions", f"{count} упоминаний в документе"))

    if hint and not get_entry(hint):
        hint_clean = normalize_manufacturer_name(hint)
        if len(hint_clean) >= 3 and any(
            re.search(r"(?<![\w])" + re.escape(hint_clean) + r"(?![\w])", window, re.IGNORECASE) for window in windows
        ):
            evidence.append(Evidence(hint_clean, _WEIGHTS["hint-in-text"] * part_strength, url, "hint-in-text", "подсказка рядом с артикулом"))
    return evidence


def _same_manufacturer(first: str, second: str) -> bool:
    if first.lower() == second.lower():
        return True
    return manufacturer_similarity(first, second) >= 0.95


def aggregate_evidence(evidence: list[Evidence]) -> list[CandidateScore]:
    """Объединяет улики по производителям; улики с одного домена не суммируются."""
    groups: list[CandidateScore] = []
    for item in evidence:
        if item.weight <= 0:
            continue
        name = normalize_manufacturer_name(item.manufacturer)
        for group in groups:
            if _same_manufacturer(group.manufacturer, name):
                group.evidence.append(item)
                break
        else:
            groups.append(CandidateScore(manufacturer=name, support=0.0, evidence=[item]))

    for group in groups:
        per_host: dict[str, float] = {}
        for item in group.evidence:
            per_host[item.host] = max(per_host.get(item.host, 0.0), min(item.weight, 0.95))
        remaining = 1.0
        for weight in per_host.values():
            remaining *= 1.0 - weight
        group.support = round(min(0.99, 1.0 - remaining), 4)
        # Каноническое имя: предпочитаем известное справочнику
        known = next((get_entry(item.manufacturer) for item in group.evidence if get_entry(item.manufacturer)), None)
        if known:
            group.manufacturer = known.canonical

    groups.sort(key=lambda group: group.support, reverse=True)
    return groups


def rank_candidates(evidence: list[Evidence], hint: str | None = None) -> list[CandidateScore]:
    """Ранжирует кандидатов и вычисляет итоговую уверенность.

    * уверенность лидера снижается, если у второго кандидата сопоставимая поддержка;
    * если подсказка оператора подтверждается заметными уликами (многие детали
      выпускают несколько производителей), выбирается она.
    """
    groups = aggregate_evidence(evidence)
    if not groups:
        return []
    for index, group in enumerate(groups):
        rivals = [other.support for pos, other in enumerate(groups) if pos != index]
        strongest_rival = max(rivals) if rivals else 0.0
        share = group.support / (group.support + strongest_rival) if group.support + strongest_rival else 1.0
        group.confidence = round(group.support * (0.5 + 0.5 * share), 4)

    if hint:
        hinted = next((group for group in groups if manufacturer_similarity(hint, group.manufacturer) >= 0.75), None)
        leader = groups[0]
        if hinted is not None and hinted is not leader and hinted.support >= 0.35 and hinted.support >= 0.5 * leader.support:
            groups.remove(hinted)
            groups.insert(0, hinted)
        if hinted is not None and hinted is groups[0]:
            # Подсказка оператора, подтверждённая независимыми источниками, — сильный априорный признак
            hinted.confidence = round(max(hinted.confidence, 1.0 - (1.0 - hinted.support) * 0.75), 4)
    groups[1:] = sorted(groups[1:], key=lambda group: group.confidence, reverse=True)
    return groups


__all__ = [
    "CandidateScore",
    "Evidence",
    "SearchHit",
    "aggregate_evidence",
    "clean_candidate_name",
    "evidence_from_document",
    "evidence_from_hit",
    "rank_candidates",
]
