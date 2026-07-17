from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from airflow.decorators import dag, task
from trader_data import deserialize_data, serialize_data

logger = logging.getLogger(__name__)
OUTPUT_DIR = "/opt/airflow/output/profiles/TraderX"

default_args = {
    "owner": "trader",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


@dag(
    schedule="0 6 * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["dayz", "trader", "configs"],
)
def generate_trader_configs():

    @task
    def ensure_dirs() -> None:
        from trader_concept import ensure_output_dirs

        ensure_output_dirs(OUTPUT_DIR)

    @task
    def fetch_google_sheets() -> str:
        """
        Loads data, serializes it to a file, and returns the path.
        """
        import tomllib

        from trader_concept import create_gspread_client, load_data, open_sheet

        with open("/opt/airflow/config.toml", "rb") as f:
            cfg = tomllib.load(f)

        google = cfg["google"]
        client = create_gspread_client(google["credentials_file"])
        sheet = open_sheet(client, google["spreadsheet_id"])

        trader_names: list[str] = []
        data = load_data(sheet, trader_names)
        data["_trader_names"] = trader_names

        data_path = "/tmp/trader_input_data.json"
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(serialize_data(data), f, ensure_ascii=False)

        logger.info(
            "Data saved to %s (%d traders, %d products)",
            data_path,
            len(data["traders_raw"]),
            len(data["products_all"]),
        )
        return data_path

    @task
    def get_trader_dicts(data_path: str) -> list[dict[str, Any]]:
        """
        Reads data and returns a list of traders for mapping.
        """
        with open(data_path) as f:
            data = json.load(f)
        return data["traders_raw"]

    @task
    def process_single_trader_task(
        trader_dict: dict[str, Any],
        data_path: str,
    ) -> dict[str, Any] | None:
        """
        Single trader: Products + Stock + Categories.
        """
        from models import input as input_models
        from trader_concept import process_single_trader

        with open(data_path) as f:
            data = json.load(f)
        full = deserialize_data(data)

        trader = input_models.Trader.model_validate(trader_dict)

        return process_single_trader(
            trader=trader,
            products_all=full["products_all"],
            prices_map=full["prices_map"],
            categories_template=full["categories_template"],
            loadouts_by_trader=full["loadouts_by_trader"],
            output_dir=OUTPUT_DIR,
        )

    @task
    def collect_results(trader_results: list[dict[str, Any] | None]) -> list[dict[str, Any]]:
        """
        Collect, filter None.
        """
        return [r for r in trader_results if r is not None]

    @task
    def save_general_settings(data_path: str, output_traders: list[dict[str, Any]]) -> str:
        from trader_concept import save_general_settings as save_gs

        with open(data_path) as f:
            data = json.load(f)
        full = deserialize_data(data)

        save_gs(
            general_settings=full["general_settings"],
            accepted_states=full["accepted_states"],
            licenses=full["licenses"],
            output_traders=output_traders,
            output_dir=OUTPUT_DIR,
        )
        return f"{OUTPUT_DIR}/TraderXConfig/TraderXGeneralSettings.json"

    @task
    def save_currency_settings(data_path: str) -> str:
        from trader_concept import save_currency_settings as save_cs

        with open(data_path) as f:
            data = json.load(f)
        full = deserialize_data(data)

        save_cs(
            currency_types_raw=full["currency_types_raw"],
            currencies_raw=full["currencies_raw"],
            output_dir=OUTPUT_DIR,
        )
        return f"{OUTPUT_DIR}/TraderXConfig/TraderXCurrencySettings.json"

    @task
    def validate_output() -> dict[str, Any]:
        stats = {"total_files": 0, "valid": 0, "invalid": 0, "errors": []}
        for json_file in Path(OUTPUT_DIR).rglob("*.json"):
            stats["total_files"] += 1
            try:
                with open(json_file) as f:
                    json.load(f)
                stats["valid"] += 1
            except (json.JSONDecodeError, OSError) as e:
                stats["invalid"] += 1
                stats["errors"].append(f"{json_file.name}: {e}")

        if stats["invalid"] > 0:
            raise ValueError(
                f"Невалидных: {stats['invalid']}/{stats['total_files']}: "
                + "; ".join(stats["errors"][:5])
            )
        return stats

    ensure_dirs()
    data_path = fetch_google_sheets()
    trader_list = get_trader_dicts(data_path)

    trader_results = process_single_trader_task.partial(
        data_path=data_path,
    ).expand(
        trader_dict=trader_list,
    )

    collected = collect_results(trader_results)

    gs_path = save_general_settings(data_path, collected)
    cs_path = save_currency_settings(data_path)

    validate_output().set_upstream([gs_path, cs_path])


generate_trader_configs()
