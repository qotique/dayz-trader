from __future__ import annotations

import logging
from typing import Any

from models import input as input_models
from models._utils import translit_key

logger = logging.getLogger(__name__)


def analyze_missing_attachments(
    products_all: list[input_models.Product],
    traders_raw: list[input_models.Trader],
) -> dict[str, Any]:
    """Analyze missing weapon attachments across traders.

    Scenario 1: A weapon references an attachment className in its
    ``attachments_list`` but no product with that className exists in
    the catalog at all (nobody sells it).

    Scenario 2: A trader sells a weapon whose ``attachments_list`` is
    non-empty, but the trader does not sell one or more of those
    attachment products.
    """

    all_classnames: set[str] = {p.className for p in products_all}

    trader_keys: list[str] = [translit_key(t.givenName) for t in traders_raw]
    trader_key_to_name: dict[str, str] = {
        translit_key(t.givenName): t.givenName for t in traders_raw
    }

    class_by_trader: dict[str, set[str]] = {tk: set() for tk in trader_keys}
    for p in products_all:
        for tk in trader_keys:
            if p.trader_access.get(tk, False):
                class_by_trader[tk].add(p.className)

    weapons = [p for p in products_all if p.attachments_list]

    missing_globally: list[dict[str, Any]] = []
    for p in weapons:
        for att in p.attachments_list:
            if att not in all_classnames:
                sellers = [
                    tk for tk in trader_keys
                    if p.trader_access.get(tk, False)
                ]
                missing_globally.append({
                    "weapon_class": p.className,
                    "weapon_category": p.category,
                    "missing_attachment": att,
                    "traders_selling_weapon": [
                        trader_key_to_name[tk] for tk in sellers
                    ],
                })

    seen_g: set[tuple[str, str]] = set()
    unique_global: list[dict[str, Any]] = []
    for item in missing_globally:
        key = (item["weapon_class"], item["missing_attachment"])
        if key not in seen_g:
            seen_g.add(key)
            unique_global.append(item)

    missing_per_trader: list[dict[str, Any]] = []
    for tk in trader_keys:
        for p in weapons:
            if not p.trader_access.get(tk, False):
                continue
            missing_atts = [
                att for att in p.attachments_list
                if att not in class_by_trader[tk]
            ]
            if missing_atts:
                missing_per_trader.append({
                    "trader": trader_key_to_name[tk],
                    "trader_key": tk,
                    "weapon_class": p.className,
                    "weapon_category": p.category,
                    "missing_attachments": missing_atts,
                })

    all_refs: set[tuple[str, str]] = set()
    for p in weapons:
        for att in p.attachments_list:
            all_refs.add((p.className, att))

    affected_traders = {item["trader_key"] for item in missing_per_trader}

    return {
        "missing_globally": unique_global,
        "missing_per_trader": missing_per_trader,
        "summary": {
            "total_weapons_with_attachments": len(weapons),
            "total_attachment_refs": len(all_refs),
            "unique_missing_globally": len(unique_global),
            "traders_with_missing_attachments": len(affected_traders),
            "affected_trader_names": sorted(
                trader_key_to_name[tk] for tk in affected_traders
            ),
        },
    }


def print_attachment_report(result: dict[str, Any]) -> None:
    summary = result["summary"]
    missing_global = result["missing_globally"]
    missing_per_trader = result["missing_per_trader"]

    print()
    print("=" * 72)
    print("  АНАЛИТИКА ОТСУТСТВУЮЩИХ ОБВЕСОВ")
    print("=" * 72)

    print()
    print(f"  Оружие с обвесами:          {summary['total_weapons_with_attachments']}")
    print(f"  Всего ссылок на обвесы:      {summary['total_attachment_refs']}")
    print(f"  Обвес не продается нигде:    {summary['unique_missing_globally']}")
    print(f"  Трейдеры с пропусками:       {summary['traders_with_missing_attachments']}")

    if summary["affected_trader_names"]:
        print(f"  Затронутые трейдеры:         {', '.join(summary['affected_trader_names'])}")

    print()
    print("-" * 72)
    print("  СЦЕНАРИЙ 1: Обвес определён, но не продаётся ни одним трейдером")
    print("-" * 72)

    if not missing_global:
        print("  Все обвесы присутствуют в каталоге. ✓")
    else:
        print()
        print(f"  {'Оружие':<35} {'Обвес':<30} {'Продавцы оружия'}")
        print(f"  {'-'*35} {'-'*30} {'-'*30}")
        for item in missing_global:
            sellers = ", ".join(item["traders_selling_weapon"]) or "—"
            print(
                f"  {item['weapon_class']:<35} "
                f"{item['missing_attachment']:<30} "
                f"{sellers}"
            )

    print()
    print("-" * 72)
    print("  СЦЕНАРИЙ 2: Трейдер продаёт оружие, но не продаёт обвес")
    print("-" * 72)

    if not missing_per_trader:
        print("  Все трейдеры продают обвесы к своему оружию. ✓")
    else:
        by_trader: dict[str, list[dict[str, Any]]] = {}
        for item in missing_per_trader:
            by_trader.setdefault(item["trader"], []).append(item)

        for trader_name in sorted(by_trader):
            items = by_trader[trader_name]
            print()
            print(f"  {trader_name}:")
            for item in items:
                atts = ", ".join(item["missing_attachments"])
                print(f"    {item['weapon_class']:<35} -> {atts}")

    print()
    print("-" * 72)
    print("  ОБВЕС — ОРУЖИЕ — ТРЕЙДЕРЫ БЕЗ ОБВЕСА")
    print("-" * 72)

    if not missing_per_trader:
        print("  Все трейдеры продают обвесы к своему оружию. ✓")
    else:
        by_att: dict[str, dict[str, list[str]]] = {}
        for item in missing_per_trader:
            for att in item["missing_attachments"]:
                by_att.setdefault(att, {}).setdefault(
                    item["weapon_class"], []
                ).append(item["trader"])

        for att in sorted(by_att):
            weapons = by_att[att]
            print()
            print(f"  {att}")
            for weapon in sorted(weapons):
                traders = sorted(set(weapons[weapon]))
                print(f"    {weapon:<35}  ->  {', '.join(traders)}")

    print()
    print("=" * 72)
