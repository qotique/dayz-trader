from __future__ import annotations

import logging
from typing import Any

from models import input as input_models
from models._utils import translit_key

logger = logging.getLogger(__name__)


def build_trader_category_matrix(
    traders_raw: list[input_models.Trader],
    products_all: list[input_models.Product],
    categories_template: list[input_models.Category],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    trader_rows: list[dict[str, Any]] = []
    category_names = sorted({c.name for c in categories_template})
    trader_keys: list[str] = []

    for trader in traders_raw:
        trader_key = translit_key(trader.givenName)
        trader_keys.append(trader_key)

        trader_product_ids = {
            p.className
            for p in products_all
            if p.trader_access.get(trader_key, False)
        }

        row: dict[str, Any] = {
            "trader_key": trader_key,
            "trader_name": trader.givenName,
        }
        for cat_name in category_names:
            count = sum(
                1
                for p in products_all
                if p.className in trader_product_ids and p.category == cat_name
            )
            row[cat_name] = count
        row["total"] = sum(row[cn] for cn in category_names)
        trader_rows.append(row)

    return trader_rows, category_names, trader_keys


def normalize_matrix(
    trader_rows: list[dict[str, Any]],
    category_names: list[str],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in trader_rows:
        total = row["total"]
        normalized = dict(row)
        if total > 0:
            for cat in category_names:
                normalized[cat] = round(row[cat] / total, 4)
        result.append(normalized)
    return result


def find_optimal_k(features: Any, max_k: int = 8) -> int:
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    n_samples = features.shape[0]
    if n_samples < 2:
        return 1
    max_k = min(max_k, n_samples - 1)
    if max_k < 2:
        return 1

    best_k = 2
    best_score = -1.0
    for k in range(2, max_k + 1):
        km = KMeans(n_clusters=k, random_state=42, n_init="auto")
        labels = km.fit_predict(features)
        score = silhouette_score(features, labels)
        if score > best_score:
            best_score = score
            best_k = k
    return best_k


def _compute_distinctive_categories(
    centroid: Any,
    category_names: list[str],
    global_centroid: Any,
    top_n: int = 3,
) -> list[dict[str, Any]]:
    deviation = centroid - global_centroid
    cat_devs = [(idx, float(deviation[idx])) for idx in range(len(centroid))]
    cat_devs.sort(key=lambda x: -x[1])

    result = [
        {"name": category_names[idx], "deviation": round(dev, 3)}
        for idx, dev in cat_devs[:top_n]
        if dev > 0
    ]

    if not result:
        cat_vals = [(idx, float(centroid[idx])) for idx in range(len(centroid))]
        cat_vals.sort(key=lambda x: -x[1])
        result = [
            {"name": category_names[idx], "deviation": 0.0}
            for idx, _ in cat_vals[:top_n]
            if float(centroid[idx]) > 0
        ]

    return result


def _cluster_label_key(distinctive: list[dict[str, Any]]) -> str:
    return " | ".join(sorted(c["name"] for c in distinctive))


def _format_cluster_name(
    distinctive: list[dict[str, Any]],
    cluster_names: dict[str, str] | None,
) -> str:
    if not distinctive:
        return "Разное"
    if cluster_names:
        key = _cluster_label_key(distinctive)
        custom = cluster_names.get(key)
        if custom:
            return custom
    return " | ".join(f'"{c["name"]}"' for c in distinctive)


def cluster_traders(
    traders_raw: list[input_models.Trader],
    products_all: list[input_models.Product],
    categories_template: list[input_models.Category],
    n_clusters: int | None = None,
    cluster_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_samples, silhouette_score

    if len(traders_raw) < 2:
        return {
            "status": "skipped",
            "reason": "Need at least 2 traders for clustering",
            "clusters": {},
            "outliers": [],
        }

    trader_rows, category_names, trader_keys = build_trader_category_matrix(
        traders_raw, products_all, categories_template
    )

    normalized = normalize_matrix(trader_rows, category_names)

    import numpy as np

    features = np.array(
        [[row[cn] for cn in category_names] for row in normalized]
    )

    if features.sum() == 0:
        return {
            "status": "skipped",
            "reason": "All traders have zero products",
            "clusters": {},
            "outliers": [],
        }

    if n_clusters is None:
        n_clusters = find_optimal_k(features, max_k=min(8, len(traders_raw) - 1))

    n_clusters = max(2, min(n_clusters, len(traders_raw) - 1))

    km = KMeans(n_clusters=n_clusters, random_state=42, n_init="auto")
    labels = km.fit_predict(features)

    silhouette = None
    if n_clusters < len(traders_raw):
        try:
            silhouette = float(silhouette_score(features, labels))
        except Exception:
            silhouette = None

    global_centroid = np.mean(km.cluster_centers_, axis=0)

    all_silhouettes = silhouette_samples(features, labels)

    clusters: dict[int, dict[str, Any]] = {}
    for cluster_id in range(n_clusters):
        mask = labels == cluster_id
        indices = [i for i in range(len(traders_raw)) if mask[i]]
        members = [
            {
                "name": traders_raw[i].givenName,
                "key": trader_keys[i],
                "total_products": trader_rows[i]["total"],
                "silhouette": float(all_silhouettes[i]),
            }
            for i in indices
        ]

        centroid = km.cluster_centers_[cluster_id]

        distinctive = _compute_distinctive_categories(
            centroid, category_names, global_centroid, top_n=3
        )

        name = _format_cluster_name(distinctive, cluster_names)

        clusters[cluster_id] = {
            "name": name,
            "distinctive": distinctive,
            "size": len(members),
            "members": members,
            "centroid": centroid.tolist(),
        }

    silhouette_threshold = 0.2
    outliers = [
        m
        for c in clusters.values()
        for m in c["members"]
        if m["silhouette"] < silhouette_threshold
    ]

    return {
        "status": "ok",
        "n_clusters": n_clusters,
        "n_traders": len(traders_raw),
        "silhouette_score": silhouette,
        "clusters": clusters,
        "outliers": outliers,
        "category_names": category_names,
    }


def print_cluster_report(result: dict[str, Any]) -> None:
    if result["status"] == "skipped":
        logger.warning("Кластеризация пропущена: %s", result.get("reason", ""))
        return

    clusters = result["clusters"]
    silhouette = result.get("silhouette_score")
    outliers = result.get("outliers", [])

    print("\n" + "=" * 60)
    print("   КЛАСТЕРИЗАЦИЯ ТОРГОВЦЕВ ПО АССОРТИМЕНТУ")
    print("=" * 60)

    if silhouette is not None:
        print(f"\n  Общий silhouette score: {silhouette:.3f}")
    print(f"  Количество кластеров: {result['n_clusters']}")
    print(f"  Количество торговцев: {result['n_traders']}")
    print()

    sorted_clusters = sorted(
        clusters.values(), key=lambda c: c["name"]
    )

    for cluster in sorted_clusters:
        name = cluster["name"]
        distinctive = cluster.get("distinctive", [])
        d_str = ", ".join(
            f'"{d["name"]}" {d["deviation"]:+.2f}' for d in distinctive
        )
        print(f"  [{name}]")
        print(f"    distinctive: {d_str}")

        members = sorted(cluster["members"], key=lambda m: -m["silhouette"])
        for m in members:
            sil = m["silhouette"]
            sil_mark = "  " if sil >= 0.3 else " ⚠"
            print(
                f"    {sil_mark} {m['name']:20s}  "
                f"(товаров: {m['total_products']:3d}, "
                f"silhouette: {sil:.2f})"
            )

        avg_products = sum(m["total_products"] for m in members) / len(members) if members else 0
        print(f"    — среднее товаров: {avg_products:.0f}, торговцев: {len(members)}")
        print()

    if outliers:
        print("  ⚠  ВЫБРОСЫ (проверить ассортимент):")
        for m in outliers:
            print(
                f"    {m['name']:20s}  "
                f"(silhouette: {m['silhouette']:.2f})"
            )
        print()

    print("=" * 60 + "\n")



