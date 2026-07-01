from __future__ import annotations

import json
import logging
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

import click

from trader_concept import (
    ensure_output_dirs,
    process_traders,
    save_currency_settings,
    save_general_settings,
)
from trader_concept import (
    main as main_gsheets,
)

logger = logging.getLogger(__name__)

SHEET_NAMES = [
    "Базовые настройки",
    "Настройки состояния",
    "Лицензии",
    "Торговцы",
    "Одежда торговцев",
    "Категории",
    "Товары",
    "Цены",
    "Валюта",
    "Наличка",
]

SHEET_TO_MODEL = {
    "Базовые настройки": "general_settings",
    "Настройки состояния": "accepted_states",
    "Лицензии": "licenses",
    "Торговцы": "traders_raw",
    "Одежда торговцев": "traders_loadouts",
    "Категории": "categories_template",
    "Товары": "products_all",
    "Цены": "prices_raw",
    "Валюта": "currency_types_raw",
    "Наличка": "currencies_raw",
}


# ── Local Input ────────────────────────────────────────────────────────────────


def load_csv_dir(input_dir: str) -> dict[str, list[dict[str, Any]]]:
    """Read all CSV files from a directory, return dict of sheet_name → records."""
    import csv

    result: dict[str, list[dict[str, Any]]] = {}
    input_path = Path(input_dir)

    if not input_path.is_dir():
        raise click.ClickException(f"Папка не найдена: {input_dir}")

    for sheet_name in SHEET_NAMES:
        csv_file = input_path / f"{sheet_name}.csv"
        if not csv_file.exists():
            logger.warning("Файл не найден, пропускаем: %s", csv_file)
            continue
        with open(csv_file, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows: list[dict[str, Any]] = []
            for row in reader:
                cleaned = {k.strip(): v.strip() for k, v in row.items() if k}
                rows.append(cleaned)
            result[sheet_name] = rows
            logger.info("Загружено %d записей из %s", len(rows), csv_file.name)

    missing = [n for n in SHEET_NAMES if n not in result]
    if missing:
        logger.warning("Отсутствуют листы: %s", ", ".join(missing))

    return result


def load_excel(filepath: str) -> dict[str, list[dict[str, Any]]]:
    """Read an Excel (.xlsx) file, return dict of sheet_name → records."""
    try:
        import openpyxl
    except ImportError:
        raise click.ClickException(
            "Для работы с Excel нужен пакет openpyxl. Установите: pip install openpyxl"
        )

    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    result: dict[str, list[dict[str, Any]]] = {}

    for sheet_name in SHEET_NAMES:
        if sheet_name not in wb.sheetnames:
            logger.warning("Лист не найден, пропускаем: %s", sheet_name)
            continue
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows or not rows[0]:
            continue
        headers = [str(h).strip() if h is not None else "" for h in rows[0]]
        data_rows: list[dict[str, Any]] = []
        for row in rows[1:]:
            record = {}
            for i, cell in enumerate(row):
                if i < len(headers) and headers[i]:
                    val = cell if cell is not None else ""
                    if isinstance(val, str):
                        val = val.strip()
                    record[headers[i]] = val
            if record:
                data_rows.append(record)
        result[sheet_name] = data_rows
        logger.info("Загружено %d записей из листа %s", len(data_rows), sheet_name)

    wb.close()
    return result


def load_json_dir(input_dir: str) -> dict[str, list[dict[str, Any]]]:
    """Read all JSON files from a directory, return dict of sheet_name → records."""
    result: dict[str, list[dict[str, Any]]] = {}
    input_path = Path(input_dir)

    if not input_path.is_dir():
        raise click.ClickException(f"Папка не найдена: {input_dir}")

    for sheet_name in SHEET_NAMES:
        json_file = input_path / f"{sheet_name}.json"
        if not json_file.exists():
            logger.warning("Файл не найден, пропускаем: %s", json_file)
            continue
        with open(json_file, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                result[sheet_name] = data
                logger.info("Загружено %d записей из %s", len(data), json_file.name)
            else:
                logger.warning(
                    "Ожидался список записей в %s, получен %s",
                    json_file.name,
                    type(data).__name__,
                )

    missing = [n for n in SHEET_NAMES if n not in result]
    if missing:
        logger.warning("Отсутствуют листы: %s", ", ".join(missing))

    return result


def load_local_data(
    sheet_data: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Build the same data dict as load_data() from local files instead of gspread."""
    from models import input as input_models

    general_settings = input_models.GeneralSettings.from_raw(
        sheet_data.get("Базовые настройки", [])
    )
    accepted_states = input_models.AcceptedStates.from_raw(
        sheet_data.get("Настройки состояния", [])
    )

    raw_licenses = sheet_data.get("Лицензии", [])
    licenses = [input_models.License.from_raw(item) for item in raw_licenses]

    raw_traders = sheet_data.get("Торговцы", [])
    traders_raw = [input_models.Trader.from_raw(item) for item in raw_traders]
    trader_names = [t.givenName for t in traders_raw]

    raw_loadouts = sheet_data.get("Одежда торговцев", [])
    traders_loadouts = [input_models.Loadout.from_raw(item) for item in raw_loadouts]

    raw_categories = sheet_data.get("Категории", [])
    categories_template = [input_models.Category.from_raw(item) for item in raw_categories]

    raw_products = sheet_data.get("Товары", [])
    products_all = [input_models.Product.from_raw(item, trader_names) for item in raw_products]

    raw_currency_types = sheet_data.get("Валюта", [])
    currency_types_raw = [
        input_models.CurrencyType.from_raw(item)
        for item in raw_currency_types
    ]

    raw_currencies = sheet_data.get("Наличка", [])
    currencies_raw = [input_models.Currency.from_raw(item) for item in raw_currencies]

    loadouts_by_trader: dict[int, list[input_models.Loadout]] = {}
    for lo in traders_loadouts:
        loadouts_by_trader.setdefault(lo.id, []).append(lo)

    raw_prices = sheet_data.get("Цены", [])
    prices_map: dict[str, input_models.TraderPrices] = {}
    for p in raw_prices:
        price_obj = input_models.TraderPrices.from_raw(p, trader_names)
        prices_map[price_obj.className] = price_obj

    return {
        "general_settings": general_settings,
        "accepted_states": accepted_states,
        "licenses": licenses,
        "traders_raw": traders_raw,
        "traders_loadouts": traders_loadouts,
        "loadouts_by_trader": loadouts_by_trader,
        "categories_template": categories_template,
        "products_all": products_all,
        "currency_types_raw": currency_types_raw,
        "currencies_raw": currencies_raw,
        "prices_map": prices_map,
    }


# ── ZIP ────────────────────────────────────────────────────────────────────────


def pack_output(output_dir: str, output_zip: str) -> str:
    """Pack the generated files into a ZIP archive."""
    output_path = Path(output_dir)
    if not output_path.is_dir():
        raise click.ClickException(f"Папка не найдена: {output_dir}")

    zip_path = Path(output_zip)
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in output_path.rglob("*"):
            if file_path.is_file():
                arcname = str(file_path.relative_to(output_path.parent))
                zf.write(file_path, arcname)

    logger.info("Архив создан: %s", zip_path)
    return str(zip_path)


# ── CLI ────────────────────────────────────────────────────────────────────────


@click.group()
def cli() -> None:
    """Генератор конфигов TraderX для DayZ."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


@cli.command()
@click.option("--sheet-id", "-s", help="ID Google Sheets таблицы")
@click.option("--credentials", "-c", default="credentials.json", help="Путь к credentials.json")
@click.option("--output", "-o", default="output/profiles/TraderX", help="Папка для результатов")
@click.option("--zip", "output_zip", help="Упаковать результат в ZIP (путь к файлу)")
def google(sheet_id: str | None, credentials: str, output: str, output_zip: str | None) -> None:
    """Сгенерировать конфиги из Google Sheets."""
    if not sheet_id:
        import tomllib
        try:
            with open("config.toml", "rb") as f:
                cfg = tomllib.load(f)
            sheet_id = cfg.get("google", {}).get("spreadsheet_id")
            credentials = cfg.get("google", {}).get("credentials_file", credentials)
            output = cfg.get("output_dir", output)
        except (FileNotFoundError, tomllib.TOMLDecodeError):
            pass

    if not sheet_id:
        raise click.ClickException(
            "Укажите ID таблицы через --sheet-id или в config.toml"
        )

    main_gsheets(
        credentials_file=credentials,
        spreadsheet_id=sheet_id,
        output_dir=output,
    )

    if output_zip:
        pack_output(output, output_zip)


@cli.command()
@click.argument("input", type=click.Path(exists=True))
@click.option("--format", "-f", "input_format",
              type=click.Choice(["auto", "csv", "json", "xlsx"]), default="auto")
@click.option("--output", "-o", default="output/profiles/TraderX", help="Папка для результатов")
@click.option("--zip", "output_zip", help="Упаковать результат в ZIP (путь к файлу)")
def local(input: str, input_format: str, output: str, output_zip: str | None) -> None:
    """Сгенерировать конфиги из локальных файлов (CSV/JSON/Excel)."""
    input_path = Path(input)

    if input_format == "auto":
        if input_path.is_dir():
            if list(input_path.glob("*.csv")):
                input_format = "csv"
            elif list(input_path.glob("*.json")):
                input_format = "json"
            else:
                raise click.ClickException(
                    "В папке не найдены CSV или JSON файлы. "
                    "Имена файлов должны соответствовать названиям листов."
                )
        elif input_path.suffix.lower() == ".xlsx":
            input_format = "xlsx"
        else:
            raise click.ClickException(
                "Формат не определён. Используйте --format csv/json/xlsx"
            )

    logger.info("Загрузка данных из %s (формат: %s)", input, input_format)

    if input_format == "csv":
        sheet_data = load_csv_dir(input)
    elif input_format == "json":
        sheet_data = load_json_dir(input)
    elif input_format == "xlsx":
        sheet_data = load_excel(input)
    else:
        raise click.ClickException(f"Неподдерживаемый формат: {input_format}")

    if not sheet_data:
        raise click.ClickException("Не удалось загрузить ни одного листа")

    data = load_local_data(sheet_data)
    ensure_output_dirs(output)

    output_traders = process_traders(
        traders_raw=data["traders_raw"],
        products_all=data["products_all"],
        prices_map=data["prices_map"],
        categories_template=data["categories_template"],
        loadouts_by_trader=data["loadouts_by_trader"],
        output_dir=output,
    )

    save_general_settings(
        general_settings=data["general_settings"],
        accepted_states=data["accepted_states"],
        licenses=data["licenses"],
        output_traders=output_traders,
        output_dir=output,
    )

    save_currency_settings(
        currency_types_raw=data["currency_types_raw"],
        currencies_raw=data["currencies_raw"],
        output_dir=output,
    )

    logger.info("Готово! Все файлы созданы в папке %s", output)

    if output_zip:
        pack_output(output, output_zip)


@cli.command()
@click.argument("source_dir", type=click.Path(exists=True, file_okay=False))
@click.argument("output_zip", type=click.Path())
def pack(source_dir: str, output_zip: str) -> None:
    """Упаковать готовые файлы в ZIP архив."""
    pack_output(source_dir, output_zip)


@cli.command()
def init_config() -> None:
    """Создать config.toml с настройками по умолчанию."""
    src = Path(__file__).parent / "config.toml"
    dst = Path("config.toml")
    if dst.exists():
        click.echo("config.toml уже существует")
        return
    if src.exists():
        shutil.copy2(src, dst)
        click.echo("Создан config.toml")
    else:
        click.echo("Не найден шаблон config.toml", err=True)


if __name__ == "__main__":
    cli()
