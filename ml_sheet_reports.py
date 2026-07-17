from __future__ import annotations

import logging
from typing import Any

import gspread

logger = logging.getLogger(__name__)

REPORT_ECONOMY = "📊 Экономика"
REPORT_OVERPRICED = "📈 Переоценено"
REPORT_UNDERPRICED = "📈 Недооценено"
REPORT_GEAR_ANOMALIES = "📈 Аномалии геара"
REPORT_MISSING = "🔍 Отсутствующий лут"
REPORT_BALANCE = "⚖️ Балансировка"
REPORT_STOCK = "📦 Склады"
REPORT_CLUSTERS = "🔬 Кластеры"
REPORT_ARBITRAGE = "🚨 Арбитраж"


def _get_or_create_worksheet(
    sheet: gspread.Spreadsheet, title: str, rows: int = 500, cols: int = 12
) -> gspread.Worksheet:
    try:
        ws = sheet.worksheet(title)
        ws.clear()
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title, rows, cols)
    return ws


def write_economy_report(
    spreadsheet: gspread.Spreadsheet, result: dict[str, Any]
) -> None:
    ws = _get_or_create_worksheet(spreadsheet, REPORT_ECONOMY, rows=500, cols=12)

    rows: list[list[Any]] = []

    loot_income = result.get("loot_income", {})
    by_tier = loot_income.get("by_tier", {})
    gear = result.get("gear_market", {})
    missing = result.get("missing_loot", {})

    rows.append(["ДОХОД ИГРОКА — продажа лута трейдеру"])
    rows.append([])
    rows.append(["Tier", "Зона", "Кол-во", "sellPrice (медиана)", "min", "max"])
    for tier_str, summary in sorted(by_tier.items(), key=lambda x: int(x[0])):
        t = int(tier_str)
        if summary["count"] > 0:
            from ml_price_analysis import TIER_NAMES
            name = TIER_NAMES.get(t, f"Tier{t}")
            rows.append([
                t, name, summary["count"],
                summary["median"], summary["min_price"], summary["max_price"],
            ])

    rows.append([])
    rows.append(["РАСХОД ИГРОКА — покупка снаряжения (stockSettings=0)"])
    rows.append([])
    rows.append(["Всего позиций геара", gear.get("total_gear", 0)])
    rows.append(["Мин. цена buyPrice", gear.get("buyPrice_min", 0)])
    rows.append(["Медиана buyPrice", gear.get("buyPrice_median", 0)])
    rows.append(["Макс. цена buyPrice", gear.get("buyPrice_max", 0)])

    rows.append([])
    tiers_sorted = sorted(by_tier.items(), key=lambda x: int(x[0]))
    loot_medians = [(int(t), s["median"]) for t, s in tiers_sorted if s["count"] > 0]
    gear_med = gear.get("buyPrice_median", 0)
    if loot_medians and gear_med > 0:
        rows.append(["ЭКОНОМИЧЕСКИЙ БАЛАНС"])
        rows.append([])
        med_str = ", ".join(f"Tier{t}: {m:,}" for t, m in loot_medians)
        rows.append(["Средний доход с продажи лута", med_str])
        rows.append(["Средняя цена геара", gear_med])
        for t, m in loot_medians[:3]:
            if m > 0:
                ratio = gear_med / m
                rows.append([
                    "Нужно продать для покупки среднего геара",
                    f"~{ratio:.0f} предметов Tier{t}",
                ])

    if missing:
        rows.append([])
        rows.append(["ПОКРЫТИЕ ЛУТА ТРЕЙДЕРАМИ"])
        rows.append([])
        rows.append(["Всего в луте", missing.get("total_loot_items", 0)])
        rows.append(["Нет у трейдеров", missing.get("total_missing", 0)])
        rows.append(["Покрытие", f"{missing.get('coverage_pct', 0)}%"])

    ws.update(rows, "A1")


def write_overpriced_report(
    spreadsheet: gspread.Spreadsheet, result: dict[str, Any]
) -> None:
    ws = _get_or_create_worksheet(spreadsheet, REPORT_OVERPRICED, rows=1000, cols=8)

    loot_income = result.get("loot_income", {})
    anomalies = loot_income.get("anomalies", [])
    overpriced = [a for a in anomalies if a["direction"] == "overpriced"]

    rows: list[list[Any]] = [
        ["className", "tier", "stockSettings", "sellPrice", "медиана тира",
         "отклонение %"],
    ]
    for a in overpriced:
        rows.append([
            a["className"], a["tier"], a.get("stockSettings", ""),
            a["price"], a["tier_median"], a["deviation"],
        ])

    ws.update(rows, "A1")


def write_underpriced_report(
    spreadsheet: gspread.Spreadsheet, result: dict[str, Any]
) -> None:
    ws = _get_or_create_worksheet(spreadsheet, REPORT_UNDERPRICED, rows=1000, cols=8)

    loot_income = result.get("loot_income", {})
    anomalies = loot_income.get("anomalies", [])
    underpriced = [a for a in anomalies if a["direction"] == "underpriced"]

    rows: list[list[Any]] = [
        ["className", "tier", "stockSettings", "sellPrice", "медиана тира",
         "отклонение %"],
    ]
    for a in underpriced:
        rows.append([
            a["className"], a["tier"], a.get("stockSettings", ""),
            a["price"], a["tier_median"], a["deviation"],
        ])

    ws.update(rows, "A1")


def write_gear_anomaly_report(
    spreadsheet: gspread.Spreadsheet, result: dict[str, Any]
) -> None:
    ws = _get_or_create_worksheet(
        spreadsheet, REPORT_GEAR_ANOMALIES, rows=1000, cols=8
    )

    gear_anomalies = result.get("loot_buy_analysis", {}).get("anomalies", [])

    rows: list[list[Any]] = [
        ["className", "tier", "stockSettings", "buyPrice", "медиана тира",
         "отклонение %"],
    ]
    for a in gear_anomalies:
        rows.append([
            a["className"], a["tier"], a.get("stockSettings", ""),
            a["price"], a["tier_median"], a["deviation"],
        ])

    ws.update(rows, "A1")


def write_missing_loot_report(
    spreadsheet: gspread.Spreadsheet, result: dict[str, Any]
) -> None:
    ws = _get_or_create_worksheet(spreadsheet, REPORT_MISSING, rows=500, cols=5)

    missing = result.get("missing_loot", {})

    rows: list[list[Any]] = [
        ["className", "Tier", "weight"],
    ]
    for item in missing.get("missing_items", []):
        rows.append([item["className"], item["tier"], item["weight"]])

    rows.append([])
    rows.append(["Итого отсутствует", missing.get("total_missing", 0), ""])
    rows.append(["Всего в луте", missing.get("total_loot_items", 0), ""])
    rows.append(["Покрытие", f"{missing.get('coverage_pct', 0)}%", ""])

    ws.update(rows, "A1")


def write_balance_report(
    spreadsheet: gspread.Spreadsheet, balance_stats: dict[str, Any] | None
) -> None:
    ws = _get_or_create_worksheet(spreadsheet, REPORT_BALANCE, rows=1000, cols=12)

    if not balance_stats:
        ws.update([["Нет данных — запустите с --balance"]], "A1")
        return

    rows: list[list[Any]] = []

    corrections = balance_stats.get("corrections_by_tier", {})
    if corrections:
        rows.append(["Коэффициенты коррекции по тирам"])
        rows.append([])
        rows.append(["Tier", "Correction"])
        for t_str, corr in sorted(corrections.items(), key=lambda x: int(x[0])):
            rows.append([t_str, corr])

    rows.append([])
    rows.append(["Статистика"])
    rows.append([])
    rows.append(["Файлов изменено", balance_stats.get("files_changed", 0)])
    rows.append(["Файлов без изменений", balance_stats.get("files_unchanged", 0)])
    rows.append(["Пропущено (buyPrice=-1)", balance_stats.get("skipped_unpurchasable", 0)])
    rows.append(["Пропущено (sellPrice=-1)", balance_stats.get("skipped_buy_only", 0)])
    rows.append(["Пропущено (не в луте)", balance_stats.get("skipped_not_in_lootzones", 0)])
    rows.append(["Всего просканировано", balance_stats.get("total_files_scanned", 0)])

    changes = balance_stats.get("changes", [])
    if changes:
        rows.append([])
        rows.append(["Изменения"])
        rows.append([])
        rows.append([
            "file", "className", "tier", "stockSettings",
            "old_sellPrice", "new_sellPrice", "old_buyPrice", "new_buyPrice",
        ])
        for c in changes:
            rows.append([
                c["file"], c["className"], c["tier"], c["stockSettings"],
                c["old_sellPrice"], c["new_sellPrice"],
                c["old_buyPrice"], c["new_buyPrice"],
            ])

    ws.update(rows, "A1")


def _migrate_old_sheets(spreadsheet: gspread.Spreadsheet) -> None:
    """Remove renamed/replaced worksheets from previous versions."""
    old_titles = {"📈 Аномалии цен"}  # was split into Переоценено/Недооценено/Аномалии геара
    for title in old_titles:
        try:
            ws = spreadsheet.worksheet(title)
            spreadsheet.del_worksheet(ws)
            logger.info("Удалён старый лист: %s", title)
        except gspread.exceptions.WorksheetNotFound:
            pass


def write_all_economy_reports(
    spreadsheet: gspread.Spreadsheet,
    result: dict[str, Any],
    balance_stats: dict[str, Any] | None = None,
) -> None:
    _migrate_old_sheets(spreadsheet)
    write_economy_report(spreadsheet, result)
    write_overpriced_report(spreadsheet, result)
    write_underpriced_report(spreadsheet, result)
    write_gear_anomaly_report(spreadsheet, result)
    write_missing_loot_report(spreadsheet, result)
    write_balance_report(spreadsheet, balance_stats)
    logger.info("Все отчёты записаны в Google Sheets")


def write_arbitrage_report(
    spreadsheet: gspread.Spreadsheet, result: dict[str, Any]
) -> None:
    ws = _get_or_create_worksheet(spreadsheet, REPORT_ARBITRAGE, rows=2000, cols=14)

    rows: list[list[Any]] = []

    rows.append(["ДЕТЕКТОР АРБИТРАЖА"])
    rows.append([])
    rows.append(["Всего найдено", result.get("total_arbitrages", 0)])
    by_sev = result.get("by_severity", {})
    if by_sev:
        rows.append(["Критических", by_sev.get("critical", 0)])
        rows.append(["Высоких", by_sev.get("high", 0)])
        rows.append(["Средних", by_sev.get("medium", 0)])
        rows.append(["Низких", by_sev.get("low", 0)])
    rows.append([])

    rows.append([
        "Тип", "Класс", "Описание", "Маржа %", "Прибыль",
        "Торговец покупка", "Торговец продажа",
        "Цена покупки", "Цена продажи", "Критичность",
        "Рекомендация",
    ])

    for a in result.get("arbitrages", []):
        rows.append([
            a.get("type", ""),
            a.get("className", ""),
            a.get("description", ""),
            a.get("profit_margin_pct", 0),
            a.get("profit_per_item", 0),
            a.get("buy_trader_name", a.get("trader_name", "")),
            a.get("sell_trader_name", ""),
            a.get("buy_price", ""),
            a.get("sell_price", ""),
            a.get("severity", ""),
            a.get("fix_suggestion", ""),
        ])

    rows.append([])
    rows.append(["Статистика"])
    rows.append([])
    rows.append(["Файлов просканировано", result.get("stats", {}).get("files_scanned", 0)])
    rows.append(["Уникальных предметов", result.get("stats", {}).get("unique_classnames", 0)])
    rows.append(["Уникальных торговцев", result.get("stats", {}).get("unique_traders", 0)])

    ws.update(rows, "A1")


def write_all_reports(
    spreadsheet: gspread.Spreadsheet,
    economy_result: dict[str, Any] | None = None,
    balance_stats: dict[str, Any] | None = None,
    arbitrage_result: dict[str, Any] | None = None,
) -> None:
    if economy_result:
        write_all_economy_reports(spreadsheet, economy_result, balance_stats)
    if arbitrage_result:
        write_arbitrage_report(spreadsheet, arbitrage_result)
