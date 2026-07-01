from __future__ import annotations

import json
import logging
import os
from typing import Any

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from models import input, output
from models._utils import translit_key

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _load_config_from_toml() -> dict[str, str]:
    """Load config from config.toml if it exists."""
    try:
        import tomllib
    except ImportError:
        return {}
    try:
        with open("config.toml", "rb") as f:
            cfg = tomllib.load(f)
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return {}

    result: dict[str, str] = {}

    google = cfg.get("google", {})
    if isinstance(google, dict):
        if "spreadsheet_id" in google:
            result["SPREADSHEET_ID"] = str(google["spreadsheet_id"])
        if "credentials_file" in google:
            result["CREDENTIALS_FILE"] = str(google["credentials_file"])

    output_dir = cfg.get("output_dir")
    if output_dir is not None:
        result["OUTPUT_DIR"] = str(output_dir)

    return result


def _load_config_from_dotenv() -> dict[str, str]:
    """Load config from .env file if python-dotenv is available."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        return {}

    result: dict[str, str] = {}
    for key in ("CREDENTIALS_FILE", "SPREADSHEET_ID", "OUTPUT_DIR"):
        val = os.getenv(key)
        if val:
            result[key] = val
    return result


def _get_config() -> dict[str, str]:
    """Merge config sources: config.toml > .env > defaults."""
    cfg: dict[str, str] = {}
    cfg.update(_load_config_from_dotenv())
    cfg.update(_load_config_from_toml())
    cfg.setdefault("CREDENTIALS_FILE", "credentials.json")
    cfg.setdefault("OUTPUT_DIR", "output/profiles/TraderX")
    return cfg


CONFIG = _get_config()
CREDENTIALS_FILE = CONFIG["CREDENTIALS_FILE"]
OUTPUT_DIR = CONFIG["OUTPUT_DIR"]


def create_gspread_client(credentials_file: str) -> gspread.Client:
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_file, scope)
    return gspread.authorize(creds)


def open_sheet(client: gspread.Client, spreadsheet_id: str) -> gspread.Spreadsheet:
    return client.open_by_key(spreadsheet_id)


def get_prices_for_product(
    trader_key: str,
    product: input.Product | None,
    prices_map: dict[str, input.TraderPrices],
) -> tuple[int, int]:
    if product is None:
        return 0, 0

    price_obj = prices_map.get(product.className)
    if price_obj:
        trader_prices = price_obj.prices.get(trader_key)
        if trader_prices:
            buy_val = trader_prices.get("buy", 0)
            sell_val = trader_prices.get("sell", 0)
            if buy_val != 0 or sell_val != 0:
                return buy_val, sell_val

    base = product.base_price
    trader_ratio = product.trader_ratios.get(trader_key, 1.0)
    buy_price = round(base * trader_ratio)
    sell_price_raw = round(base * trader_ratio * product.buy_ratio)
    sell_price = sell_price_raw if sell_price_raw < 50 else (sell_price_raw // 50) * 50
    return int(buy_price), int(sell_price)


def round_stock_for_vodka(product_proc: input.Product, trader_key: str) -> int:
    stock_val = int(product_proc.maxStock or 0)
    if (
        stock_val
        and "vodka" in product_proc.product_id.lower()
        and "chernyi_rynok" in trader_key.lower()
    ):
        stock_val = 0
    return stock_val


def write_product_and_stock(
    product_out: output.Product,
    trader_name_lat: str,
    stock_value: int,
    output_dir: str,
) -> str:
    pid = f"prod_{product_out.className}_{trader_name_lat}_001".lower()

    prod_path = os.path.join(output_dir, "TraderXConfig/Products", f"{pid}.json")
    with open(prod_path, "w", encoding="utf-8") as f:
        json.dump(product_out.model_dump(), f, ensure_ascii=False, indent=4)

    stock_out = output.Stock(productId=pid, stock=int(stock_value))
    stock_path = os.path.join(output_dir, "TraderXDatabase/Stock", f"{pid}.json")
    with open(stock_path, "w", encoding="utf-8") as f:
        json.dump(stock_out.model_dump(), f, ensure_ascii=False, indent=4)

    return pid


def load_data(
    sheet: gspread.Spreadsheet, trader_names: list[str]
) -> dict[str, Any]:
    general_settings = input.GeneralSettings.from_raw(
        sheet.worksheet("Базовые настройки").get_all_records()
    )
    accepted_states = input.AcceptedStates.from_raw(
        sheet.worksheet("Настройки состояния").get_all_records()
    )
    licenses = [
        input.License.from_raw(item)
        for item in sheet.worksheet("Лицензии").get_all_records()
    ]
    traders_raw = [
        input.Trader.from_raw(item)
        for item in sheet.worksheet("Торговцы").get_all_records()
    ]
    trader_names[:] = [t.givenName for t in traders_raw]

    traders_loadouts = [
        input.Loadout.from_raw(item)
        for item in sheet.worksheet("Одежда торговцев").get_all_records()
    ]
    categories_template = [
        input.Category.from_raw(item)
        for item in sheet.worksheet("Категории").get_all_records()
    ]
    products_all = [
        input.Product.from_raw(item, trader_names)
        for item in sheet.worksheet("Товары").get_all_records()
    ]
    currency_types_raw = [
        input.CurrencyType.from_raw(item)
        for item in sheet.worksheet("Валюта").get_all_records()
    ]
    currencies_raw = [
        input.Currency.from_raw(item)
        for item in sheet.worksheet("Наличка").get_all_records()
    ]

    loadouts_by_trader: dict[int, list[input.Loadout]] = {}
    for lo in traders_loadouts:
        loadouts_by_trader.setdefault(lo.id, []).append(lo)

    try:
        prices_worksheet = sheet.worksheet("Цены")
        prices_raw = prices_worksheet.get_all_records()
    except gspread.exceptions.WorksheetNotFound:
        logger.error("Лист 'Цены' не найден! Убедитесь, что он существует и называется правильно.")
        raise

    prices_map: dict[str, input.TraderPrices] = {}
    for p in prices_raw:
        price_obj = input.TraderPrices.from_raw(p, trader_names)
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


def process_traders(
    traders_raw: list[input.Trader],
    products_all: list[input.Product],
    prices_map: dict[str, input.TraderPrices],
    categories_template: list[input.Category],
    loadouts_by_trader: dict[int, list[input.Loadout]],
    output_dir: str,
) -> list[dict[str, Any]]:
    output_traders: list[dict[str, Any]] = []

    for trader in traders_raw:
        trader_given = trader.givenName
        trader_key = translit_key(trader_given)
        trader_name_lat = trader_key

        available = [p for p in products_all if p.trader_access.get(trader_key, False)]
        if not available:
            logger.info("У %s нет товаров, пропускаем", trader_given)
            continue

        available_by_class = {p.className: p for p in available}

        explicit_parents = [p for p in available if not p.parent_class]
        potential_variants = [p for p in available if p.parent_class]

        final_parents = {p.className: p for p in explicit_parents}
        for var in potential_variants:
            if var.parent_class not in final_parents:
                final_parents[var.className] = var
                var.parent_class = None

        grouped: dict[str, list[input.Product]] = {pc: [] for pc in final_parents}
        for var in potential_variants:
            if var.parent_class and var.parent_class in final_parents:
                grouped[var.parent_class].append(var)

        needed_attachments: set[str] = set()
        for p in available:
            for att in p.attachments_list:
                att_product = available_by_class.get(att)
                if att_product and att_product.trader_access.get(trader_key, False):
                    needed_attachments.add(att)

        def build_product(
            inp: input.Product,
            variants: list[str] | None = None,
        ) -> output.Product:
            buy_price, sell_price = get_prices_for_product(trader_key, inp, prices_map)
            return output.Product(
                className=inp.className,
                buyPrice=buy_price,
                sellPrice=sell_price,
                stockSettings=int(inp.stockSettings),
                maxStock=int(inp.maxStock or 0),
                tradeQuantity=int(inp.tradeQuantity),
                coefficient=inp.coefficient,
                variants=variants or [],
                attachments=[
                    attachment_map[a] for a in inp.attachments_list if a in attachment_map
                ],
            )

        attachment_map: dict[str, str] = {}
        for att_class in needed_attachments:
            att_pid = f"prod_{att_class}_{trader_name_lat}_001".lower()
            attachment_map[att_class] = att_pid

            if att_class in final_parents:
                continue
            att_prod = available_by_class.get(att_class)
            if att_prod and att_prod.parent_class:
                continue
            if att_prod is None:
                continue

            att_out = build_product(att_prod)
            att_sv = round_stock_for_vodka(att_prod, trader_key)
            write_product_and_stock(att_out, trader_name_lat, att_sv, output_dir)

        trader_products: list[tuple[str, str, output.Product]] = []
        for parent_class_name, parent_prod in final_parents.items():
            variant_list = grouped[parent_class_name]

            variant_product_ids: list[str] = []
            for var in variant_list:
                var_out = build_product(var)
                var_sv = round_stock_for_vodka(var, trader_key)
                vid = write_product_and_stock(var_out, trader_name_lat, var_sv, output_dir)
                variant_product_ids.append(vid)

            parent_out = build_product(parent_prod, variants=variant_product_ids)
            parent_sv = round_stock_for_vodka(parent_prod, trader_key)
            parent_id = write_product_and_stock(
                parent_out, trader_name_lat, parent_sv, output_dir
            )
            trader_products.append((parent_prod.category, parent_id, parent_out))

        active_categories: list[str] = []
        for cat_tmpl in categories_template:
            cat_id = (
                cat_tmpl.category_id.replace("<placeholder>", trader_name_lat).lower()
                + "_001"
            )
            cat_filename = os.path.join(
                output_dir, "TraderXConfig/Categories", f"{cat_id}.json"
            )
            cat_product_ids = [
                pid for (cat_name, pid, _) in trader_products if cat_name == cat_tmpl.name
            ]
            if cat_product_ids:
                active_categories.append(cat_id)
                out_cat = output.Category(
                    isVisible=1 if cat_tmpl.is_visible else 0,
                    icon="",
                    categoryName=f"[{cat_tmpl.name}]",
                    licensesRequired=cat_tmpl.licenses,
                    productIds=cat_product_ids,
                )
                with open(cat_filename, "w", encoding="utf-8") as f:
                    json.dump(out_cat.model_dump(), f, ensure_ascii=False, indent=4)

        trader_loadouts = loadouts_by_trader.get(trader.trader_id, [])
        out_loadouts = [
            output.Loadout(
                className=lo.className,
                slotName=lo.slotName,
                quantity=-1,
                attachments=[{"className": att, "quantity": 1} for att in lo.attachments],
            )
            for lo in trader_loadouts
        ]

        out_trader = output.Trader.from_raw(
            trader.model_dump(),
            categories=active_categories,
            loadouts=out_loadouts,
        )
        output_traders.append(out_trader.model_dump())

    return output_traders


def save_general_settings(
    general_settings: input.GeneralSettings,
    accepted_states: input.AcceptedStates,
    licenses: list[input.License],
    output_traders: list[dict[str, Any]],
    output_dir: str,
) -> None:
    accepted_states_out = {
        "acceptWorn": 1 if accepted_states.acceptWorn else 0,
        "acceptDamaged": 1 if accepted_states.acceptDamaged else 0,
        "acceptBadlyDamaged": 1 if accepted_states.acceptBadlyDamaged else 0,
        "coefficientWorn": accepted_states.coefficientWorn,
        "coefficientDamaged": accepted_states.coefficientDamaged,
        "coefficientBadlyDamaged": accepted_states.coefficientBadlyDamaged,
    }

    general_out = {
        "version": general_settings.version,
        "serverID": general_settings.serverID,
        "licenses": [lic.model_dump() for lic in licenses],
        "acceptedStates": accepted_states_out,
        "traders": output_traders,
        "traderObjects": general_settings.traderObjects,
    }

    path = os.path.join(output_dir, "TraderXConfig/TraderXGeneralSettings.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(general_out, f, ensure_ascii=False, indent=4)


def save_currency_settings(
    currency_types_raw: list[input.CurrencyType],
    currencies_raw: list[input.Currency],
    output_dir: str,
) -> None:
    currency_types_out: list[output.CurrencyType] = []
    for ctype in currency_types_raw:
        currencies_list = [
            output.Currency(className=curr.className, value=curr.value)
            for curr in currencies_raw
            if curr.className in ctype.currencies
        ]
        currency_types_out.append(
            output.CurrencyType(
                currencyName=ctype.currencyName,
                currencies=currencies_list,
            )
        )

    currency_settings = output.CurrencySettings(currencyTypes=currency_types_out)
    path = os.path.join(output_dir, "TraderXConfig/TraderXCurrencySettings.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(currency_settings.model_dump(), f, ensure_ascii=False, indent=4)


def ensure_output_dirs(output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(f"{output_dir}/TraderXConfig/Categories", exist_ok=True)
    os.makedirs(f"{output_dir}/TraderXConfig/Products", exist_ok=True)
    os.makedirs(f"{output_dir}/TraderXDatabase/Stock", exist_ok=True)


def main(
    credentials_file: str = "",
    spreadsheet_id: str = "",
    output_dir: str = "",
) -> None:
    cfg = _get_config()
    credentials_file = credentials_file or cfg["CREDENTIALS_FILE"]
    spreadsheet_id = spreadsheet_id or os.getenv("SPREADSHEET_ID", "")
    output_dir = output_dir or cfg["OUTPUT_DIR"]
    if not spreadsheet_id:
        logger.error("SPREADSHEET_ID не задан. Укажите в config.toml, .env или аргументом.")
        return
    client = create_gspread_client(credentials_file)
    sheet = open_sheet(client, spreadsheet_id)

    ensure_output_dirs(output_dir)

    trader_names: list[str] = []
    data = load_data(sheet, trader_names)

    output_traders = process_traders(
        traders_raw=data["traders_raw"],
        products_all=data["products_all"],
        prices_map=data["prices_map"],
        categories_template=data["categories_template"],
        loadouts_by_trader=data["loadouts_by_trader"],
        output_dir=output_dir,
    )

    save_general_settings(
        general_settings=data["general_settings"],
        accepted_states=data["accepted_states"],
        licenses=data["licenses"],
        output_traders=output_traders,
        output_dir=output_dir,
    )

    save_currency_settings(
        currency_types_raw=data["currency_types_raw"],
        currencies_raw=data["currencies_raw"],
        output_dir=output_dir,
    )

    logger.info("Готово! Все файлы созданы в папке %s", output_dir)


if __name__ == "__main__":
    try:
        import cli as _cli_mod  # type: ignore[has-type]
        _cli_mod.cli()  # type: ignore[has-type]
    except ImportError:
        main()
