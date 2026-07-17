from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

SEVERITY_CRITICAL = "critical"
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"

ARB_CROSS_TRADER = "cross_trader"
ARB_ATTACHMENT = "attachment"
ARB_REPAIR = "repair"
ARB_MULTI_HOP = "multi_hop"

PRODUCT_ID_PATTERN = re.compile(
    r"^prod_(?P<className>.+?)_(?P<trader>.+?)_001$"
)


def _extract_trader_from_filename(fname: str) -> str:
    stem = fname
    if stem.endswith(".json"):
        stem = stem[:-5]
    m = PRODUCT_ID_PATTERN.match(stem)
    if m:
        return m.group("trader")
    return ""


def load_products(products_dir: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not os.path.isdir(products_dir):
        logger.warning("Products directory not found: %s", products_dir)
        return result

    for fname in os.listdir(products_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(products_dir, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Skipping %s: %s", fname, e)
            continue

        trader = _extract_trader_from_filename(fname)
        if not trader:
            continue

        data["_trader"] = trader
        data["_file"] = fname
        data["_productId"] = fname[:-5]
        result.append(data)

    logger.info("Loaded %d products from %s", len(result), products_dir)
    return result


def load_general_settings(
    general_settings_path: str,
) -> dict[str, Any]:
    default = {
        "acceptWorn": 1,
        "acceptDamaged": 1,
        "acceptBadlyDamaged": 1,
        "coefficientWorn": 0.8,
        "coefficientDamaged": 0.6,
        "coefficientBadlyDamaged": 0.3,
        "traders": [],
    }
    try:
        with open(general_settings_path, encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        logger.warning(
            "General settings not found at %s, using defaults", general_settings_path
        )
        default["trader_map"] = {}
        return default

    accepted = data.get("acceptedStates", {})
    traders_raw = data.get("traders", [])

    trader_map: dict[str, str] = {}
    for t in traders_raw:
        key = t.get("className", "")
        name = t.get("givenName", key)
        trader_map[key] = name

    return {
        "acceptWorn": int(accepted.get("acceptWorn", 1)),
        "acceptDamaged": int(accepted.get("acceptDamaged", 1)),
        "acceptBadlyDamaged": int(accepted.get("acceptBadlyDamaged", 1)),
        "coefficientWorn": float(accepted.get("coefficientWorn", 0.8)),
        "coefficientDamaged": float(accepted.get("coefficientDamaged", 0.6)),
        "coefficientBadlyDamaged": float(accepted.get("coefficientBadlyDamaged", 0.3)),
        "traders": traders_raw,
        "trader_map": trader_map,
    }


def _severity(profit_pct: float) -> str:
    if profit_pct >= 50:
        return SEVERITY_CRITICAL
    if profit_pct >= 20:
        return SEVERITY_HIGH
    if profit_pct >= 5:
        return SEVERITY_MEDIUM
    return SEVERITY_LOW


def _fix_suggestion_cross_trader(
    cn: str, buyer_trader: str, seller_trader: str, buy_price: int, sell_price: int,
) -> str:
    target_buy = max(1, int(sell_price * 0.9))
    target_sell = max(1, int(buy_price * 1.1))
    return (
        f"Выровнять цены {cn}: у {seller_trader} снизить sellPrice "
        f"({sell_price} -> {target_sell}), либо у {buyer_trader} поднять "
        f"buyPrice ({buy_price} -> {target_buy})"
    )


def _fix_suggestion_attachment(
    cn: str, trader: str, component_cns: list[str], profit: int,
) -> str:
    comps = ", ".join(component_cns)
    return (
        f"Проверить цены обвеса {cn} у {trader}: "
        f"сумма компонентов на {profit} руб. отличается от целого. "
        f"Компоненты: {comps}"
    )


def _fix_suggestion_repair(cn: str, trader: str) -> str:
    return (
        f"Проверить ремонт {cn} у {trader}: починка изношенного "
        f"выгоднее, чем продажа/покупка нового. "
        f"Уменьшить coefficientWorn или увеличить стоимость ремонта"
    )


def detect_cross_trader_arbitrage(
    products_by_class: dict[str, list[dict[str, Any]]],
    trader_names: dict[str, str],
    min_profit_abs: int = 100,
    min_profit_pct: float = 1.0,
) -> list[dict[str, Any]]:
    arbitrages: list[dict[str, Any]] = []

    for cn, items in products_by_class.items():
        if len(items) < 2:
            continue

        for buyer in items:
            for seller in items:
                if buyer["_trader"] == seller["_trader"]:
                    continue

                buy_price = int(buyer.get("buyPrice", 0))
                sell_price = int(seller.get("sellPrice", 0))

                if buy_price <= 0 or sell_price <= 0:
                    continue

                profit = sell_price - buy_price
                if profit < min_profit_abs:
                    continue

                profit_pct = (profit / buy_price) * 100
                if profit_pct < min_profit_pct:
                    continue

                buyer_name = trader_names.get(buyer["_trader"], buyer["_trader"])
                seller_name = trader_names.get(seller["_trader"], seller["_trader"])

                arbitrages.append({
                    "type": ARB_CROSS_TRADER,
                    "severity": _severity(profit_pct),
                    "className": cn,
                    "description": (
                        f"{cn}: купить у \u00ab{buyer_name}\u00bb за {buy_price:,}, "
                        f"продать \u00ab{seller_name}\u00bb за {sell_price:,} "
                        f"(+{profit:,} = +{profit_pct:.0f}%)"
                    ),
                    "buy_trader": buyer["_trader"],
                    "buy_trader_name": buyer_name,
                    "sell_trader": seller["_trader"],
                    "sell_trader_name": seller_name,
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "profit_per_item": profit,
                    "profit_margin_pct": round(profit_pct, 1),
                    "fix_suggestion": _fix_suggestion_cross_trader(
                        cn, buyer["_trader"], seller["_trader"],
                        buy_price, sell_price,
                    ),
                })

    arbitrages.sort(key=lambda x: -x["profit_margin_pct"])
    return arbitrages


def detect_attachment_arbitrage(
    products_by_id: dict[str, dict[str, Any]],
    trader_names: dict[str, str],
    min_profit_abs: int = 100,
) -> list[dict[str, Any]]:
    arbitrages: list[dict[str, Any]] = []
    seen: set[str] = set()

    for pid, product in products_by_id.items():
        attachments = product.get("attachments", [])
        if not attachments:
            continue

        trader = product["_trader"]
        cn = product["className"]
        product_buy_price = int(product.get("buyPrice", 0))
        product_sell_price = int(product.get("sellPrice", 0))

        attach_prices_sell: list[tuple[str, str, int]] = []
        attach_prices_buy: list[tuple[str, str, int]] = []
        resolved_all = True

        for att_pid in attachments:
            att = products_by_id.get(att_pid)
            if att is None:
                resolved_all = False
                continue
            att_cn = att["className"]
            att_sp = int(att.get("sellPrice", 0))
            att_bp = int(att.get("buyPrice", 0))
            attach_prices_sell.append((att_pid, att_cn, att_sp))
            attach_prices_buy.append((att_pid, att_cn, att_bp))

        if not resolved_all or not attach_prices_sell:
            continue

        total_attach_sell = sum(p[2] for p in attach_prices_sell)
        total_attach_buy = sum(p[2] for p in attach_prices_buy)

        key = (cn, trader, "attach")
        if key not in seen:
            seen.add(key)

            disassemble_profit = total_attach_sell - product_sell_price
            if disassemble_profit >= min_profit_abs:
                d_pct = (disassemble_profit / product_sell_price) * 100 if product_sell_price else 0
                comp_cns = [p[1] for p in attach_prices_sell]
                trader_name = trader_names.get(trader, trader)
                arbitrages.append({
                    "type": ARB_ATTACHMENT,
                    "severity": _severity(d_pct),
                    "direction": "disassemble",
                    "className": cn,
                    "trader": trader,
                    "trader_name": trader_name,
                    "description": (
                        f"{cn} у \u00ab{trader_name}\u00bb: купить целиком за {product_sell_price:,}, "
                        f"разобрать и продать обвес за {total_attach_sell:,} "
                        f"(+{disassemble_profit:,} = +{d_pct:.0f}%)"
                    ),
                    "components": comp_cns,
                    "product_buyPrice": product_buy_price,
                    "product_sellPrice": product_sell_price,
                    "total_components_sellPrice": total_attach_sell,
                    "total_components_buyPrice": total_attach_buy,
                    "profit_per_item": disassemble_profit,
                    "profit_margin_pct": round(d_pct, 1),
                    "fix_suggestion": _fix_suggestion_attachment(
                        cn, trader_name, comp_cns, disassemble_profit,
                    ),
                })

            assemble_profit = product_buy_price - total_attach_buy
            if assemble_profit >= min_profit_abs:
                a_pct = (assemble_profit / total_attach_buy) * 100 if total_attach_buy else 0
                comp_cns = [p[1] for p in attach_prices_buy]
                trader_name = trader_names.get(trader, trader)
                arbitrages.append({
                    "type": ARB_ATTACHMENT,
                    "severity": _severity(a_pct),
                    "direction": "assemble",
                    "className": cn,
                    "trader": trader,
                    "trader_name": trader_name,
                    "description": (
                        f"{cn} у \u00ab{trader_name}\u00bb: купить обвес за {total_attach_buy:,}, "
                        f"собрать и продать за {product_buy_price:,} "
                        f"(+{assemble_profit:,} = +{a_pct:.0f}%)"
                    ),
                    "components": comp_cns,
                    "product_buyPrice": product_buy_price,
                    "product_sellPrice": product_sell_price,
                    "total_components_sellPrice": total_attach_sell,
                    "total_components_buyPrice": total_attach_buy,
                    "profit_per_item": assemble_profit,
                    "profit_margin_pct": round(a_pct, 1),
                    "fix_suggestion": _fix_suggestion_attachment(
                        cn, trader_name, comp_cns, assemble_profit,
                    ),
                })

    arbitrages.sort(key=lambda x: -x["profit_margin_pct"])
    return arbitrages


def detect_repair_arbitrage(
    products: list[dict[str, Any]],
    settings: dict[str, Any],
    repair_cost_pct: float = 0.3,
    min_profit_abs: int = 100,
) -> list[dict[str, Any]]:
    arbitrages: list[dict[str, Any]] = []
    coeff_worn = settings.get("coefficientWorn", 0.8)
    coeff_damaged = settings.get("coefficientDamaged", 0.6)
    coeff_badly = settings.get("coefficientBadlyDamaged", 0.3)
    accept_worn = settings.get("acceptWorn", 1)
    accept_damaged = settings.get("acceptDamaged", 1)
    accept_badly = settings.get("acceptBadlyDamaged", 1)

    conditions: list[tuple[str, float, bool]] = [
        ("worn", coeff_worn, accept_worn),
        ("damaged", coeff_damaged, accept_damaged),
        ("badly_damaged", coeff_badly, accept_badly),
    ]

    for product in products:
        sell_price = int(product.get("sellPrice", 0))
        buy_price = int(product.get("buyPrice", 0))
        if sell_price <= 0:
            continue

        repair_estimate = int(buy_price * repair_cost_pct)
        if repair_estimate <= 0:
            continue

        for condition_name, coeff, accepted in conditions:
            if not accepted:
                continue
            degraded_sell = int(sell_price * coeff)
            price_diff = sell_price - degraded_sell

            profit = price_diff - repair_estimate
            if profit >= min_profit_abs:
                profit_pct = (profit / repair_estimate) * 100 if repair_estimate > 0 else 0
                trader_name = product.get("_trader", "?")
                arbitrages.append({
                    "type": ARB_REPAIR,
                    "severity": _severity(profit_pct),
                    "className": product["className"],
                    "trader": product["_trader"],
                    "condition": condition_name,
                    "description": (
                        f"{product['className']} ({condition_name}): "
                        f"ремонт ~{repair_estimate:,}, выгода {profit:,} "
                        f"(+{profit_pct:.0f}%)"
                    ),
                    "sellPrice_pristine": sell_price,
                    "sellPrice_degraded": degraded_sell,
                    "repair_estimate": repair_estimate,
                    "profit_per_item": profit,
                    "profit_margin_pct": round(profit_pct, 1),
                    "fix_suggestion": _fix_suggestion_repair(
                        product["className"], trader_name,
                    ),
                })

    arbitrages.sort(key=lambda x: -x["profit_margin_pct"])
    return arbitrages


def _build_price_graph(
    products_by_class: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, dict[str, int]]]:
    graph: dict[str, dict[str, dict[str, int]]] = {}
    for cn, items in products_by_class.items():
        for item in items:
            trader = item["_trader"]
            buy_price = int(item.get("buyPrice", 0))
            sell_price = int(item.get("sellPrice", 0))
            if trader not in graph:
                graph[trader] = {}
            graph[trader][cn] = {"buy": buy_price, "sell": sell_price}
    return graph


def _build_profitable_edges(
    products_by_class: dict[str, list[dict[str, Any]]],
    min_profit_abs: int = 100,
) -> dict[str, dict[str, list[tuple[str, int, int]]]]:
    edges: dict[str, dict[str, list[tuple[str, int, int]]]] = {}
    for cn, items in products_by_class.items():
        if len(items) < 2:
            continue
        for seller in items:
            s_trader = seller["_trader"]
            s_sell = int(seller.get("sellPrice", 0))
            if s_sell <= 0:
                continue
            for buyer in items:
                if buyer["_trader"] == s_trader:
                    continue
                b_buy = int(buyer.get("buyPrice", 0))
                profit = b_buy - s_sell
                if profit < min_profit_abs:
                    continue
                edges.setdefault(s_trader, {}).setdefault(cn, []).append(
                    (buyer["_trader"], s_sell, b_buy)
                )
    return edges


def _find_multi_hop_chains(
    start_trader: str,
    start_cn: str,
    edges: dict[str, dict[str, list[tuple[str, int, int]]]],
    max_depth: int = 5,
    min_profit_abs: int = 100,
    max_chains_per_start: int = 10,
    _visited_traders: set[str] | None = None,
    _depth: int = 0,
) -> list[dict[str, Any]]:
    if _visited_traders is None:
        _visited_traders = set()
    _visited_traders.add(start_trader)

    if _depth >= max_depth:
        _visited_traders.discard(start_trader)
        return []

    chains: list[dict[str, Any]] = []
    outgoing = edges.get(start_trader, {}).get(start_cn, [])

    for next_trader, s_sell, b_buy in outgoing:
        if next_trader in _visited_traders:
            continue

        profit = b_buy - s_sell
        if profit < min_profit_abs:
            continue

        chains.append({
            "type": ARB_MULTI_HOP,
            "className": start_cn,
            "chain": [
                (start_trader, "sell", s_sell),
                (next_trader, "buy", b_buy),
            ],
            "profit": profit,
            "profit_margin_pct": round((profit / s_sell) * 100, 1) if s_sell else 0,
        })

        if len(chains) >= max_chains_per_start:
            break

        sub_chains = _find_multi_hop_chains(
            next_trader, start_cn, edges,
            max_depth=max_depth,
            min_profit_abs=min_profit_abs,
            max_chains_per_start=max_chains_per_start,
            _visited_traders=_visited_traders,
            _depth=_depth + 1,
        )
        for sc in sub_chains:
            sc["chain"] = [(start_trader, "sell", s_sell)] + sc["chain"]
            total_sell = sum(p for _, act, p in sc["chain"] if act == "sell")
            total_buy = sum(p for _, act, p in sc["chain"] if act == "buy")
            sc["profit"] = total_buy - total_sell
            sc["profit_margin_pct"] = round(
                (sc["profit"] / s_sell) * 100, 1
            ) if s_sell else 0
            chains.append(sc)

            if len(chains) >= max_chains_per_start:
                break

        if len(chains) >= max_chains_per_start:
            break

    _visited_traders.discard(start_trader)
    return chains


def detect_multi_hop_arbitrage(
    products_by_class: dict[str, list[dict[str, Any]]],
    trader_names: dict[str, str],
    max_depth: int = 5,
    min_profit_abs: int = 100,
    max_chains_per_start: int = 10,
) -> list[dict[str, Any]]:
    t0 = time.monotonic()
    edges = _build_profitable_edges(products_by_class, min_profit_abs=min_profit_abs)
    all_chains: list[dict[str, Any]] = []

    for trader in edges:
        for cn in edges[trader]:
            chains = _find_multi_hop_chains(
                trader, cn, edges,
                max_depth=max_depth,
                min_profit_abs=min_profit_abs,
                max_chains_per_start=max_chains_per_start,
            )
            for c in chains:
                if len(c["chain"]) >= 4:
                    c["severity"] = _severity(c["profit_margin_pct"])
                    chain_desc_parts: list[str] = []
                    for t, action, price in c["chain"]:
                        tname = trader_names.get(t, t)
                        chain_desc_parts.append(f"{tname}({action}={price:,})")
                    c["description"] = (
                        f"{c['className']}: " + " -> ".join(chain_desc_parts)
                        + f" = +{c['profit']:,} (+{c['profit_margin_pct']:.0f}%)"
                    )
                    c["fix_suggestion"] = (
                        f"Разорвать цепочку: проверить цены {c['className']} "
                        f"у {', '.join(trader_names.get(t, t) for t, _, _ in c['chain'])}"
                    )
                    all_chains.append(c)

    elapsed = time.monotonic() - t0
    logger.info("Multi-hop detection: %.3fs, %d chains found", elapsed, len(all_chains))

    all_chains.sort(key=lambda x: -x["profit_margin_pct"])
    return all_chains


def _index_products(
    products: list[dict[str, Any]],
) -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str, dict[str, Any]],
]:
    by_class: dict[str, list[dict[str, Any]]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for p in products:
        cn = p.get("className", "")
        by_class.setdefault(cn, []).append(p)
        pid = p.get("_productId", "")
        if pid:
            by_id[pid] = p
    return by_class, by_id


def detect_arbitrages(
    products_dir: str,
    general_settings_path: str | None = None,
    repair_cost_pct: float = 0.3,
    min_profit_abs: int = 100,
    min_profit_pct: float = 1.0,
    enable_cross_trader: bool = True,
    enable_attachment: bool = True,
    enable_repair: bool = True,
    enable_multi_hop: bool = False,
    max_chain_length: int = 5,
    max_chains_per_start: int = 10,
) -> dict[str, Any]:
    products = load_products(products_dir)
    if not products:
        return {"error": "No products found", "arbitrages": [], "stats": {}}

    if general_settings_path and not os.path.exists(general_settings_path):
        general_settings_path = None

    settings = load_general_settings(general_settings_path) if general_settings_path else load_general_settings("")
    trader_names: dict[str, str] = settings.get("trader_map", {})

    by_class, by_id = _index_products(products)

    all_arbitrages: list[dict[str, Any]] = []

    if enable_cross_trader:
        logger.info("Detecting cross-trader arbitrage...")
        all_arbitrages.extend(
            detect_cross_trader_arbitrage(
                by_class, trader_names,
                min_profit_abs=min_profit_abs,
                min_profit_pct=min_profit_pct,
            )
        )

    if enable_attachment:
        logger.info("Detecting attachment arbitrage...")
        all_arbitrages.extend(
            detect_attachment_arbitrage(
                by_id, trader_names,
                min_profit_abs=min_profit_abs,
            )
        )

    if enable_repair:
        logger.info("Detecting repair arbitrage...")
        all_arbitrages.extend(
            detect_repair_arbitrage(
                products, settings,
                repair_cost_pct=repair_cost_pct,
                min_profit_abs=min_profit_abs,
            )
        )

    if enable_multi_hop:
        logger.info("Detecting multi-hop arbitrage...")
        all_arbitrages.extend(
            detect_multi_hop_arbitrage(
                by_class, trader_names,
                max_depth=max_chain_length,
                min_profit_abs=min_profit_abs,
                max_chains_per_start=max_chains_per_start,
            )
        )

    by_severity: dict[str, int] = {}
    for a in all_arbitrages:
        sev = a.get("severity", SEVERITY_LOW)
        by_severity[sev] = by_severity.get(sev, 0) + 1

    by_trader: dict[str, dict[str, int]] = {}
    for a in all_arbitrages:
        if a["type"] in (ARB_ATTACHMENT, ARB_REPAIR):
            t = a.get("trader", "?")
            by_trader.setdefault(t, {"arbitrages_as_buy": 0, "arbitrages_as_sell": 0})
            by_trader[t]["arbitrages_as_sell"] = by_trader[t].get("arbitrages_as_sell", 0) + 1
        elif a["type"] in (ARB_CROSS_TRADER, ARB_MULTI_HOP):
            buy_t = a.get("buy_trader", "?")
            sell_t = a.get("sell_trader", "?")
            by_trader.setdefault(buy_t, {"arbitrages_as_buy": 0, "arbitrages_as_sell": 0})
            by_trader[buy_t]["arbitrages_as_buy"] = by_trader[buy_t].get("arbitrages_as_buy", 0) + 1
            if sell_t:
                by_trader.setdefault(sell_t, {"arbitrages_as_buy": 0, "arbitrages_as_sell": 0})
                by_trader[sell_t]["arbitrages_as_sell"] = by_trader[sell_t].get("arbitrages_as_sell", 0) + 1

    severity_order = [SEVERITY_CRITICAL, SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW]
    all_arbitrages.sort(
        key=lambda x: (
            severity_order.index(x.get("severity", SEVERITY_LOW))
            if x.get("severity") in severity_order
            else 99,
            -x.get("profit_margin_pct", 0),
        )
    )

    total_profit = sum(a.get("profit_per_item", 0) for a in all_arbitrages)

    return {
        "total_arbitrages": len(all_arbitrages),
        "by_severity": by_severity,
        "total_profit_if_all_done_once": total_profit,
        "arbitrages": all_arbitrages,
        "by_trader": by_trader,
        "stats": {
            "files_scanned": len(products),
            "unique_classnames": len(by_class),
            "unique_traders": len(set(p["_trader"] for p in products)),
            "settings_loaded": general_settings_path is not None,
            "modes": {
                "cross_trader": enable_cross_trader,
                "attachment": enable_attachment,
                "repair": enable_repair,
                "multi_hop": enable_multi_hop,
            },
        },
    }


def print_arbitrage_report(result: dict[str, Any]) -> None:
    if "error" in result:
        print(f"\n  \u041e\u0448\u0438\u0431\u043a\u0430: {result['error']}\n")
        return

    arbitrages = result.get("arbitrages", [])
    by_severity = result.get("by_severity", {})
    stats = result.get("stats", {})

    print("\n" + "=" * 70)
    print("   \u0414\u0415\u0422\u0415\u041a\u0422\u041e\u0420 \u042d\u041a\u041e\u041d\u041e\u041c\u0418\u0427\u0415\u0421\u041a\u041e\u0413\u041e \u0410\u0420\u0411\u0418\u0422\u0420\u0410\u0416\u0410")
    print("=" * 70)

    print(f"\n  \u041f\u0440\u043e\u0441\u043a\u0430\u043d\u0438\u0440\u043e\u0432\u0430\u043d\u043e: {stats.get('files_scanned', 0)} \u0444\u0430\u0439\u043b\u043e\u0432, "
          f"{stats.get('unique_classnames', 0)} \u043f\u0440\u0435\u0434\u043c\u0435\u0442\u043e\u0432, "
          f"{stats.get('unique_traders', 0)} \u0442\u043e\u0440\u0433\u043e\u0432\u0446\u0435\u0432")

    print(f"\n  \u0412\u0441\u0435\u0433\u043e \u043d\u0430\u0439\u0434\u0435\u043d\u043e \u0430\u0440\u0431\u0438\u0442\u0440\u0430\u0436\u0435\u0439: {result['total_arbitrages']}")
    if by_severity:
        print(
            f"    \u041a\u0440\u0438\u0442\u0438\u0447\u0435\u0441\u043a\u0438\u0445: {by_severity.get(SEVERITY_CRITICAL, 0)}\n"
            f"    \u0412\u044b\u0441\u043e\u043a\u0438\u0445:     {by_severity.get(SEVERITY_HIGH, 0)}\n"
            f"    \u0421\u0440\u0435\u0434\u043d\u0438\u0445:     {by_severity.get(SEVERITY_MEDIUM, 0)}\n"
            f"    \u041d\u0438\u0437\u043a\u0438\u0445:      {by_severity.get(SEVERITY_LOW, 0)}"
        )
    if result.get("total_profit_if_all_done_once", 0) > 0:
        print(f"\n  \u0421\u0443\u043c\u043c\u0430\u0440\u043d\u044b\u0439 \u043f\u0440\u043e\u0444\u0438\u0442 (\u0440\u0430\u0437\u043e\u0432\u0430\u044f \u043f\u0440\u043e\u043a\u0440\u0443\u0442\u043a\u0430 \u0432\u0441\u0435\u0445): "
              f"{result['total_profit_if_all_done_once']:,} \u0440\u0443\u0431")

    severity_icons = {
        SEVERITY_CRITICAL: "\U0001f534",
        SEVERITY_HIGH: "\U0001f7e0",
        SEVERITY_MEDIUM: "\U0001f7e1",
        SEVERITY_LOW: "\u26aa",
    }

    for a in arbitrages:
        icon = severity_icons.get(a.get("severity", SEVERITY_LOW), "\u26aa")
        print(
            f"\n  {icon} [{a['type']}] {a.get('severity', '').upper()}: "
            f"{a['className']}"
        )
        print(f"    {a['description']}")
        print(f"    \u0424\u0438\u043a\u0441: {a.get('fix_suggestion', '')}")

    by_trader = result.get("by_trader", {})
    if by_trader:
        print(f"\n  {'='*50}")
        print("  \u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430 \u043f\u043e \u0442\u043e\u0440\u0433\u043e\u0432\u0446\u0430\u043c:")
        print(f"  {'='*50}")
        for t_key, counts in sorted(by_trader.items()):
            total = counts.get("arbitrages_as_buy", 0) + counts.get("arbitrages_as_sell", 0)
            if total > 0:
                print(
                    f"    {t_key:20s}  \u043f\u043e\u043a\u0443\u043f\u043a\u0430: {counts.get('arbitrages_as_buy', 0):>3}  "
                    f"\u043f\u0440\u043e\u0434\u0430\u0436\u0430: {counts.get('arbitrages_as_sell', 0):>3}  \u0432\u0441\u0435\u0433\u043e: {total}"
                )

    print("\n" + "=" * 70 + "\n")
