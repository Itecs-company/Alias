"""Справочник производителей и утилиты сопоставления названий и артикулов.

Модуль не выполняет сетевых запросов и не обращается к БД: здесь собраны
чистые функции, которые используются поисковым движком и легко тестируются.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import unquote, urlparse

from rapidfuzz import fuzz, process


@dataclass(frozen=True)
class ManufacturerEntry:
    canonical: str
    country: str | None = None
    produces: str | None = None
    domains: tuple[str, ...] = ()
    # Надёжные названия: используются и для нормализации, и для поиска в тексте
    aliases: tuple[str, ...] = ()
    # Ищутся в тексте только с точным регистром (SICK, SMC, JST ...)
    case_sensitive: tuple[str, ...] = ()
    # Сокращения, которые опасно искать в тексте (TI, ST, ON ...), только для нормализации
    normalize_only: tuple[str, ...] = ()
    parent: str | None = None


def _m(
    canonical: str,
    country: str | None = None,
    produces: str | None = None,
    domains: tuple[str, ...] | list[str] = (),
    aliases: tuple[str, ...] | list[str] = (),
    cs: tuple[str, ...] | list[str] = (),
    norm: tuple[str, ...] | list[str] = (),
    parent: str | None = None,
) -> ManufacturerEntry:
    return ManufacturerEntry(
        canonical=canonical,
        country=country,
        produces=produces,
        domains=tuple(domains),
        aliases=tuple(aliases),
        case_sensitive=tuple(cs),
        normalize_only=tuple(norm),
        parent=parent,
    )


MANUFACTURERS: tuple[ManufacturerEntry, ...] = (
    # --- Полупроводники -------------------------------------------------------
    _m("Texas Instruments", "США", "Аналоговые и встраиваемые микросхемы", ["ti.com", "texasinstruments.com"],
       ["Texas Instruments", "Texas Instruments Incorporated", "德州仪器", "テキサス・インスツルメンツ",
        "텍사스 인스트루먼트", "Техас Инструментс"], norm=["TI", "Texas"]),
    _m("National Semiconductor", "США", "Аналоговые микросхемы", ["national.com"], ["National Semiconductor"],
       norm=["NSC"], parent="Texas Instruments"),
    _m("Burr-Brown", "США", "Прецизионные аналоговые микросхемы", [], ["Burr-Brown", "Burr Brown"],
       parent="Texas Instruments"),
    _m("Analog Devices", "США", "Аналоговые, смешанные и DSP микросхемы", ["analog.com", "adi.com"],
       ["Analog Devices", "Analog Devices Inc", "亚德诺半导体", "アナログ・デバイセズ", "아날로그 디바이스"], norm=["ADI"]),
    _m("Linear Technology", "США", "Аналоговые микросхемы и микросхемы питания", ["linear.com"],
       ["Linear Technology"], norm=["LTC"], parent="Analog Devices"),
    _m("Maxim Integrated", "США", "Аналоговые и смешанные микросхемы", ["maximintegrated.com", "maxim-ic.com"],
       ["Maxim Integrated", "Maxim Integrated Products", "美信半導體", "マキシム"], norm=["Maxim", "美信", "맥심"],
       parent="Analog Devices"),
    _m("STMicroelectronics", "Швейцария", "Микроконтроллеры, силовые и аналоговые полупроводники", ["st.com"],
       ["STMicroelectronics", "ST Microelectronics", "意法半导体", "意法半導體", "エスティーマイクロエレクトロニクス",
        "에스티마이크로일렉트로닉스"], norm=["ST", "STM", "SGS-Thomson", "SGS Thomson", "ST Micro"]),
    _m("Microchip Technology", "США", "Микроконтроллеры, память, аналоговые микросхемы", ["microchip.com"],
       ["Microchip Technology", "Microchip Technology Inc", "微芯科技", "微芯科技公司", "マイクロチップ", "마이크로칩"],
       cs=["Microchip"], norm=["MCHP"]),
    _m("Atmel", "США", "Микроконтроллеры и память", ["atmel.com"], ["Atmel"], parent="Microchip Technology"),
    _m("Microsemi", "США", "Силовые, FPGA и аэрокосмические компоненты", ["microsemi.com"], ["Microsemi"],
       parent="Microchip Technology"),
    _m("NXP Semiconductors", "Нидерланды", "Микроконтроллеры, автомобильная и RF электроника", ["nxp.com", "nxp.com.cn"],
       ["NXP Semiconductors", "NXP", "恩智浦", "恩智浦半導體", "エヌエックスピー", "엔엑스피"]),
    _m("Freescale Semiconductor", "США", "Микроконтроллеры и процессоры", ["freescale.com"],
       ["Freescale Semiconductor", "Freescale"], parent="NXP Semiconductors"),
    _m("Infineon Technologies", "Германия", "Силовые полупроводники, микроконтроллеры, датчики", ["infineon.com"],
       ["Infineon Technologies", "Infineon", "英飞凌", "英飛凌", "インフィニオン", "인피니언"]),
    _m("International Rectifier", "США", "Силовые полупроводники", ["irf.com"], ["International Rectifier"],
       norm=["IR"], parent="Infineon Technologies"),
    _m("Cypress Semiconductor", "США", "Микроконтроллеры, память, USB-контроллеры", ["cypress.com"],
       ["Cypress Semiconductor"], norm=["Cypress"], parent="Infineon Technologies"),
    _m("onsemi", "США", "Силовые и аналоговые полупроводники, датчики изображения", ["onsemi.com", "onsemi.cn", "onsemi.jp"],
       ["onsemi", "ON Semiconductor", "ON Semi", "安森美", "安森美半導體", "オン・セミコンダクター", "온세미"], norm=["ON"]),
    _m("Fairchild Semiconductor", "США", "Дискретные и силовые полупроводники", ["fairchildsemi.com"],
       ["Fairchild Semiconductor", "Fairchild"], parent="onsemi"),
    _m("Renesas Electronics", "Япония", "Микроконтроллеры, SoC, аналоговые микросхемы", ["renesas.com"],
       ["Renesas Electronics", "Renesas", "瑞萨电子", "瑞薩電子", "ルネサスエレクトロニクス", "르네사스"]),
    _m("Intersil", "США", "Аналоговые микросхемы и микросхемы питания", ["intersil.com"], ["Intersil"],
       parent="Renesas Electronics"),
    _m("Integrated Device Technology", "США", "Тактирование, интерфейсы, RF", ["idt.com"],
       ["Integrated Device Technology"], cs=["IDT"], parent="Renesas Electronics"),
    _m("Vishay Intertechnology", "США", "Дискретные полупроводники и пассивные компоненты", ["vishay.com"],
       ["Vishay Intertechnology", "Vishay", "Vishay Siliconix", "Vishay Semiconductors", "Vishay Dale",
        "Vishay Sprague", "威世", "威世半導體", "ヴィシェイ", "비셰이"]),
    _m("Diodes Incorporated", "США", "Дискретные и аналоговые полупроводники", ["diodes.com"],
       ["Diodes Incorporated", "Diodes Inc", "Diodes Inc."], norm=["Diodes"]),
    _m("Nexperia", "Нидерланды", "Дискретные полупроводники и логика", ["nexperia.com", "nexperia.com.cn"], ["Nexperia"]),
    _m("ROHM Semiconductor", "Япония", "Дискретные полупроводники, пассивные компоненты, микросхемы", ["rohm.com", "rohm.co.jp"],
       ["ROHM Semiconductor", "ROHM", "罗姆", "羅姆半導體", "ローム"], norm=["롬"]),
    _m("Toshiba", "Япония", "Полупроводники, накопители, электроника",
       ["toshiba.com", "toshiba.co.jp", "toshiba-semicon-storage.com"],
       ["Toshiba", "Toshiba Electronic Devices & Storage", "东芝", "東芝"]),
    _m("Broadcom", "США", "Сетевые, RF и оптоэлектронные компоненты", ["broadcom.com"],
       ["Broadcom", "Avago Technologies", "Avago", "博通", "博通公司", "ブロードコム", "브로드컴"]),
    _m("Semtech", "США", "Аналоговые и смешанные микросхемы, LoRa", ["semtech.com"], ["Semtech"]),
    _m("Samsung", "Южная Корея", "Память, полупроводники, электроника",
       ["samsung.com", "semiconductor.samsung.com", "samsungsem.com"],
       ["Samsung", "Samsung Electronics", "Samsung Semiconductor", "Samsung Electro-Mechanics", "三星", "三星電子",
        "サムスン", "삼성"]),
    _m("SK hynix", "Южная Корея", "Память DRAM и NAND", ["skhynix.com"], ["SK hynix", "SK Hynix", "Hynix"]),
    _m("Micron Technology", "США", "Память DRAM и NAND", ["micron.com"], ["Micron Technology"], cs=["Micron"]),
    _m("Intel", "США", "Процессоры, FPGA, чипсеты", ["intel.com"], ["Intel", "Intel Corporation", "英特尔"]),
    _m("Altera", "США", "FPGA", ["altera.com"], ["Altera"], parent="Intel"),
    _m("AMD", "США", "Процессоры, GPU, FPGA", ["amd.com"], ["Advanced Micro Devices", "AMD"]),
    _m("Xilinx", "США", "FPGA и адаптивные SoC", ["xilinx.com"], ["Xilinx"], parent="AMD"),
    _m("Lattice Semiconductor", "США", "FPGA", ["latticesemi.com"], ["Lattice Semiconductor"], norm=["Lattice"]),
    _m("Silicon Labs", "США", "Беспроводные SoC, микроконтроллеры, изоляторы", ["silabs.com"],
       ["Silicon Labs", "Silicon Laboratories"], norm=["SiLabs"]),
    _m("Nordic Semiconductor", "Норвегия", "Беспроводные SoC (Bluetooth LE, Thread)", ["nordicsemi.com"],
       ["Nordic Semiconductor"], norm=["Nordic"]),
    _m("Espressif Systems", "Китай", "Wi-Fi/Bluetooth SoC и модули", ["espressif.com", "espressif.com.cn"],
       ["Espressif Systems", "Espressif", "乐鑫"]),
    _m("Qualcomm", "США", "Мобильные SoC и модемы", ["qualcomm.com"], ["Qualcomm", "高通"]),
    _m("MediaTek", "Тайвань", "SoC для мобильных и потребительских устройств", ["mediatek.com"], ["MediaTek", "联发科"]),
    _m("Realtek Semiconductor", "Тайвань", "Сетевые и аудио микросхемы", ["realtek.com"],
       ["Realtek Semiconductor", "Realtek", "瑞昱"]),
    _m("Winbond Electronics", "Тайвань", "Флеш-память и DRAM", ["winbond.com"], ["Winbond Electronics", "Winbond", "华邦"]),
    _m("Macronix", "Тайвань", "Флеш-память", ["macronix.com"], ["Macronix", "旺宏"]),
    _m("Integrated Silicon Solution", "США", "Память SRAM/DRAM/Flash", ["issi.com"],
       ["Integrated Silicon Solution"], cs=["ISSI"]),
    _m("GigaDevice", "Китай", "Флеш-память и микроконтроллеры", ["gigadevice.com", "gigadevice.com.cn"],
       ["GigaDevice", "兆易创新"]),
    _m("Allegro MicroSystems", "США", "Датчики тока и Холла, драйверы двигателей", ["allegromicro.com"],
       ["Allegro MicroSystems", "Allegro Microsystems"], norm=["Allegro"]),
    _m("Power Integrations", "США", "Микросхемы для источников питания", ["power.com"], ["Power Integrations"]),
    _m("Monolithic Power Systems", "США", "Микросхемы управления питанием", ["monolithicpower.com"],
       ["Monolithic Power Systems"], norm=["MPS"]),
    _m("Richtek Technology", "Тайвань", "Микросхемы управления питанием", ["richtek.com"],
       ["Richtek Technology", "Richtek"]),
    _m("Skyworks Solutions", "США", "RF микросхемы", ["skyworksinc.com"], ["Skyworks Solutions", "Skyworks"]),
    _m("Qorvo", "США", "RF компоненты", ["qorvo.com"], ["Qorvo"]),
    _m("Mini-Circuits", "США", "RF и СВЧ компоненты", ["minicircuits.com"], ["Mini-Circuits", "Mini Circuits"]),
    _m("Wolfspeed", "США", "SiC и GaN полупроводники", ["wolfspeed.com"], ["Wolfspeed"], norm=["Cree"]),
    _m("Littelfuse", "США", "Предохранители и защитные компоненты", ["littelfuse.com"], ["Littelfuse", "IXYS"]),
    _m("Alpha & Omega Semiconductor", "США", "MOSFET и силовые микросхемы", ["aosmd.com"],
       ["Alpha & Omega Semiconductor", "Alpha and Omega Semiconductor"], cs=["AOS"]),
    _m("Taiwan Semiconductor", "Тайвань", "Дискретные полупроводники", ["taiwansemi.com"], ["Taiwan Semiconductor"]),
    _m("Central Semiconductor", "США", "Дискретные полупроводники", ["centralsemi.com"], ["Central Semiconductor"]),
    _m("Micro Commercial Components", "США", "Дискретные полупроводники", ["mccsemi.com"],
       ["Micro Commercial Components"]),
    _m("Panjit", "Тайвань", "Дискретные полупроводники", ["panjit.com.tw", "pan-jit.com"], ["Panjit"]),
    _m("Melexis", "Бельгия", "Автомобильные датчики и микросхемы", ["melexis.com"], ["Melexis"]),
    _m("Nuvoton Technology", "Тайвань", "Микроконтроллеры", ["nuvoton.com"], ["Nuvoton Technology", "Nuvoton"]),
    _m("Holtek Semiconductor", "Тайвань", "Микроконтроллеры", ["holtek.com"], ["Holtek Semiconductor", "Holtek"]),
    _m("Torex Semiconductor", "Япония", "Микросхемы питания", ["torexsemi.com"], ["Torex Semiconductor"],
       norm=["Torex"]),
    _m("ABLIC", "Япония", "Аналоговые микросхемы", ["ablic.com"], ["ABLIC", "Seiko Instruments"]),
    _m("Mitsubishi Electric", "Япония", "Силовые модули, автоматизация", ["mitsubishielectric.com"],
       ["Mitsubishi Electric", "三菱电机", "三菱電機"]),
    _m("Fuji Electric", "Япония", "Силовые полупроводники, автоматизация", ["fujielectric.com"], ["Fuji Electric"]),
    _m("Semikron Danfoss", "Германия", "Силовые модули", ["semikron-danfoss.com", "semikron.com"],
       ["Semikron Danfoss", "Semikron", "SEMIKRON"]),
    _m("Sony", "Япония", "Датчики изображения, электроника", ["sony.com", "sony-semicon.com", "sony.net"],
       ["Sony Semiconductor Solutions", "Sony"]),
    _m("ams OSRAM", "Австрия", "Оптоэлектроника и датчики", ["ams-osram.com", "osram.com", "ams.com"],
       ["ams OSRAM", "OSRAM", "Osram Opto Semiconductors"], norm=["ams"]),
    _m("Nichia", "Япония", "Светодиоды", ["nichia.co.jp"], ["Nichia"]),
    _m("Lumileds", "Нидерланды", "Светодиоды", ["lumileds.com"], ["Lumileds"]),
    _m("Lite-On", "Тайвань", "Оптоэлектроника и источники питания", ["liteon.com"], ["Lite-On", "LITE-ON", "Liteon"]),
    _m("Everlight Electronics", "Тайвань", "Светодиоды и оптроны", ["everlight.com"],
       ["Everlight Electronics", "Everlight"]),
    _m("Kingbright", "Тайвань", "Светодиоды", ["kingbright.com", "kingbrightusa.com"], ["Kingbright"]),
    _m("Sensirion", "Швейцария", "Датчики влажности, газа и расхода", ["sensirion.com"], ["Sensirion"]),
    _m("u-blox", "Швейцария", "GNSS и сотовые модули", ["u-blox.com"], ["u-blox"]),
    _m("Quectel", "Китай", "Сотовые и GNSS модули", ["quectel.com"], ["Quectel"]),
    _m("SIMCom", "Китай", "Сотовые модули", ["simcom.com"], ["SIMCom"]),
    _m("Seiko Epson", "Япония", "Кварцевые генераторы, микроконтроллеры, принтеры",
       ["epson.com", "epsondevice.com", "global.epson.com", "epson.jp"], ["Seiko Epson", "Epson"]),
    _m("Abracon", "США", "Кварцевые резонаторы и генераторы", ["abracon.com"], ["Abracon"]),
    _m("SiTime", "США", "MEMS генераторы", ["sitime.com"], ["SiTime"]),
    _m("Kingston Technology", "США", "Модули памяти и накопители", ["kingston.com"], ["Kingston Technology"],
       norm=["Kingston"]),
    _m("Western Digital", "США", "Накопители", ["westerndigital.com", "wd.com"], ["Western Digital"]),
    _m("Seagate Technology", "США", "Накопители", ["seagate.com"], ["Seagate Technology", "Seagate"]),
    # --- Пассивные компоненты --------------------------------------------------
    _m("Panasonic", "Япония", "Электронные компоненты и электроника",
       ["panasonic.com", "panasonic.jp", "panasonic.net", "panasonic.eu"], ["Panasonic", "松下"]),
    _m("Murata Manufacturing", "Япония", "Конденсаторы, фильтры, RF модули", ["murata.com"],
       ["Murata Manufacturing", "Murata Electronics", "Murata", "村田"]),
    _m("TDK", "Япония", "Пассивные компоненты, датчики, источники питания", ["tdk.com", "tdk-lambda.com"],
       ["TDK Corporation", "TDK", "TDK-Lambda"]),
    _m("EPCOS", "Германия", "Пассивные компоненты", ["epcos.com"], ["EPCOS"], parent="TDK"),
    _m("Yageo", "Тайвань", "Резисторы и конденсаторы", ["yageo.com"], ["Yageo", "国巨"]),
    _m("KEMET", "США", "Конденсаторы", ["kemet.com"], ["KEMET", "Kemet"], parent="Yageo"),
    _m("Kyocera AVX", "США", "Конденсаторы и коннекторы", ["kyocera-avx.com", "avx.com"],
       ["Kyocera AVX", "AVX Corporation"], cs=["AVX"]),
    _m("Kyocera", "Япония", "Керамика, электронные компоненты", ["kyocera.com", "kyocera.co.jp"], ["Kyocera"]),
    _m("Taiyo Yuden", "Япония", "Конденсаторы и индуктивности", ["yuden.co.jp", "t-yuden.com"], ["Taiyo Yuden"]),
    _m("Nichicon", "Япония", "Конденсаторы", ["nichicon.co.jp", "nichicon.com"], ["Nichicon"]),
    _m("Rubycon", "Япония", "Конденсаторы", ["rubycon.co.jp"], ["Rubycon"]),
    _m("Bourns", "США", "Резисторы, защитные компоненты, датчики", ["bourns.com"], ["Bourns"]),
    _m("Ohmite", "США", "Резисторы", ["ohmite.com"], ["Ohmite"]),
    _m("Susumu", "Япония", "Прецизионные резисторы", ["susumu.co.jp"], ["Susumu"]),
    _m("Stackpole Electronics", "США", "Резисторы", ["seielect.com"], ["Stackpole Electronics", "Stackpole"]),
    _m("Würth Elektronik", "Германия", "Пассивные компоненты и коннекторы", ["we-online.com", "we-online.de"],
       ["Würth Elektronik", "Wurth Elektronik", "Wuerth Elektronik", "Wurth Electronics", "Würth"]),
    _m("Coilcraft", "США", "Индуктивности", ["coilcraft.com"], ["Coilcraft"]),
    # --- Коннекторы и электромеханика -------------------------------------------
    _m("Molex", "США", "Коннекторы", ["molex.com"], ["Molex"]),
    _m("TE Connectivity", "Швейцария", "Коннекторы и датчики", ["te.com"],
       ["TE Connectivity", "Tyco Electronics", "AMP Incorporated"], norm=["TE", "Tyco", "AMP"]),
    _m("Amphenol", "США", "Коннекторы и кабели", ["amphenol.com"], ["Amphenol"]),
    _m("Hirose Electric", "Япония", "Коннекторы", ["hirose.com"], ["Hirose Electric", "Hirose"]),
    _m("JST", "Япония", "Коннекторы", ["jst-mfg.com", "jst.com"], ["J.S.T. Mfg", "JST Mfg"], cs=["JST"]),
    _m("Samtec", "США", "Коннекторы", ["samtec.com"], ["Samtec"]),
    _m("Harwin", "Великобритания", "Коннекторы", ["harwin.com"], ["Harwin"]),
    _m("C&K", "США", "Переключатели", ["ckswitches.com"], ["C&K Components", "C&K Switches"]),
    _m("E-Switch", "США", "Переключатели", ["e-switch.com"], ["E-Switch"]),
    _m("Alps Alpine", "Япония", "Переключатели, энкодеры, датчики", ["alpsalpine.com"],
       ["Alps Alpine", "Alps Electric"], cs=["ALPS"]),
    _m("Omron", "Япония", "Реле, датчики, автоматизация", ["omron.com"], ["Omron", "OMRON", "欧姆龙", "オムロン"]),
    _m("Finder", "Италия", "Реле", ["findernet.com"], ["Finder Relays"], norm=["Finder"]),
    _m("Hongfa", "Китай", "Реле", ["hongfa.com"], ["Hongfa", "宏发"]),
    _m("Phoenix Contact", "Германия", "Клеммы, коннекторы, автоматизация", ["phoenixcontact.com"], ["Phoenix Contact"]),
    _m("WAGO", "Германия", "Клеммы и автоматизация", ["wago.com"], ["WAGO", "Wago"]),
    _m("Weidmüller", "Германия", "Клеммы и коннекторы", ["weidmueller.com"], ["Weidmüller", "Weidmuller", "Weidmueller"]),
    _m("HARTING", "Германия", "Промышленные коннекторы", ["harting.com"], ["HARTING", "Harting"]),
    _m("LAPP", "Германия", "Кабели и кабельные вводы", ["lapp.com", "lappgroup.com"], ["LAPP", "Lapp Kabel", "U.I. Lapp"]),
    _m("Belden", "США", "Кабели", ["belden.com"], ["Belden"]),
    _m("3M", "США", "Промышленные материалы и компоненты", ["3m.com"], cs=["3M"]),
    # --- Источники питания -----------------------------------------------------
    _m("Mean Well", "Тайвань", "Источники питания", ["meanwell.com", "meanwell.com.tw", "meanwell.ru"],
       ["Mean Well", "MEAN WELL", "Meanwell", "明纬"]),
    _m("RECOM", "Австрия", "DC/DC преобразователи", ["recom-power.com"], ["RECOM Power", "Recom"]),
    _m("TRACO Power", "Швейцария", "Источники питания", ["tracopower.com"], ["TRACO Power", "Traco Power", "Traco"]),
    _m("Delta Electronics", "Тайвань", "Источники питания, вентиляторы, автоматизация", ["deltaww.com"],
       ["Delta Electronics"], norm=["Delta"]),
    # --- Промышленная автоматизация и электротехника ----------------------------
    _m("Schneider Electric", "Франция", "Электротехника и автоматизация", ["se.com", "schneider-electric.com"],
       ["Schneider Electric"], norm=["Schneider"]),
    _m("Siemens", "Германия", "Автоматизация и электротехника", ["siemens.com"], ["Siemens"]),
    _m("ABB", "Швейцария", "Электротехника и автоматизация", ["abb.com"], ["ABB"]),
    _m("Eaton", "Ирландия", "Электротехника и силовое оборудование", ["eaton.com"], ["Eaton"]),
    _m("Legrand", "Франция", "Электроустановочные изделия", ["legrand.com", "legrand.ru"], ["Legrand"]),
    _m("Honeywell", "США", "Датчики и автоматизация", ["honeywell.com"], ["Honeywell"]),
    _m("Festo", "Германия", "Пневматика и автоматизация", ["festo.com"], ["Festo"]),
    _m("SMC Corporation", "Япония", "Пневматика", ["smcworld.com", "smc.eu", "smcusa.com"], ["SMC Corporation"],
       cs=["SMC"]),
    _m("Pepperl+Fuchs", "Германия", "Датчики и взрывозащищённое оборудование", ["pepperl-fuchs.com"],
       ["Pepperl+Fuchs", "Pepperl + Fuchs", "Pepperl Fuchs"]),
    _m("SICK", "Германия", "Промышленные датчики", ["sick.com"], ["SICK AG"], cs=["SICK"]),
    _m("Balluff", "Германия", "Промышленные датчики", ["balluff.com"], ["Balluff"]),
    _m("ifm electronic", "Германия", "Промышленные датчики", ["ifm.com"], ["ifm electronic"], cs=["ifm"]),
    _m("Keyence", "Япония", "Датчики и измерительные системы", ["keyence.com", "keyence.co.jp"], ["Keyence", "キーエンス"]),
    _m("Autonics", "Южная Корея", "Датчики и контроллеры", ["autonics.com"], ["Autonics"]),
    _m("Rittal", "Германия", "Электротехнические шкафы", ["rittal.com"], ["Rittal"]),
    _m("Hammond Manufacturing", "Канада", "Корпуса и трансформаторы", ["hammfg.com", "hammondmfg.com"],
       ["Hammond Manufacturing"], norm=["Hammond"]),
    _m("Bosch", "Германия", "Датчики, автокомпоненты, инструмент",
       ["bosch.com", "bosch-sensortec.com", "bosch-professional.com"], ["Bosch", "Robert Bosch", "Bosch Sensortec", "博世"]),
    _m("Bosch Rexroth", "Германия", "Гидравлика и приводы", ["boschrexroth.com"], ["Bosch Rexroth", "Rexroth"],
       parent="Bosch"),
    _m("Danfoss", "Дания", "Приводы, компрессоры, гидравлика", ["danfoss.com"], ["Danfoss"]),
    _m("Grundfos", "Дания", "Насосы", ["grundfos.com"], ["Grundfos"]),
    _m("Parker Hannifin", "США", "Гидравлика и пневматика", ["parker.com"], ["Parker Hannifin"], norm=["Parker"]),
    _m("maxon", "Швейцария", "Электродвигатели", ["maxongroup.com"], ["maxon motor", "Maxon Motor"], norm=["Maxon"]),
    _m("Nidec", "Япония", "Электродвигатели", ["nidec.com"], ["Nidec"]),
    _m("SKF", "Швеция", "Подшипники", ["skf.com"], ["SKF"]),
    _m("Schaeffler", "Германия", "Подшипники (FAG, INA)", ["schaeffler.com"], ["Schaeffler"], norm=["FAG", "INA"]),
    _m("NSK", "Япония", "Подшипники", ["nsk.com"], cs=["NSK"]),
    _m("Timken", "США", "Подшипники", ["timken.com"], ["Timken"]),
    # --- Инструмент и измерения -------------------------------------------------
    _m("Fluke", "США", "Измерительные приборы", ["fluke.com"], ["Fluke", "Fluke Corporation"]),
    _m("Keysight Technologies", "США", "Измерительное оборудование", ["keysight.com"],
       ["Keysight Technologies", "Keysight"]),
    _m("Agilent Technologies", "США", "Аналитическое оборудование", ["agilent.com"], ["Agilent Technologies", "Agilent"]),
    _m("Tektronix", "США", "Осциллографы и измерительное оборудование", ["tek.com"], ["Tektronix"]),
    _m("Rohde & Schwarz", "Германия", "Измерительное и радиооборудование", ["rohde-schwarz.com"],
       ["Rohde & Schwarz", "Rohde and Schwarz", "Rohde-Schwarz"], norm=["R&S"]),
    _m("Testo", "Германия", "Измерительные приборы",
       ["testo.com", "testo.ru", "testo.de", "testo.co.uk", "testodirect.co.uk"], ["Testo"], norm=["Тесто"]),
    _m("Makita", "Япония", "Электроинструмент", ["makita.com", "makita.co.jp", "makita.ru"], ["Makita"]),
    _m("Hilti", "Лихтенштейн", "Строительный инструмент", ["hilti.com", "hilti.ru"], ["Hilti"]),
    _m("Knipex", "Германия", "Ручной инструмент", ["knipex.com", "knipex.de"], ["Knipex"]),
    _m("Wiha", "Германия", "Ручной инструмент", ["wiha.com"], ["Wiha"]),
    # --- Российские производители ------------------------------------------------
    _m("Sibeco", "Россия", None, ["sibeco.net", "sibeco-russia.ru"], ["Sibeco", "СИБЕКО", "Сибеко", "Сибэко"],
       norm=["Сибеко Россия"]),
    _m("IEK", "Россия", "Электротехническая продукция", ["iek.ru", "iek.group"], ["ИЭК"], cs=["IEK"]),
    _m("EKF", "Россия", "Электротехническая продукция", ["ekfgroup.com"], cs=["EKF"]),
    _m("KEAZ", "Россия", "Низковольтная аппаратура", ["keaz.ru"], ["КЭАЗ", "KEAZ"]),
    _m("Milandr", "Россия", "Микросхемы", ["milandr.ru"], ["Миландр", "Milandr"]),
    _m("Angstrem", "Россия", "Микросхемы", ["angstrem.ru"], ["Ангстрем", "Angstrem"]),
    _m("Mikron", "Россия", "Микросхемы и RFID", ["mikron.ru"], ["Mikron", "ПАО Микрон", "АО Микрон"], norm=["Микрон"]),
    _m("OWEN", "Россия", "Средства автоматизации", ["owen.ru"], cs=["ОВЕН", "OWEN"], norm=["Овен"]),
)

# Площадки, которые продают/перепечатывают чужие компоненты: домен не указывает
# на производителя, но заголовки и URL обычно содержат его название.
DISTRIBUTOR_DOMAINS: frozenset[str] = frozenset({
    "digikey.com", "digikey.ru", "digikey.de", "digikey.co.uk", "digikey.cn", "mouser.com", "mouser.ru",
    "mouser.de", "mouser.co.uk", "mouser.cn", "farnell.com", "newark.com", "element14.com", "rs-online.com",
    "rsdelivers.com", "rs-components.com", "arrow.com", "avnet.com", "futureelectronics.com", "tme.eu", "tme.com",
    "lcsc.com", "jlcpcb.com", "octopart.com", "findchips.com", "alldatasheet.com", "alldatasheet.net",
    "datasheetspdf.com", "datasheet4u.com", "datasheetarchive.com", "datasheets.com", "datasheetcatalog.com",
    "alltransistors.com", "chipdip.ru", "platan.ru", "elitan.ru", "promelec.ru", "compel.ru", "efind.ru",
    "chipfind.ru", "electronshik.ru", "eicom.ru", "ozon.ru", "wildberries.ru", "avito.ru", "market.yandex.ru",
    "ebay.com", "aliexpress.com", "aliexpress.ru", "amazon.com", "conrad.com", "conrad.de", "reichelt.de",
    "distrelec.com", "verical.com", "rocelec.com", "utmel.com", "win-source.net", "vseinstrumenti.ru", "etm.ru",
    "elec.ru", "220-volt.ru", "etk-oe.ru", "zip-2002.ru", "voltmaster.ru", "kosmodrom.com.ua", "radiodetali.com",
})

LEGAL_SUFFIXES = (
    "incorporated", "inc", "corporation", "corp", "company", "co", "ltd", "limited", "llc", "gmbh", "ag", "sa",
    "s a", "plc", "oy", "ab", "bv", "b v", "nv", "n v", "kk", "k k", "spa", "s p a", "srl", "as", "a s", "se",
    "ooo", "ооо", "зао", "оао", "пао", "ао", "нпо", "нпп", "group", "holdings",
)

_CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya", "і": "i", "ї": "yi", "є": "ye",
}

# Кириллические буквы, визуально совпадающие с латинскими: операторы часто вводят
# артикулы в русской раскладке ("КМ1234" вместо "KM1234").
_CYRILLIC_LOOKALIKES = str.maketrans({
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
    "Х": "X", "У": "Y", "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p",
    "с": "c", "т": "t", "х": "x", "у": "y",
})

_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")
_WORD_BOUNDARY_LEFT = r"(?<![\w&+])"
_WORD_BOUNDARY_RIGHT = r"(?![\w&+])"


def _is_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def transliterate(text: str) -> str:
    """Транслитерирует кириллицу в латиницу (для сравнения названий)."""
    return "".join(_CYRILLIC_TO_LATIN.get(ch, ch) for ch in text.lower())


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _clean_name(name: str) -> str:
    cleaned = unicodedata.normalize("NFKC", name or "")
    cleaned = cleaned.strip().strip("\"'«»“”„`")
    return re.sub(r"\s+", " ", cleaned).strip(" ,.;:-")


def _name_key(name: str) -> str:
    """Ключ для точного сравнения названий: без регистра, пунктуации и диакритики."""
    base = _strip_accents(_clean_name(name)).lower()
    base = base.replace("&", " and ").replace("+", " and ")
    base = re.sub(r"[^\w]+", " ", base)
    return re.sub(r"\s+", " ", base).strip()


def _strip_legal_suffixes(key: str) -> str:
    words = key.split()
    changed = True
    while changed and len(words) > 1:
        changed = False
        for suffix in LEGAL_SUFFIXES:
            parts = suffix.split()
            if len(words) > len(parts) and words[-len(parts):] == parts:
                words = words[: -len(parts)]
                changed = True
                break
    # Префиксы российских юрлиц: "ООО Ромашка"
    while len(words) > 1 and words[0] in {"ооо", "зао", "оао", "пао", "ао", "нпо", "нпп", "ooo", "zao", "oao", "pao"}:
        words = words[1:]
    return " ".join(words)


@dataclass
class _Index:
    by_key: dict[str, ManufacturerEntry] = field(default_factory=dict)
    by_canonical: dict[str, ManufacturerEntry] = field(default_factory=dict)
    fuzzy_keys: list[str] = field(default_factory=list)
    text_ci: re.Pattern[str] | None = None
    text_cs: re.Pattern[str] | None = None
    text_cjk: re.Pattern[str] | None = None
    text_lookup: dict[str, ManufacturerEntry] = field(default_factory=dict)
    domains: list[tuple[str, ManufacturerEntry]] = field(default_factory=list)
    slug_keys: dict[str, ManufacturerEntry] = field(default_factory=dict)


def _alternation(names: list[str]) -> str:
    return "|".join(re.escape(name) for name in sorted(set(names), key=len, reverse=True))


def _build_index() -> _Index:
    index = _Index()
    ci_names: list[str] = []
    cs_names: list[str] = []
    cjk_names: list[str] = []
    for entry in MANUFACTURERS:
        index.by_canonical[entry.canonical.lower()] = entry
        all_names = (entry.canonical, *entry.aliases, *entry.case_sensitive, *entry.normalize_only)
        for name in all_names:
            key = _name_key(name)
            if key:
                index.by_key.setdefault(key, entry)
                stripped = _strip_legal_suffixes(key)
                if stripped:
                    index.by_key.setdefault(stripped, entry)
        for name in (entry.canonical, *entry.aliases):
            if len(_name_key(name)) >= 4 and not _is_cjk(name):
                index.fuzzy_keys.append(_name_key(name))
        for name in (entry.canonical, *entry.aliases):
            if _is_cjk(name):
                if len(name) >= 2:
                    cjk_names.append(name)
                    index.text_lookup[name] = entry
            elif len(name) >= 3 and name not in entry.case_sensitive:
                ci_names.append(name)
                index.text_lookup[name.lower()] = entry
        for name in entry.case_sensitive:
            cs_names.append(name)
            index.text_lookup["cs:" + name] = entry
        for domain in entry.domains:
            index.domains.append((domain.lower(), entry))
        # Для URL не используем опасные сокращения (normalize_only: TI, ST, ON ...)
        for name in (entry.canonical, *entry.aliases, *entry.case_sensitive):
            if _is_cjk(name):
                continue
            compact = re.sub(r"[^a-z0-9]", "", _name_key(name))
            if len(compact) >= 3:
                index.slug_keys.setdefault(compact, entry)

    index.domains.sort(key=lambda item: len(item[0]), reverse=True)
    if ci_names:
        index.text_ci = re.compile(
            _WORD_BOUNDARY_LEFT + "(" + _alternation(ci_names) + ")" + _WORD_BOUNDARY_RIGHT, re.IGNORECASE
        )
    if cs_names:
        index.text_cs = re.compile(_WORD_BOUNDARY_LEFT + "(" + _alternation(cs_names) + ")" + _WORD_BOUNDARY_RIGHT)
    if cjk_names:
        index.text_cjk = re.compile("(" + _alternation(cjk_names) + ")")
    return index


_INDEX = _build_index()

# Совместимость со старым кодом
KNOWN_MANUFACTURERS: list[str] = [entry.canonical for entry in MANUFACTURERS]
DOMAIN_MANUFACTURER_HINTS: dict[str, str] = {domain: entry.canonical for domain, entry in _INDEX.domains}


def get_entry(name: str | None) -> ManufacturerEntry | None:
    """Возвращает запись справочника для названия/алиаса производителя."""
    if not name:
        return None
    return _lookup_entry(name)


@lru_cache(maxsize=4096)
def _lookup_entry(name: str) -> ManufacturerEntry | None:
    key = _name_key(name)
    if not key:
        return None
    for candidate in (key, _strip_legal_suffixes(key)):
        if candidate in _INDEX.by_key:
            return _INDEX.by_key[candidate]
    # Транслитерация (Сименс -> simens, Тесто -> testo)
    translit = _strip_legal_suffixes(_name_key(transliterate(name)))
    if translit in _INDEX.by_key:
        return _INDEX.by_key[translit]
    # CJK-названия внутри строки ("意法半导体公司")
    if _is_cjk(name) and _INDEX.text_cjk is not None:
        match = _INDEX.text_cjk.search(name)
        if match:
            return _INDEX.text_lookup.get(match.group(1))
    # Лишние слова после названия: "Murata Electronics", "NXP USA Inc", "Toshiba Semiconductor and Storage"
    words = _strip_legal_suffixes(key).split()
    for size in range(len(words) - 1, 0, -1):
        compact = re.sub(r"[^a-z0-9]", "", "".join(words[:size]))
        if len(compact) >= 3 and compact in _INDEX.slug_keys:
            return _INDEX.slug_keys[compact]
    # Нечёткое совпадение для опечаток ("Infinion", "Texas Instrument")
    for candidate in {key, _strip_legal_suffixes(key), translit}:
        if len(candidate) < 5:
            continue
        match = process.extractOne(candidate, _INDEX.fuzzy_keys, scorer=fuzz.ratio, score_cutoff=86)
        if match:
            return _INDEX.by_key.get(match[0])
    return None


def is_trusted_short_name(name: str) -> bool:
    """Короткое имя (≤ 3 символов) из текста доверенно, только если это точное
    название из справочника (NXP, TDK, ABB), а не сокращение вроде ST/TI/ON."""
    entry = _INDEX.by_key.get(_name_key(name))
    if entry is None:
        return False
    return name in (entry.canonical, *entry.aliases, *entry.case_sensitive)


def normalize_manufacturer_name(name: str | None) -> str:
    """Приводит название производителя на любом языке к каноническому виду.

    Неизвестные названия возвращаются очищенными от лишних пробелов и кавычек.
    """
    if not name:
        return ""
    entry = _lookup_entry(name)
    if entry:
        return entry.canonical
    return _clean_name(name)


def manufacturer_family(name: str | None) -> str | None:
    """Каноническое название материнской компании (Linear Technology -> Analog Devices)."""
    entry = get_entry(name)
    if not entry:
        return None
    return entry.parent or entry.canonical


def manufacturer_similarity(first: str | None, second: str | None) -> float:
    """Оценка сходства двух названий производителя в диапазоне 0..1."""
    if not first or not second:
        return 0.0
    first_entry = get_entry(first)
    second_entry = get_entry(second)
    if first_entry and second_entry:
        if first_entry.canonical == second_entry.canonical:
            return 1.0
        if manufacturer_family(first) == manufacturer_family(second):
            return 0.9
    first_key = _strip_legal_suffixes(_name_key(transliterate(normalize_manufacturer_name(first))))
    second_key = _strip_legal_suffixes(_name_key(transliterate(normalize_manufacturer_name(second))))
    if not first_key or not second_key:
        return 0.0
    if first_key == second_key:
        return 1.0
    score = max(
        fuzz.ratio(first_key, second_key),
        fuzz.token_sort_ratio(first_key, second_key),
    )
    shorter, longer = sorted((first_key, second_key), key=len)
    # Одно название целиком входит в другое ("Testo" / "Testo SE & Co")
    if len(shorter) >= 4 and re.search(r"\b" + re.escape(shorter) + r"\b", longer):
        score = max(score, 90)
    return round(score / 100, 4)


def evaluate_match(submitted: str | None, resolved: str | None) -> tuple[str | None, float | None]:
    """Сравнивает производителя, указанного оператором, с найденным."""
    if not submitted or not submitted.strip():
        return None, None
    if not resolved:
        return "pending", None
    score = manufacturer_similarity(submitted, resolved)
    return ("matched" if score >= 0.75 else "mismatch"), score


def manufacturer_from_url(url: str | None) -> str | None:
    """Определяет производителя по домену URL (ti.com -> Texas Instruments)."""
    host = hostname(url)
    if not host:
        return None
    for domain, entry in _INDEX.domains:
        if host == domain or host.endswith("." + domain):
            return entry.canonical
    return None


def hostname(url: str | None) -> str:
    if not url:
        return ""
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return ""
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def is_distributor(url: str | None) -> bool:
    host = hostname(url)
    if not host:
        return False
    return any(host == domain or host.endswith("." + domain) for domain in DISTRIBUTOR_DOMAINS)


@dataclass(frozen=True)
class Mention:
    canonical: str
    start: int
    end: int
    text: str


def find_manufacturer_mentions(text: str | None) -> list[Mention]:
    """Находит упоминания известных производителей в тексте (с учётом границ слов)."""
    if not text:
        return []
    mentions: list[Mention] = []
    if _INDEX.text_ci is not None:
        for match in _INDEX.text_ci.finditer(text):
            entry = _INDEX.text_lookup.get(match.group(1).lower())
            if entry:
                mentions.append(Mention(entry.canonical, match.start(), match.end(), match.group(1)))
    if _INDEX.text_cs is not None:
        for match in _INDEX.text_cs.finditer(text):
            entry = _INDEX.text_lookup.get("cs:" + match.group(1))
            if entry:
                mentions.append(Mention(entry.canonical, match.start(), match.end(), match.group(1)))
    if _INDEX.text_cjk is not None and _is_cjk(text):
        for match in _INDEX.text_cjk.finditer(text):
            entry = _INDEX.text_lookup.get(match.group(1))
            if entry:
                mentions.append(Mention(entry.canonical, match.start(), match.end(), match.group(1)))
    mentions.sort(key=lambda item: item.start)
    return mentions


def manufacturer_from_slug(slug: str) -> str | None:
    """Распознаёт производителя в сегменте URL (``stmicroelectronics``, ``nxp-usa-inc``)."""
    cleaned = _name_key(unquote(slug).replace("-", " ").replace("_", " ").replace("+", " "))
    words = cleaned.split()
    if not words:
        return None
    # "nxp usa inc" -> "nxpusainc", "nxpusa", "nxp"; "murata electronics" -> ... "murata"
    for size in range(len(words), 0, -1):
        compact = "".join(words[:size])
        if len(compact) < 3:
            break
        entry = _INDEX.slug_keys.get(compact)
        if entry is not None:
            return entry.canonical
    return None


def fold_lookalikes(text: str) -> str:
    return unicodedata.normalize("NFKC", text).translate(_CYRILLIC_LOOKALIKES)


def part_number_key(part_number: str | None) -> str:
    """Ключ артикула: только буквы/цифры, верхний регистр, кириллица-двойники -> латиница.

    Прочие кириллические буквы сохраняются (российские артикулы вида ``К155ЛА3``).
    """
    if not part_number:
        return ""
    return re.sub(r"[^0-9A-ZА-ЯЁ]", "", fold_lookalikes(part_number).upper())


def has_mixed_scripts(part_number: str) -> bool:
    """True, если в артикуле одновременно латиница и кириллица (типичная опечатка раскладки)."""
    return bool(re.search(r"[A-Za-z]", part_number)) and bool(re.search(r"[А-Яа-яЁё]", part_number))


@lru_cache(maxsize=2048)
def _part_patterns(key: str) -> tuple[re.Pattern[str], re.Pattern[str] | None]:
    separators = r"[\s\-_./]?"
    body = separators.join(re.escape(ch) for ch in key)
    # Слева артикул не должен продолжать другой номер: ни "XLM317", ни "5935-0560-0001"
    left = r"(?<![0-9A-ZА-ЯЁ])(?<![0-9A-ZА-ЯЁ][\-_./])"
    exact = re.compile(left + body + r"(?P<tail>[0-9A-ZА-ЯЁ]*)", re.IGNORECASE)
    base: re.Pattern[str] | None = None
    base_len = max(4, int(len(key) * 0.7 + 0.5))
    if len(key) > base_len:
        base_body = separators.join(re.escape(ch) for ch in key[:base_len])
        base = re.compile(left + base_body + r"[0-9A-ZА-ЯЁ]*(?![0-9A-ZА-ЯЁ])", re.IGNORECASE)
    return exact, base


def part_number_strength(part_number: str | None, text: str | None) -> float:
    """Насколько уверенно текст упоминает артикул.

    * 1.0 — точное упоминание (с учётом пробелов/дефисов/точек внутри артикула);
    * 0.75 — упоминание с дополнительным суффиксом (``LM317T`` -> ``LM317TG``);
    * 0.5 — упоминание базовой серии (``LM317T`` -> ``LM317``);
    * 0.0 — артикул не найден.
    """
    key = part_number_key(part_number)
    if not key or not text:
        return 0.0
    folded = fold_lookalikes(text).upper()
    exact, base = _part_patterns(key)
    best = 0.0
    for match in exact.finditer(folded):
        tail = match.group("tail")
        if not tail:
            return 1.0
        # Короткий суффикс исполнения/упаковки
        if len(tail) <= 4:
            best = max(best, 0.75)
    if best:
        return best
    if len(key) < 5:
        return 0.0
    if base is not None and base.search(folded):
        return 0.5
    return 0.0


def query_part_number(part_number: str) -> str:
    """Вариант артикула для поискового запроса (исправляет смешанную раскладку)."""
    cleaned = re.sub(r"\s+", " ", part_number.strip())
    if has_mixed_scripts(cleaned):
        return fold_lookalikes(cleaned)
    return cleaned


def manufacturer_info_from_dictionary(name: str | None) -> dict[str, str | None]:
    """Справочная информация о производителе без обращения к OpenAI."""
    entry = get_entry(name)
    if not entry:
        return {}
    aliases = [alias for alias in entry.aliases if alias != entry.canonical and not _is_cjk(alias)][:4]
    return {
        "what_produces": entry.produces,
        "website": f"https://www.{entry.domains[0]}" if entry.domains else None,
        "manufacturer_aliases": ", ".join(aliases) or None,
        "country": entry.country,
    }


__all__ = [
    "DISTRIBUTOR_DOMAINS",
    "DOMAIN_MANUFACTURER_HINTS",
    "KNOWN_MANUFACTURERS",
    "MANUFACTURERS",
    "ManufacturerEntry",
    "Mention",
    "evaluate_match",
    "find_manufacturer_mentions",
    "fold_lookalikes",
    "get_entry",
    "has_mixed_scripts",
    "hostname",
    "is_distributor",
    "is_trusted_short_name",
    "manufacturer_family",
    "manufacturer_from_slug",
    "manufacturer_from_url",
    "manufacturer_info_from_dictionary",
    "manufacturer_similarity",
    "normalize_manufacturer_name",
    "part_number_key",
    "part_number_strength",
    "query_part_number",
    "transliterate",
]
