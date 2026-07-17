from __future__ import annotations

import json
import logging
import os
import re
import statistics
import tempfile
from typing import Any

from models._utils import translit_key

logger = logging.getLogger(__name__)


def fetch_stock_via_ftp(
    host: str,
    user: str = "anonymous",
    password: str = "",
    remote_path: str = "/TraderX/TraderXDatabase/Stock",
    local_path: str | None = None,
    use_tls: bool = False,
    progress_interval: int = 500,
) -> str:
    if local_path is None:
        local_path = tempfile.mkdtemp(prefix="traderx_stock_")

    import ftplib
    import time

    logger.info("Подключение к FTP %s как %s ...", host, user)
    ftp_cls = ftplib.FTP_TLS if use_tls else ftplib.FTP
    ftp = ftp_cls(host, user, password)
    start_time = time.time()
    try:
        ftp.cwd(remote_path)

        files: list[str] = []
        ftp.retrlines("NLST", files.append)
        json_files = [f for f in files if f.endswith(".json")]
        total = len(json_files)
        logger.info("Найдено %d Stock файлов. Загрузка...", total)

        for i, fname in enumerate(json_files, 1):
            local_fpath = os.path.join(local_path, fname)
            with open(local_fpath, "wb") as f:
                ftp.retrbinary(f"RETR {fname}", f.write)
            if i % progress_interval == 0 or i == total:
                elapsed = time.time() - start_time
                logger.info("  %d / %d файлов (%.0f сек)", i, total, elapsed)
    finally:
        ftp.quit()

    elapsed = time.time() - start_time
    logger.info(
        "Загружено %d Stock файлов в %s (%.0f сек)",
        len(json_files), local_path, elapsed,
    )
    return local_path


def load_stock_files(stock_dir: str) -> dict[str, int]:
    result: dict[str, int] = {}
    if not os.path.isdir(stock_dir):
        logger.warning("Stock directory not found: %s", stock_dir)
        return result

    for fname in os.listdir(stock_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(stock_dir, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                data = json.load(f)
            result[data["productId"]] = int(data["stock"])
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Skipping %s: %s", fname, e)

    return result


def load_product_info(products_dir: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not os.path.isdir(products_dir):
        logger.warning("Products directory not found: %s", products_dir)
        return result

    for fname in os.listdir(products_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(products_dir, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                data = json.load(f)
            pid = fname[:-5]
            result[pid] = {
                "maxStock": int(data.get("maxStock", 0)),
                "stockSettings": int(data.get("stockSettings", 0)),
                "className": str(data.get("className", "")),
            }
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Skipping %s: %s", fname, e)

    return result


def load_traders(general_settings_path: str) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        with open(general_settings_path, encoding="utf-8") as f:
            data = json.load(f)
        for t in data.get("traders", []):
            given = t.get("givenName", "")
            key = translit_key(given) if given else ""
            if key:
                result[key] = given
    except (json.JSONDecodeError, KeyError, OSError) as e:
        logger.warning("Could not load traders from %s: %s", general_settings_path, e)
    return result


def extract_trader_key(product_id: str, class_name: str) -> str:
    stem = product_id
    if stem.startswith("prod_"):
        stem = stem[5:]

    class_lower = class_name.lower()

    if class_lower in stem:
        idx = stem.index(class_lower)
        rest = stem[idx + len(class_lower):]
        if rest.startswith("_"):
            rest = rest[1:]
        rest = re.sub(r"_\d{3}$", "", rest)
        return rest

    return ""


def compute_sell_through_rate(current_stock: int, max_stock: int) -> float:
    if max_stock <= 0:
        return 0.0
    return max(0.0, min(1.0, (max_stock - current_stock) / max_stock))


def detect_outliers_zscore(
    values: list[float], threshold: float = 2.0
) -> list[int]:
    if len(values) < 2:
        return []
    mean = statistics.mean(values)
    stdev = statistics.stdev(values)
    if stdev == 0:
        return []
    return [
        i for i, v in enumerate(values)
        if abs((v - mean) / stdev) > threshold
    ]


def analyze_stock(
    stock_data: dict[str, int],
    product_info: dict[str, dict[str, Any]],
    traders: dict[str, str] | None = None,
    outlier_threshold: float = 2.0,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []

    for pid, current_stock in stock_data.items():
        info = product_info.get(pid)
        if info is None:
            continue

        max_stock = info["maxStock"]
        stock_settings = info["stockSettings"]
        class_name = info["className"]

        sell_through = compute_sell_through_rate(current_stock, max_stock)
        trader_key = extract_trader_key(pid, class_name)
        trader_name = traders.get(trader_key, trader_key) if traders else trader_key

        items.append({
            "product_id": pid,
            "className": class_name,
            "trader": trader_name,
            "maxStock": max_stock,
            "currentStock": current_stock,
            "stockSettings": stock_settings,
            "sellThrough": round(sell_through, 3),
        })

    by_settings: dict[int, list[dict[str, Any]]] = {}
    for item in items:
        by_settings.setdefault(item["stockSettings"], []).append(item)

    outliers: list[dict[str, Any]] = []
    for s_val, group in by_settings.items():
        rates = [it["sellThrough"] for it in group]
        outlier_indices = detect_outliers_zscore(rates, outlier_threshold)
        for idx in outlier_indices:
            o = dict(group[idx])
            o["group"] = s_val
            outliers.append(o)

    summary_by_settings: dict[str, dict[str, Any]] = {}
    for k, v in sorted(by_settings.items()):
        rates = [it["sellThrough"] for it in v]
        summary_by_settings[str(k)] = {
            "count": len(v),
            "mean_sell_through": round(statistics.mean(rates), 3) if v else 0.0,
        }

    return {
        "total_items": len(items),
        "items_by_settings": summary_by_settings,
        "items": items,
        "outliers": outliers,
        "threshold": outlier_threshold,
    }


def print_stock_report(result: dict[str, Any]) -> None:
    items = result["items"]
    outliers = result.get("outliers", [])

    by_settings: dict[int, list[dict[str, Any]]] = {}
    for item in items:
        by_settings.setdefault(item["stockSettings"], []).append(item)

    print("\n" + "=" * 60)
    print("   ИНВЕНТАРНАЯ АНАЛИТИКА (Stock Health Report)")
    print("=" * 60)
    print(f"\n  Всего товаров: {result['total_items']}")
    for s_val, group in sorted(by_settings.items()):
        print(f"    stockSettings={s_val}: {len(group)} товаров")
    print()

    for s_val, group in sorted(by_settings.items()):
        sorted_group = sorted(group, key=lambda x: -x["sellThrough"])
        high_demand = [it for it in sorted_group if it["sellThrough"] > 0.8][:10]
        dead_stock = [it for it in sorted_group if it["sellThrough"] < 0.05][:10]

        label = f"stockSettings={s_val}"
        if s_val == 0:
            label += " (только игроки)"
        elif s_val == 98:
            label += " (авторасход + приём)"

        print(f"--- {label} ---")

        if high_demand:
            print("  Быстро расходуемые (sell-through > 80%):")
            for it in high_demand:
                print(f"    {it['className']:35s} @ {it['trader']:20s}"
                      f"  stock: {it['currentStock']:4d}/{it['maxStock']:<4d}"
                      f"  ({it['sellThrough']*100:.0f}%)")
        else:
            print("  Нет товаров с высоким расходом.")

        if dead_stock:
            print("  Мёртвый сток (sell-through < 5%):")
            for it in dead_stock:
                print(f"    {it['className']:35s} @ {it['trader']:20s}"
                      f"  stock: {it['currentStock']:4d}/{it['maxStock']:<4d}")

        print()

    if outliers:
        print("  ⚠  АНОМАЛИИ (выбросы по sell-through):")
        for it in sorted(outliers, key=lambda x: -abs(x["sellThrough"] - 0.5)):
            print(f"    {it['className']:35s} @ {it['trader']:20s}"
                  f"  sell-through: {it['sellThrough']*100:.0f}%"
                  f"  (group: stockSettings={it['group']})")
        print()

    print("=" * 60 + "\n")
