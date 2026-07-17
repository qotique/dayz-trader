from __future__ import annotations

from datetime import datetime, timedelta
from airflow.decorators import dag, task
from pathlib import Path

from airflow.operators.trigger_dagrun import TriggerDagRunOperator

OUTPUT_DIR = "/opt/airflow/output/profiles/TraderX"


@dag(
    schedule="0 4 * * 1",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    default_args={
        "owner": "trader",
        "retries": 1,
        "retry_delay": timedelta(minutes=10),
    },
    tags=["dayz", "trader", "full-sync"],
)
def full_sync():

    trigger_generate = TriggerDagRunOperator(
        task_id="trigger_generate_configs",
        trigger_dag_id="generate_trader_configs",
        wait_for_completion=True,
        trigger_rule="all_success",
    )

    trigger_analytics = TriggerDagRunOperator(
        task_id="trigger_economy_analytics",
        trigger_dag_id="economy_analytics",
        wait_for_completion=True,
        trigger_rule="all_success",
    )

    @task
    def deploy_to_server() -> str:
        """
        Deploy configs on FTP-server.
        """
        import ftplib
        import os
        from pathlib import Path
        import tomllib

        cfg_path = Path("/opt/airflow/config.toml")
        with open(cfg_path, "rb") as f:
            cfg = tomllib.load(f)

        stock_cfg = cfg.get("stock_report", {})
        ftp_host = stock_cfg.get("ftp_host", "")
        ftp_user = stock_cfg.get("ftp_user", "")
        remote_base = "/Server/profiles/TraderX"

        if not ftp_host:
            return "FTP not configured, skipping deploy"

        ftp = ftplib.FTP(ftp_host)
        ftp.login(ftp_user)

        output_path = Path(OUTPUT_DIR)
        for local_file in output_path.rglob("*.json"):
            relative = local_file.relative_to(output_path)
            remote_path = f"{remote_base}/{relative}"
            remote_dir = str(Path(remote_path).parent)

            try:
                ftp.cwd(remote_dir)
            except ftplib.error_perm:
                ftp.mkd(remote_dir)

            with open(local_file, "rb") as f:
                ftp.storbinary(f"STOR {remote_path}", f)

        ftp.quit()
        return f"Deployed {len(list(output_path.rglob('*.json')))} files"

    trigger_generate >> trigger_analytics >> deploy_to_server()


full_sync()