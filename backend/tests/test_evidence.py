from app.services.evidence import SearchHit, evidence_from_document, evidence_from_hit, rank_candidates

LM317T_HITS = [
    SearchHit("https://www.ti.com/lit/ds/symlink/lm317.pdf", "LM317 3-Pin Adjustable Regulator datasheet", "The LM317 ...", rank=0),
    SearchHit(
        "https://www.digikey.com/en/products/detail/stmicroelectronics/LM317T/591677",
        "LM317T STMicroelectronics | Voltage Regulators - Linear | DigiKey",
        "Buy now. LM317T - Linear Voltage Regulator IC from STMicroelectronics",
        rank=1,
    ),
    SearchHit("https://www.alldatasheet.com/datasheet-pdf/pdf/22754/STMICROELECTRONICS/LM317T.html",
              "LM317T Datasheet (PDF) - STMicroelectronics", "LM317T Datasheet", rank=2),
    SearchHit("https://www.st.com/resource/en/datasheet/lm317.pdf", "Datasheet - LM217, LM317", "", rank=3),
    SearchHit("https://www.mouser.com/ProductDetail/Texas-Instruments/LM317T", "LM317T Texas Instruments | Mouser", "", rank=4),
]


def _evidence(hits, part, hint=None):
    items = []
    for hit in hits:
        items.extend(evidence_from_hit(hit, part, hint))
    return items


def test_multi_source_part_is_ambiguous_without_hint():
    ranked = rank_candidates(_evidence(LM317T_HITS, "LM317T"))
    names = [candidate.manufacturer for candidate in ranked]
    assert names[:2] == ["STMicroelectronics", "Texas Instruments"]
    assert ranked[0].confidence < 0.8  # два реальных производителя — уверенность снижена
    assert all("Datasheet" not in name for name in names)


def test_operator_hint_breaks_the_tie():
    ranked = rank_candidates(_evidence(LM317T_HITS, "LM317T", "TI"), "TI")
    assert ranked[0].manufacturer == "Texas Instruments"
    assert ranked[0].confidence >= 0.9
    ranked = rank_candidates(_evidence(LM317T_HITS, "LM317T", "ST"), "ST")
    assert ranked[0].manufacturer == "STMicroelectronics"


def test_hint_without_evidence_is_ignored():
    ranked = rank_candidates(_evidence(LM317T_HITS, "LM317T", "Sibeco"), "Sibeco")
    assert ranked[0].manufacturer != "Sibeco"


def test_official_domain_without_part_number_is_weak():
    evidence = evidence_from_hit(SearchHit("https://www.ti.com/", "Texas Instruments home", "", rank=5), "XYZ123")
    assert evidence == []
    evidence = evidence_from_hit(SearchHit("https://www.ti.com/", "Texas Instruments home", "", rank=0), "XYZ123")
    assert len(evidence) == 1 and evidence[0].weight < 0.2


def test_poisoned_results_give_no_evidence():
    junk = [SearchHit("https://www.walmart.com/", "Walmart | Save Money", "Shop Walmart.com today", rank=i) for i in range(5)]
    assert _evidence(junk, "STM32F103C8T6") == []


def test_unknown_manufacturer_from_label_and_hint():
    hits = [
        SearchHit("https://shop.example.ru/item/0563-1234", "Зонд 0563-1234 купить", "Производитель: Сибеко. Артикул 0563-1234", rank=0),
        SearchHit("https://another.example.com/p/0563-1234", "0563-1234 probe", "Brand: Sibeco", rank=1),
    ]
    ranked = rank_candidates(_evidence(hits, "0563-1234", "Сибеко"), "Сибеко")
    assert ranked[0].manufacturer == "Sibeco"


def test_document_copyright_evidence():
    text = "LM317 datasheet\nLM317T adjustable regulator\n" + "x\n" * 50 + "© 2016, Texas Instruments Incorporated"
    evidence = evidence_from_document("https://www.alldatasheet.com/doc.pdf", text, "LM317T")
    kinds = {(item.manufacturer, item.kind) for item in evidence}
    assert ("Texas Instruments", "doc-copyright") in kinds
    assert evidence_from_document("https://example.com", "nothing relevant", "LM317T") == []


def test_candidate_name_cleanup():
    from app.services.evidence import clean_candidate_name

    assert clean_candidate_name("Copyright 2026 AeroBase Group") == "AeroBase Group"
    assert clean_candidate_name("© 2016, Texas Instruments Incorporated") == "Texas Instruments"
    assert clean_candidate_name("ООО Ромашка. К155ЛА3") == "ООО Ромашка"
    assert clean_candidate_name("St. Louis Micro") is None  # не превращаем "St" в STMicroelectronics
    assert clean_candidate_name("NXP") == "NXP Semiconductors"
    assert clean_candidate_name("Datasheet (PDF)") is None
