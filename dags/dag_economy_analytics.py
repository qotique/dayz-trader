from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from airflow.decorators import dag, task, task_group
from airflow.operators.empty import EmptyOperator

logger = logging.getLogger(__name__)

OUTPUT_DIR = "/opt/airflow/output/profiles/TraderX"

default_args = {
    "owner": "trader",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


@dag(
    schedule="0 8 * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["dayz", "trader", "analytics", "ml"],
)
def economy_analytics():

    @task
    def analyze_prices() -> dict[str, Any]:
        """
        Economic analysis: tier distribution, anomalies, balance.
        """
        from ml_price_analysis import analyze_economy, auto_balance_prices

        products_dir = f"{OUTPUT_DIR}/TraderXConfig/Products"
        loot_path = "/opt/airflow/lootzones.json"

        result = analyze_economy(loot_path=loot_path, products_dir=products_dir)

        balance = auto_balance_prices(
            products_dir=products_dir,
            loot_path=loot_path,
            dry_run=True,
        )

        return {"economy": result, "balance": balance}

    @task
    def detect_arbitrage() -> dict[str, Any]:
        """
        Searching for arbitrage opportunities between traders.
        """
        from ml_arbitrage_detector import detect_arbitrages

        return detect_arbitrages(
            products_dir=f"{OUTPUT_DIR}/TraderXConfig/Products",
            general_settings_path=f"{OUTPUT_DIR}/TraderXConfig/TraderXGeneralSettings.json",
            enable_cross_trader=True,
            enable_attachment=True,
            enable_repair=True,
            enable_multi_hop=False,
        )

    @task
    def analyze_attachments(data: dict[str, Any]) -> dict[str, Any]:
        """
        Analysis of missing attachments.
        """
        from ml_attachment_analytics import analyze_missing_attachments
        from trader_concept import create_gspread_client, load_data, open_sheet
        import tomllib

        cfg_path = Path("/opt/airflow/config.toml")
        with open(cfg_path, "rb") as f:
            cfg = tomllib.load(f)

        google = cfg["google"]
        client = create_gspread_client(google["credentials_file"])
        sheet = open_sheet(client, google["spreadsheet_id"])
        trader_names: list[str] = []
        raw_data = load_data(sheet, trader_names)

        return analyze_missing_attachments(
            raw_data["products_all"],
            raw_data["traders_raw"],
        )

    @task
    def write_reports(
        price_result: dict[str, Any],
        arbitrage_result: dict[str, Any],
        attachment_result: dict[str, Any],
    ) -> str:
        """
        Writing reports to Google Sheets.
        """
        import tomllib
        from ml_sheet_reports import write_all_reports
        from trader_concept import create_gspread_client, open_sheet

        cfg_path = Path("/opt/airflow/config.toml")
        with open(cfg_path, "rb") as f:
            cfg = tomllib.load(f)

        google = cfg["google"]
        client = create_gspread_client(google["credentials_file"])
        sheet = open_sheet(client, google["spreadsheet_id"])

        write_all_reports(
            spreadsheet=sheet,
            economy_result=price_result.get("economy"),
            balance_stats=price_result.get("balance"),
            arbitrage_result=arbitrage_result,
        )

        return "Reports written to Google Sheets"

    price_res = analyze_prices()
    arb_res = detect_arbitrage()
    att_res = analyze_attachments(price_res)

    write_reports(price_res, arb_res, att_res)


economy_analytics()