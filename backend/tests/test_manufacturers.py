import pytest

from app.services.manufacturers import (
    evaluate_match,
    find_manufacturer_mentions,
    is_distributor,
    manufacturer_from_slug,
    manufacturer_from_url,
    manufacturer_info_from_dictionary,
    manufacturer_similarity,
    normalize_manufacturer_name,
    part_number_key,
    part_number_strength,
    query_part_number,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("TI", "Texas Instruments"),
        ("texas instrument", "Texas Instruments"),
        ("Сибеко", "Sibeco"),
        ("СИБЕКО", "Sibeco"),
        ("Тесто", "Testo"),
        ("ON Semiconductor", "onsemi"),
        ("意法半导体公司", "STMicroelectronics"),
        ("Analog Devices, Inc.", "Analog Devices"),
        ("Infinion", "Infineon Technologies"),
        ("Murata Electronics", "Murata Manufacturing"),
        ("NXP USA Inc", "NXP Semiconductors"),
        ("Unknown Brand GmbH", "Unknown Brand GmbH"),
        ("Texas Nuts Company", "Texas Nuts Company"),
        ("", ""),
    ],
)
def test_normalize_manufacturer_name(raw, expected):
    assert normalize_manufacturer_name(raw) == expected


def test_similarity_and_match_status():
    assert evaluate_match("TI", "Texas Instruments") == ("matched", 1.0)
    # Кириллическая подсказка раньше давала «расхождение»
    assert evaluate_match("Сибеко", "Sibeco")[0] == "matched"
    assert evaluate_match("Linear Technology", "Analog Devices")[0] == "matched"
    assert evaluate_match("ST", "onsemi")[0] == "mismatch"
    assert evaluate_match("Тест-Про", "Test-Pro")[0] == "matched"
    assert evaluate_match(None, "Texas Instruments") == (None, None)
    assert evaluate_match("TI", None) == ("pending", None)
    assert manufacturer_similarity("Testo SE & Co. KGaA", "Testo") >= 0.75


def test_mentions_respect_word_boundaries():
    text = "Intelligent design. LM317T STMicroelectronics | Mouser; sick day; SICK sensor; microchip vs Microchip PIC"
    names = [mention.canonical for mention in find_manufacturer_mentions(text)]
    assert "Intel" not in names
    assert names.count("SICK") == 1
    assert names.count("Microchip Technology") == 1
    assert "STMicroelectronics" in names


@pytest.mark.parametrize(
    ("part", "text", "expected"),
    [
        ("LM317T", "LM317T Datasheet", 1.0),
        ("LM317T", "lm317t-dg regulator", 1.0),
        ("LM317T", "LM317TG", 0.75),
        ("LM317T", "LM317 regulator", 0.5),
        ("LM317T", "XLM317T", 0.0),
        ("0560-0001", "NSN 5935-0560-0001", 0.0),
        ("0560-0001", "P/N 0560 0001", 1.0),
        ("6 030 646", "part 6030646", 1.0),
        ("КМ1234", "KM1234 relay", 1.0),
        ("STM32F103C8T6", "STM32F103 family", 0.5),
        ("ABC123", "", 0.0),
    ],
)
def test_part_number_strength(part, text, expected):
    assert part_number_strength(part, text) == expected


def test_part_number_helpers():
    assert part_number_key(" lm-317.t ") == "LM317T"
    assert query_part_number("КM1234") == "KM1234"  # смешанная раскладка
    assert query_part_number("К155ЛА3") == "К155ЛА3"  # настоящий кириллический артикул не трогаем


def test_url_helpers():
    assert manufacturer_from_url("https://www.ti.com/lit/ds/symlink/lm317.pdf") == "Texas Instruments"
    assert manufacturer_from_url("https://notti.com/x") is None
    assert manufacturer_from_url("https://semiconductor.samsung.com/x") == "Samsung"
    assert is_distributor("https://www.digikey.com/en/products")
    assert not is_distributor("https://www.st.com")
    assert manufacturer_from_slug("nxp-usa-inc") == "NXP Semiconductors"
    assert manufacturer_from_slug("texas-instruments") == "Texas Instruments"
    assert manufacturer_from_slug("on-shore-technology-inc") is None
    assert manufacturer_from_slug("st") is None


def test_dictionary_info():
    info = manufacturer_info_from_dictionary("TI")
    assert info["country"] == "США"
    assert info["website"] == "https://www.ti.com"
    assert manufacturer_info_from_dictionary("Unknown Brand") == {}
