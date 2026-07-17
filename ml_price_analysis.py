from __future__ import annotations

import json
import logging
import os
import statistics
from typing import Any

logger = logging.getLogger(__name__)

ZONE_TIER: dict[str, int] = {
    "LootZone_BuildingMaterials": 0,
    "LootZone_Solnechnoe": 0,
    "LootZone_Tier1": 1,
    "LootZone_Tier1_Military": 1,
    "LootZone_Tier1_Stash": 1,
    "LootZone_Tier2": 2,
    "LootZone_Tier2_Military": 2,
    "LootZone_Tier2_Stash": 2,
    "LootZone_Tier3": 3,
    "LootZone_Tier3_Military": 3,
    "LootZone_Tier3_Stash": 3,
    "LootZone_Tier4": 4,
    "LootZone_Tier4_Military": 4,
    "LootZone_Tier4_Stash": 4,
    "LootZone_Tier5": 5,
    "LootZone_Tier5_Military": 5,
    "LootZone_Tier5_Stash": 5,
}

TARGET_SELLPRICE_BY_TIER: dict[int, int] = {
    0: 50,
    1: 200,
    2: 800,
    3: 3000,
    4: 10000,
    5: 30000,
}

TIER_NAMES: dict[int, str] = {
    0: "Стройматериалы / Солнечное",
    1: "Tier1",
    2: "Tier2",
    3: "Tier3",
    4: "Tier4",
    5: "Tier5",
}


def _stock_demand_factor(ss: int, overrides: dict[int, float] | None = None) -> float:
    if overrides and ss in overrides:
        return overrides[ss]
    if ss == 0:
        return 0.8
    return max(0.5, min(1.5, (ss + 50) / 100))


def load_lootzones(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    items: dict[str, list[dict[str, Any]]] = {}
    for z in data.get("zones", []):
        tier = ZONE_TIER.get(z.get("zoneName", ""), 0)
        drop_chance = z.get("dropChance", 1.0)
        for c in z.get("classNames", []):
            cn = c["className"]
            items.setdefault(cn, []).append({
                "tier": tier,
                "weight": c.get("weight", 0.5),
                "dropChance": drop_chance,
                "zone": z["zoneName"],
            })

    return {"items": items, "zones": data.get("zones", [])}


def compute_rarity(loot_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for cn, appearances in loot_data["items"].items():
        min_tier = min(a["tier"] for a in appearances)
        in_lowest = [a for a in appearances if a["tier"] == min_tier]
        max_weight_in_lowest = max(a["weight"] for a in in_lowest)
        total_weight = sum(a["weight"] * a["dropChance"] for a in appearances)
        zone_count = len(appearances)

        within_tier_rarity = 1.0 - max_weight_in_lowest
        rarity_score = min_tier * 100 + within_tier_rarity * 50

        result[cn] = {
            "min_tier": min_tier,
            "max_weight_in_lowest_tier": max_weight_in_lowest,
            "total_weight": total_weight,
            "zone_count": zone_count,
            "rarity_score": rarity_score,
            "appearances": appearances,
        }
    return result


def load_product_prices(products_dir: str) -> dict[str, dict[int, list[dict[str, Any]]]]:
    result: dict[str, dict[int, list[dict[str, Any]]]] = {}
    if not os.path.isdir(products_dir):
        logger.warning("Products directory not found: %s", products_dir)
        return result

    for fname in os.listdir(products_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(products_dir, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                d = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Skipping %s: %s", fname, e)
            continue

        if not isinstance(d, dict):
            logger.debug("Skipping %s: root is %s, not dict", fname, type(d).__name__)
            continue

        cn = d.get("className", "")
        ss = d.get("stockSettings", -1)
        if not cn:
            continue

        result.setdefault(cn, {}).setdefault(ss, []).append({
            "buyPrice": int(d.get("buyPrice", 0)),
            "sellPrice": int(d.get("sellPrice", 0)),
            "productId": fname[:-5],
        })

    return result


def analyze_economy(
    loot_path: str,
    products_dir: str,
) -> dict[str, Any]:
    loot_data = load_lootzones(loot_path)
    rarity = compute_rarity(loot_data)
    prices = load_product_prices(products_dir)

    tier_loot_items: dict[int, list[dict[str, Any]]] = {}
    loot_buy_by_tier: dict[int, list[dict[str, Any]]] = {}

    for cn, r in rarity.items():
        tier = r["min_tier"]
        if cn not in prices:
            continue
        for ss, entries in prices[cn].items():
            avg_bp = statistics.mean(e["buyPrice"] for e in entries)
            avg_sp = statistics.mean(e["sellPrice"] for e in entries)
            ssf = _stock_demand_factor(ss)
            item_info = {
                "className": cn,
                "buyPrice": round(avg_bp),
                "sellPrice": round(avg_sp),
                "weight": r["max_weight_in_lowest_tier"],
                "tier": tier,
                "rarity_score": r["rarity_score"],
                "zone_count": r["zone_count"],
                "total_weight": r["total_weight"],
                "stockSettings": ss,
                "demandFactor": round(ssf, 3),
            }
            tier_loot_items.setdefault(tier, []).append(item_info)
            if ss == 0:
                loot_buy_by_tier.setdefault(tier, []).append(item_info)

    tier_summary = _compute_tier_summaries(tier_loot_items, "sellPrice")
    tier_buy_summary = _compute_tier_summaries(loot_buy_by_tier, "buyPrice")

    anomalies = _find_anomalies(tier_loot_items, tier_summary, "sellPrice")
    anomalies_buy = _find_anomalies(loot_buy_by_tier, tier_buy_summary, "buyPrice")

    gear_items = _load_gear_items(prices, rarity)

    missing = find_missing_loot_items(loot_path, products_dir)

    return {
        "loot_income": {
            "by_tier": {str(k): v for k, v in tier_summary.items()},
            "items": {str(k): v for k, v in tier_loot_items.items()},
            "anomalies": anomalies,
        },
        "loot_buy_analysis": {
            "by_tier": {str(k): v for k, v in tier_buy_summary.items()},
            "anomalies": anomalies_buy,
        },
        "gear_market": gear_items,
        "total_loot_items": len(rarity),
        "missing_loot": missing,
    }


def _compute_tier_summaries(
    tier_items: dict[int, list[dict[str, Any]]], price_key: str,
) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for tier in sorted(tier_items):
        items = tier_items[tier]
        prices_list = [it[price_key] for it in items]
        if not prices_list:
            result[tier] = {"tier": tier, "count": 0}
            continue
        q = (
            statistics.quantiles(prices_list, n=4)
            if len(prices_list) >= 4
            else [prices_list[0], prices_list[-1]]
        )
        result[tier] = {
            "tier": tier,
            "count": len(items),
            "min_price": min(prices_list),
            "q25": q[0],
            "median": statistics.median(prices_list),
            "q75": q[1] if len(q) > 1 else q[0],
            "max_price": max(prices_list),
        }
    return result


def _find_anomalies(
    tier_items: dict[int, list[dict[str, Any]]],
    tier_summary: dict[int, dict[str, Any]],
    price_key: str,
) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    for tier, items in tier_items.items():
        summary = tier_summary.get(tier, {})
        median = summary.get("median", 0)
        q25 = summary.get("q25", 0)
        q75 = summary.get("q75", 0)
        iqr = q75 - q25
        lower = q25 - 1.5 * iqr if iqr > 0 else median * 0.1
        upper = q75 + 1.5 * iqr if iqr > 0 else median * 10

        for item in items:
            price = item[price_key]
            if median > 0 and price != median:
                deviation = (price - median) / median
                if price < lower or price > upper:
                    anomalies.append({
                        "className": item["className"],
                        "tier": tier,
                        "price": price,
                        "tier_median": median,
                        "deviation": round(deviation * 100),
                        "direction": "overpriced" if price > median else "underpriced",
                        "stockSettings": item.get("stockSettings"),
                        "demandFactor": item.get("demandFactor", 1.0),
                    })

    return sorted(anomalies, key=lambda x: -abs(x["deviation"]))


def _load_gear_items(
    prices: dict[str, dict[int, list[dict[str, int]]]],
    rarity: dict[str, Any],
) -> dict[str, Any]:
    gear_items: list[dict[str, Any]] = []
    loot_cns = set(rarity.keys())

    for cn, ss_dict in prices.items():
        if 0 not in ss_dict:
            continue
        if cn not in loot_cns:
            avg_bp = statistics.mean(e["buyPrice"] for e in ss_dict[0])
            gear_items.append({"className": cn, "buyPrice": round(avg_bp)})

    gear_items.sort(key=lambda x: x["buyPrice"])
    buy_prices = [it["buyPrice"] for it in gear_items]

    return {
        "total_gear": len(gear_items),
        "items": gear_items,
        "buyPrice_min": min(buy_prices) if buy_prices else 0,
        "buyPrice_median": statistics.median(buy_prices) if buy_prices else 0,
        "buyPrice_max": max(buy_prices) if buy_prices else 0,
    }


def print_price_report(result: dict[str, Any]) -> None:
    loot_income = result["loot_income"]
    loot_buy = result["loot_buy_analysis"]
    gear = result["gear_market"]

    print("\n" + "=" * 70)
    print("   ЭКОНОМИЧЕСКИЙ АНАЛИЗ (Economy Report)")
    print("=" * 70)

    print("\n1. ДОХОД ИГРОКА — продажа лута трейдеру\n")
    _print_tier_table(loot_income["by_tier"], "sellPrice")

    overpriced = [a for a in loot_income["anomalies"] if a["direction"] == "overpriced"]
    underpriced = [a for a in loot_income["anomalies"] if a["direction"] == "underpriced"]

    if overpriced:
        print("\n  ПЕРЕОЦЕНЕНО (игрок продаёт слишком дорого -> лёгкие деньги):")
        for a in overpriced[:10]:
            _print_anomaly(a, "sellPrice")
        if len(overpriced) > 10:
            print(f"    ... и ещё {len(overpriced) - 10}")

    if underpriced:
        print("\n  НЕДООЦЕНЕНО (игрок продаёт слишком дёшево -> невыгодно тащить):")
        for a in underpriced[:10]:
            _print_anomaly(a, "sellPrice")
        if len(underpriced) > 10:
            print(f"    ... и ещё {len(underpriced) - 10}")

    print("\n2. РАСХОД ИГРОКА — покупка снаряжения (stockSettings=0)\n")
    print(f"  Всего позиций геара: {gear['total_gear']}")
    print(
        f"  Цены buyPrice:  min={gear['buyPrice_min']:,}  "
        f"median={gear['buyPrice_median']:,}  "
        f"max={gear['buyPrice_max']:,}"
    )

    cheap = [it for it in gear["items"] if it["buyPrice"] <= 1000]
    moderate = [it for it in gear["items"] if 1000 < it["buyPrice"] <= 10000]
    expensive = [it for it in gear["items"] if 10000 < it["buyPrice"] <= 100000]
    luxury = [it for it in gear["items"] if it["buyPrice"] > 100000]
    print("\n  Категории:")
    print(f"    До 1 000 руб:       {len(cheap):>4} предметов")
    print(f"    1 000 - 10 000 руб: {len(moderate):>4} предметов")
    print(f"    10 000 - 100 000:   {len(expensive):>4} предметов")
    print(f"    > 100 000 руб:      {len(luxury):>4} предметов")

    gear_anomalies = loot_buy.get("anomalies", [])
    if gear_anomalies:
        print("\n  Аномальные цены (loot предметы в ss=0):")
        for a in gear_anomalies[:10]:
            _print_anomaly(a, "buyPrice")

    print("\n3. ЭКОНОМИЧЕСКИЙ БАЛАНС\n")
    tiers_sorted = sorted(loot_income["by_tier"].items(), key=lambda x: int(x[0]))
    loot_medians = [(int(t), s["median"]) for t, s in tiers_sorted if s["count"] > 0]
    gear_med = gear["buyPrice_median"]

    if loot_medians and gear_med > 0:
        print(
            "  Средний доход с продажи лута: "
            + ", ".join(f"Tier{t}: {m:,}" for t, m in loot_medians)
        )
        print(f"  Средняя цена геара:           {gear_med:,}")
        for t, m in loot_medians[:3]:
            if m > 0:
                ratio = gear_med / m
                print(
                    f"  Для покупки среднего геара нужно продать "
                    f"~{ratio:.0f} предметов Tier{t}."
                )
        if gear["buyPrice_min"] > 0:
            cheapest = gear["buyPrice_min"]
            for t, m in reversed(loot_medians[-3:]):
                if m > 0:
                    count = cheapest / m
                    if count >= 1:
                        print(
                            f"  Самый дешёвый геар ({cheapest:,} руб) — продать "
                            f"{count:.1f} предметов Tier{t}."
                        )

    missing = result.get("missing_loot", {})
    if missing:
        by_zone = missing.get("by_zone", [])
        if by_zone:
            print("\n4. ПРЕДМЕТЫ ЛУТА ОТСУТСТВУЮЩИЕ У ТРЕЙДЕРОВ\n")
            print(f"  Всего в луте: {missing['total_loot_items']}, "
                  f"нет у трейдеров: {missing['total_missing']}, "
                  f"покрытие: {missing['coverage_pct']}%\n")
            for z in by_zone:
                print(f"  {z['zoneName']:30s}  {z['count']:>4} отсутствует")
                for name in z['items'][:10]:
                    print(f"    - {name}")
                if len(z['items']) > 10:
                    print(f"    ... и ещё {len(z['items']) - 10}")

    print("\n" + "=" * 70 + "\n")


def _print_anomaly(a: dict[str, Any], price_label: str) -> None:
    ss = a.get("stockSettings", "")
    ss_str = f" ss={ss}" if ss != "" else ""
    print(
        f"    {a['className']:35s} tier={a['tier']}{ss_str}  "
        f"{price_label}={a['price']:>8,}  "
        f"(медиана тира={a['tier_median']:>8,})  "
        f"[{a['deviation']:+.0f}%]"
    )


def _print_tier_table(
    by_tier: dict[str, dict[str, Any]], price_label: str,
) -> None:
    print(
        f"  {'Tier':<6} {'Зона':<20} {'Кол-во':>6}  "
        f"{price_label:>10} {'min':>10} {'max':>10}"
    )
    print(f"  {'-'*66}")
    for tier_str, summary in sorted(by_tier.items(), key=lambda x: int(x[0])):
        t = int(tier_str)
        name = TIER_NAMES.get(t, f"Tier{t}")
        if summary["count"] > 0:
            print(
                f"  {t:<6} {name:<20} {summary['count']:>6}  "
                f"{summary['median']:>10,} {summary['min_price']:>10,} "
                f"{summary['max_price']:>10,}"
            )


def find_missing_loot_items(
    loot_path: str,
    products_dir: str,
) -> dict[str, Any]:
    loot_data = load_lootzones(loot_path)
    rarity = compute_rarity(loot_data)

    product_classnames: set[str] = set()
    for fname in os.listdir(products_dir):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(products_dir, fname), encoding="utf-8") as f:
                d = json.load(f)
            if not isinstance(d, dict):
                logger.debug("Skipping %s: root is %s, not dict", fname, type(d).__name__)
                continue
            cn = d.get("className", "")
            if cn:
                product_classnames.add(cn)
        except (json.JSONDecodeError, OSError):
            continue

    all_loot_cn = set(rarity.keys())
    missing_cn = all_loot_cn - product_classnames

    by_zone: list[dict[str, Any]] = []
    for zone in loot_data["zones"]:
        zone_name = zone.get("zoneName", "Unknown")
        zone_items: list[str] = []
        for item in zone.get("classNames", []):
            cn = item.get("className", "")
            if cn in missing_cn:
                zone_items.append(cn)
        if zone_items:
            by_zone.append({
                "zoneName": zone_name,
                "count": len(zone_items),
                "items": sorted(zone_items),
            })

    total_loot = len(all_loot_cn)
    total_missing = len(missing_cn)
    coverage_pct = round((total_loot - total_missing) / total_loot * 100, 1) if total_loot else 0

    missing_items: list[dict[str, Any]] = []
    for cn in sorted(missing_cn):
        r = rarity.get(cn, {})
        missing_items.append({
            "className": cn,
            "tier": r.get("min_tier", 0),
            "weight": r.get("max_weight_in_lowest_tier", 0),
        })

    return {
        "by_zone": by_zone,
        "total_loot_items": total_loot,
        "total_missing": total_missing,
        "coverage_pct": coverage_pct,
        "missing_classnames": sorted(missing_cn),
        "missing_items": missing_items,
    }


def auto_balance_prices(
    products_dir: str,
    loot_path: str | None = None,
    output_dir: str | None = None,
    dry_run: bool = True,
    target_sellprice: dict[int, int] | None = None,
    markup: float = 1.3,
    stock_demand_map: dict[int, float] | None = None,
) -> dict[str, Any]:
    if loot_path is None:
        loot_path = _find_loot_path(products_dir)

    if not os.path.exists(loot_path):
        logger.error("lootzones.json not found at %s", loot_path)
        return {"error": f"lootzones.json not found at {loot_path}"}

    loot_data = load_lootzones(loot_path)
    rarity = compute_rarity(loot_data)
    target = target_sellprice or TARGET_SELLPRICE_BY_TIER

    # ── First pass: collect all sell prices per tier ──
    tier_prices: dict[int, list[int]] = {}
    entries: list[dict[str, Any]] = []
    skipped_not_loot = 0
    skipped_unpurchasable = 0
    skipped_buy_only = 0

    for fname in os.listdir(products_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(products_dir, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                d = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        if not isinstance(d, dict):
            continue

        bp = d.get("buyPrice", 0)
        if bp == -1:
            skipped_unpurchasable += 1
            continue

        sp = d.get("sellPrice", 0)
        if sp == -1:
            skipped_buy_only += 1
            continue

        cn = d.get("className", "")
        if cn not in rarity:
            skipped_not_loot += 1
            continue

        r = rarity[cn]
        tier = r["min_tier"]
        tier_prices.setdefault(tier, []).append(sp)

        entries.append({
            "fpath": fpath,
            "fname": fname,
            "cn": cn,
            "tier": tier,
            "stockSettings": d.get("stockSettings", -1),
            "old_sellPrice": sp,
            "old_buyPrice": bp,
            "rarity": r,
        })

    if not tier_prices:
        return {"total_files_scanned": 0, "files_changed": 0, "dry_run": dry_run}

    # ── Compute correction per tier ──
    corrections: dict[int, float] = {}
    for tier, prices in tier_prices.items():
        current_median = statistics.median(prices)
        tier_target = target.get(tier, 500)
        if current_median > 0 and tier_target > 0:
            corrections[tier] = tier_target / current_median
        else:
            corrections[tier] = 1.0  # no change

    # ── Second pass: apply correction ──
    changes: list[dict[str, Any]] = []
    changed_files: list[str] = []
    unchanged = 0

    for e in entries:
        tier = e["tier"]
        ssf = _stock_demand_factor(e["stockSettings"], stock_demand_map)
        correction = corrections.get(tier, 1.0)

        new_sell = max(1, int(e["old_sellPrice"] * correction * ssf))
        new_buy = max(1, int(new_sell * markup))

        if e["old_sellPrice"] != new_sell or e["old_buyPrice"] != new_buy:
            changes.append({
                "file": e["fname"],
                "className": e["cn"],
                "tier": tier,
                "stockSettings": e["stockSettings"],
                "demandFactor": round(ssf, 3),
                "weight": e["rarity"]["max_weight_in_lowest_tier"],
                "old_buyPrice": e["old_buyPrice"],
                "new_buyPrice": new_buy,
                "old_sellPrice": e["old_sellPrice"],
                "new_sellPrice": new_sell,
            })
            if not dry_run:
                d = {"buyPrice": new_buy, "sellPrice": new_sell}
                out_path = e["fpath"]
                if output_dir:
                    out_path = os.path.join(output_dir, e["fname"])
                    os.makedirs(output_dir, exist_ok=True)
                with open(e["fpath"], encoding="utf-8") as f:
                    orig = json.load(f)
                orig["buyPrice"] = new_buy
                orig["sellPrice"] = new_sell
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(orig, f, ensure_ascii=False, indent=2)
                changed_files.append(out_path)
        else:
            unchanged += 1

    stats: dict[str, Any] = {
        "total_files_scanned": len(entries) + skipped_unpurchasable
        + skipped_not_loot + skipped_buy_only,
        "files_changed": len(changes),
        "files_unchanged": unchanged,
        "skipped_unpurchasable": skipped_unpurchasable,
        "skipped_buy_only": skipped_buy_only,
        "skipped_not_in_lootzones": skipped_not_loot,
        "dry_run": dry_run,
        "changes": changes,
        "changed_files": changed_files,
        "corrections_by_tier": {str(k): round(v, 4) for k, v in corrections.items()},
    }

    if dry_run:
        print("\n  [DRY RUN] Коэффициенты коррекции по тирам:")
        for t_str, corr in sorted(stats["corrections_by_tier"].items(), key=lambda x: int(x[0])):
            t = int(t_str)
            median_before = statistics.median(tier_prices[t])
            target_val = target.get(t, 500)
            print(f"    Tier {t}: текущ. медиана={median_before:>10,} → "
                  f"цель={target_val:>6,}  correction={corr:.4f}")
        print(f"\n  [DRY RUN] Будет изменено {len(changes)} файлов:")
        for c in changes[:20]:
            print(
                f"    {c['file']:45s} tier={c['tier']} ss={c['stockSettings']}  "
                f"sellPrice: {c['old_sellPrice']:>10,} -> {c['new_sellPrice']:>10,}  "
                f"buyPrice: {c['old_buyPrice']:>10,} -> {c['new_buyPrice']:>10,}"
            )
        if len(changes) > 20:
            print(f"    ... и ещё {len(changes) - 20}")
    else:
        print(f"\n  Изменено {len(changes)} файлов в {output_dir or products_dir}")

    return stats


def _find_loot_path(products_dir: str) -> str:
    candidates = [
        os.path.join(os.path.dirname(products_dir), "..", "..", "lootzones.json"),
        os.path.join(os.path.dirname(products_dir), "..", "lootzones.json"),
        "output/profiles/lootzones.json",
        "lootzones.json",
    ]
    for p in candidates:
        resolved = os.path.normpath(p)
        if os.path.exists(resolved):
            return resolved
    return candidates[0]
