from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from trader_concept import (
    ensure_output_dirs,
    load_data,
    main,
    process_traders,
    save_currency_settings,
    save_general_settings,
)
from models.input import (
    AcceptedStates,
    Category,
    GeneralSettings,
    License,
    Product,
    Trader,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def mock_sheet(data: dict[str, list[dict[str, Any]]]) -> MagicMock:
    """Build a gspread.Spreadsheet mock that returns test data per worksheet."""

    def worksheet(name: str) -> MagicMock:
        ws = MagicMock()
        ws.get_all_records.return_value = data.get(name, [])
        return ws

    sheet = MagicMock()
    sheet.worksheet = MagicMock(side_effect=worksheet)
    return sheet


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def sheet_data() -> dict[str, list[dict[str, Any]]]:
    return {
        "Базовые настройки": [
            {"версия": "1.0.1", "сервер": "test_server", "лицензии": "", "торговцы": "", "объекты торговцев": ""},
        ],
        "Настройки состояния": [
            {
                "принимать поношенное": True,
                "коеффициент поношенного": 0.5,
                "принимать поврежденное": True,
                "коеффициент поврежденного": 0.3,
                "принимать сильно поврежденное": False,
                "коеффициент сильно поврежденного": 0.1,
            },
        ],
        "Лицензии": [
            {"licenseId": "lic_trader", "licenseName": "Торговец", "description": "Базовая лицензия"},
            {"licenseId": "lic_weapons", "licenseName": "Оружие", "description": "Оружейная лицензия"},
        ],
        "Торговцы": [
            {"Имя": "Рыбак", "Описание": "Продает рыбу", "className": "TraderFisher", "Наценка": 1.0, "Валюта": "Rub", "Позиция": "<100, 200, 300>", "Ориентация": "<0, 90, 0>"},
            {"Имя": "Сидор", "Описание": "Барыга", "className": "TraderSidor", "Наценка": 1.5, "Валюта": "Rub, Euro", "Позиция": "", "Ориентация": ""},
        ],
        "Одежда торговцев": [
            {"id": 0, "className": "FisherVest", "slotName": "Body", "attachments": ""},
            {"id": 0, "className": "FisherHat", "slotName": "Head", "attachments": ""},
            {"id": 1, "className": "SidorJacket", "slotName": "Body", "attachments": '["bag"]'},
        ],
        "Категории": [
            {"Name": "Снаряжение", "Наценка": 0.5, "Видимость": True, "Лицензии": "lic_trader"},
            {"Name": "Оружие", "Наценка": 0.8, "Видимость": True, "Лицензии": "lic_weapons"},
        ],
        "Товары": [
            {"product_id": "", "className": "FishingRod", "Категория": "Снаряжение", "Себестоимость": 100, "Наценка продажи игроком": 0.5, "Сток": 200, "Запас": 50, "Режим": 16, "Коефициент": 1.0, "Обвес": "", "Вариант для": "", "Рыбак": True, "Сидор": False, "Рыбак наценка": 1.0, "Сидор наценка": 1.0},
            {"product_id": "", "className": "FishingNet", "Категория": "Снаряжение", "Себестоимость": 200, "Наценка продажи игроком": 0.5, "Сток": 100, "Запас": 30, "Режим": 10, "Коефициент": 1.0, "Обвес": "", "Вариант для": "FishingRod", "Рыбак": True, "Сидор": False, "Рыбак наценка": 1.0, "Сидор наценка": 1.0},
            {"product_id": "", "className": "AK47", "Категория": "Оружие", "Себестоимость": 500, "Наценка продажи игроком": 0.3, "Сток": 300, "Запас": 20, "Режим": 1, "Коефициент": 1.0, "Обвес": "silencer, scope", "Вариант для": "", "Рыбак": False, "Сидор": True, "Рыбак наценка": 1.0, "Сидор наценка": 1.2},
            {"product_id": "", "className": "AK47_Wood", "Категория": "Оружие", "Себестоимость": 600, "Наценка продажи игроком": 0.3, "Сток": 300, "Запас": 15, "Режим": 1, "Коефициент": 1.0, "Обвес": "", "Вариант для": "AK47", "Рыбак": False, "Сидор": True, "Рыбак наценка": 1.0, "Сидор наценка": 1.0},
            {"product_id": "", "className": "silencer", "Категория": "Оружие", "Себестоимость": 50, "Наценка продажи игроком": 0.5, "Сток": 500, "Запас": 100, "Режим": 10, "Коефициент": 1.0, "Обвес": "", "Вариант для": "", "Рыбак": False, "Сидор": True, "Рыбак наценка": 1.0, "Сидор наценка": 1.0},
            {"product_id": "", "className": "scope", "Категория": "Оружие", "Себестоимость": 80, "Наценка продажи игроком": 0.5, "Сток": 500, "Запас": 100, "Режим": 10, "Коефициент": 1.0, "Обвес": "", "Вариант для": "", "Рыбак": False, "Сидор": True, "Рыбак наценка": 1.0, "Сидор наценка": 1.0},
        ],
        "Цены": [
            {"className": "FishingRod", "Рыбак продажа": 80, "Рыбак покупка": 40},
            {"className": "AK47", "Сидор продажа": 1200, "Сидор покупка": 600},
        ],
        "Валюта": [
            {"Валюта": "Rub", "currencies": "Rub"},
            {"Валюта": "Euro", "currencies": "Euro"},
        ],
        "Наличка": [
            {"className": "Rub", "value": 1},
            {"className": "Euro", "value": 5},
        ],
    }


# ── Integration: load_data → process_traders → save_* ─────────────────────────


class TestFullPipeline:
    def test_load_data_returns_structured_data(self, sheet_data: dict) -> None:
        sheet = mock_sheet(sheet_data)
        trader_names: list[str] = []
        data = load_data(sheet, trader_names)

        assert isinstance(data["general_settings"], GeneralSettings)
        assert isinstance(data["accepted_states"], AcceptedStates)
        assert len(data["licenses"]) == 2
        assert all(isinstance(lic, License) for lic in data["licenses"])
        assert len(data["traders_raw"]) == 2
        assert all(isinstance(t, Trader) for t in data["traders_raw"])
        assert len(data["traders_loadouts"]) == 3
        assert len(data["categories_template"]) == 2
        assert all(isinstance(c, Category) for c in data["categories_template"])
        assert len(data["products_all"]) == 6
        assert all(isinstance(p, Product) for p in data["products_all"])
        assert len(data["currency_types_raw"]) == 2
        assert len(data["currencies_raw"]) == 2
        assert len(data["prices_map"]) == 2
        assert trader_names == ["Рыбак", "Сидор"]

    def test_process_traders_creates_files(self, sheet_data: dict) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ensure_output_dirs(tmpdir)
            sheet = mock_sheet(sheet_data)
            trader_names: list[str] = []
            data = load_data(sheet, trader_names)

            output_traders = process_traders(
                traders_raw=data["traders_raw"],
                products_all=data["products_all"],
                prices_map=data["prices_map"],
                categories_template=data["categories_template"],
                loadouts_by_trader=data["loadouts_by_trader"],
                output_dir=tmpdir,
            )

            # Both traders have products
            assert len(output_traders) == 2

            product_dir = Path(tmpdir) / "TraderXConfig/Products"
            stock_dir = Path(tmpdir) / "TraderXDatabase/Stock"
            cat_dir = Path(tmpdir) / "TraderXConfig/Categories"

            # Files are created
            assert len(list(product_dir.iterdir())) > 0
            assert len(list(stock_dir.iterdir())) > 0
            assert len(list(cat_dir.iterdir())) > 0

            # Verify all generated JSONs are valid
            for f in product_dir.iterdir():
                data = json.loads(f.read_text(encoding="utf-8"))
                assert "className" in data
                assert "buyPrice" in data
                assert "sellPrice" in data
            for f in stock_dir.iterdir():
                data = json.loads(f.read_text(encoding="utf-8"))
                assert "productId" in data
                assert "stock" in data
            for f in cat_dir.iterdir():
                data = json.loads(f.read_text(encoding="utf-8"))
                assert "isVisible" in data
                assert "productIds" in data

    def test_save_general_settings(self, sheet_data: dict) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ensure_output_dirs(tmpdir)
            sheet = mock_sheet(sheet_data)
            trader_names: list[str] = []
            data = load_data(sheet, trader_names)
            output_traders = process_traders(
                traders_raw=data["traders_raw"],
                products_all=data["products_all"],
                prices_map=data["prices_map"],
                categories_template=data["categories_template"],
                loadouts_by_trader=data["loadouts_by_trader"],
                output_dir=tmpdir,
            )

            save_general_settings(
                data["general_settings"],
                data["accepted_states"],
                data["licenses"],
                output_traders,
                tmpdir,
            )

            path = Path(tmpdir) / "TraderXConfig/TraderXGeneralSettings.json"
            assert path.exists()
            content = json.loads(path.read_text(encoding="utf-8"))
            assert content["version"] == "1.0.1"
            assert content["serverID"] == "test_server"
            assert len(content["licenses"]) == 2
            assert len(content["traders"]) == 2
            assert "acceptWorn" in content["acceptedStates"]
            assert "acceptDamaged" in content["acceptedStates"]

    def test_save_currency_settings(self, sheet_data: dict) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ensure_output_dirs(tmpdir)
            sheet = mock_sheet(sheet_data)
            trader_names: list[str] = []
            data = load_data(sheet, trader_names)

            save_currency_settings(
                data["currency_types_raw"],
                data["currencies_raw"],
                tmpdir,
            )

            path = Path(tmpdir) / "TraderXConfig/TraderXCurrencySettings.json"
            assert path.exists()
            content = json.loads(path.read_text(encoding="utf-8"))
            assert "currencyTypes" in content
            assert len(content["currencyTypes"]) == 2

    def test_full_main_with_mock(self, sheet_data: dict) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sheet = mock_sheet(sheet_data)

            with patch("trader_concept.create_gspread_client") as mock_create:
                with patch("trader_concept.open_sheet", return_value=sheet):
                    mock_create.return_value = MagicMock()

                    main(
                        credentials_file="fake.json",
                        spreadsheet_id="fake_id",
                        output_dir=tmpdir,
                    )

            # Verify all expected directories and files exist
            assert (Path(tmpdir) / "TraderXConfig/Categories").is_dir()
            assert (Path(tmpdir) / "TraderXConfig/Products").is_dir()
            assert (Path(tmpdir) / "TraderXDatabase/Stock").is_dir()
            assert (Path(tmpdir) / "TraderXConfig/TraderXGeneralSettings.json").exists()
            assert (Path(tmpdir) / "TraderXConfig/TraderXCurrencySettings.json").exists()


# ── Integration: product variant & attachment logic ───────────────────────────


class TestProductRelationships:
    def test_parent_with_variants(self, sheet_data: dict) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ensure_output_dirs(tmpdir)
            sheet = mock_sheet(sheet_data)
            trader_names: list[str] = []
            data = load_data(sheet, trader_names)
            output_traders = process_traders(
                traders_raw=data["traders_raw"],
                products_all=data["products_all"],
                prices_map=data["prices_map"],
                categories_template=data["categories_template"],
                loadouts_by_trader=data["loadouts_by_trader"],
                output_dir=tmpdir,
            )

            # Sidor has AK47 (parent) + AK47_Wood (variant) + silencer + scope
            next(t for t in output_traders if t["givenName"] == "Сидор")

            # Find product files for Sidor
            prod_dir = Path(tmpdir) / "TraderXConfig/Products"
            sidor_products = list(prod_dir.glob("*_sidor_001.json"))

            # Should have: AK47(parent), AK47_Wood(variant), silencer, scope
            assert len(sidor_products) >= 4

            # Parent product should list variants
            ak47_file = prod_dir / "prod_ak47_sidor_001.json"
            assert ak47_file.exists()
            ak47_data = json.loads(ak47_file.read_text(encoding="utf-8"))
            assert ak47_data["variants"] == ["prod_ak47_wood_sidor_001"]
            assert "prod_silencer_sidor_001" in ak47_data["attachments"]
            assert "prod_scope_sidor_001" in ak47_data["attachments"]

            # Variant product should not have variants
            ak47w_file = prod_dir / "prod_ak47_wood_sidor_001.json"
            assert ak47w_file.exists()
            ak47w_data = json.loads(ak47w_file.read_text(encoding="utf-8"))
            assert ak47w_data["variants"] == []
            assert ak47w_data["attachments"] == []

    def test_attachments_written_as_separate_products(self, sheet_data: dict) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ensure_output_dirs(tmpdir)
            sheet = mock_sheet(sheet_data)
            trader_names: list[str] = []
            data = load_data(sheet, trader_names)
            process_traders(
                traders_raw=data["traders_raw"],
                products_all=data["products_all"],
                prices_map=data["prices_map"],
                categories_template=data["categories_template"],
                loadouts_by_trader=data["loadouts_by_trader"],
                output_dir=tmpdir,
            )

            prod_dir = Path(tmpdir) / "TraderXConfig/Products"
            stock_dir = Path(tmpdir) / "TraderXDatabase/Stock"

            # silencer and scope should exist as standalone products for Sidor
            silencer = prod_dir / "prod_silencer_sidor_001.json"
            scope = prod_dir / "prod_scope_sidor_001.json"
            assert silencer.exists(), "silencer attachment product not created"
            assert scope.exists(), "scope attachment product not created"

            # They should also have stock entries
            assert (stock_dir / "prod_silencer_sidor_001.json").exists()
            assert (stock_dir / "prod_scope_sidor_001.json").exists()

    def test_prices_from_map_vs_calculated(self, sheet_data: dict) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ensure_output_dirs(tmpdir)
            sheet = mock_sheet(sheet_data)
            trader_names: list[str] = []
            data = load_data(sheet, trader_names)
            process_traders(
                traders_raw=data["traders_raw"],
                products_all=data["products_all"],
                prices_map=data["prices_map"],
                categories_template=data["categories_template"],
                loadouts_by_trader=data["loadouts_by_trader"],
                output_dir=tmpdir,
            )

            prod_dir = Path(tmpdir) / "TraderXConfig/Products"

            # FishingRod for Рыбак — price from map (80 sell, 40 buy)
            rod = json.loads(
                (prod_dir / "prod_fishingrod_rybak_001.json").read_text(encoding="utf-8")
            )
            assert rod["buyPrice"] == 40
            assert rod["sellPrice"] == 80

            # AK47 for Сидор — price from map (1200 sell, 600 buy)
            ak47 = json.loads(
                (prod_dir / "prod_ak47_sidor_001.json").read_text(encoding="utf-8")
            )
            assert ak47["buyPrice"] == 600
            assert ak47["sellPrice"] == 1200

            # FishingNet (variant) for Рыбак — no price in map, calculated
            net = json.loads(
                (prod_dir / "prod_fishingnet_rybak_001.json").read_text(encoding="utf-8")
            )
            # base=200, ratio=1.0 → buy=200, sell=200 * 0.5 = 100
            assert net["buyPrice"] == 200
            assert net["sellPrice"] == 100

    def test_trader_without_products_skipped(self, sheet_data: dict) -> None:
        # Add a third trader with no product access
        sheet_data["Торговцы"].append(
            {"Имя": "БезТоваров", "Описание": "Empty", "className": "TraderEmpty", "Наценка": 1.0, "Валюта": "", "Позиция": "", "Ориентация": ""},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            ensure_output_dirs(tmpdir)
            sheet = mock_sheet(sheet_data)
            trader_names: list[str] = []
            data = load_data(sheet, trader_names)
            output_traders = process_traders(
                traders_raw=data["traders_raw"],
                products_all=data["products_all"],
                prices_map=data["prices_map"],
                categories_template=data["categories_template"],
                loadouts_by_trader=data["loadouts_by_trader"],
                output_dir=tmpdir,
            )

            names = [t["givenName"] for t in output_traders]
            assert "БезТоваров" not in names
            assert "Рыбак" in names
            assert "Сидор" in names

    def test_loadout_generation(self, sheet_data: dict) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ensure_output_dirs(tmpdir)
            sheet = mock_sheet(sheet_data)
            trader_names: list[str] = []
            data = load_data(sheet, trader_names)
            output_traders = process_traders(
                traders_raw=data["traders_raw"],
                products_all=data["products_all"],
                prices_map=data["prices_map"],
                categories_template=data["categories_template"],
                loadouts_by_trader=data["loadouts_by_trader"],
                output_dir=tmpdir,
            )

            sidor = next(t for t in output_traders if t["givenName"] == "Сидор")
            assert len(sidor["loadouts"]) == 1
            assert sidor["loadouts"][0]["className"] == "SidorJacket"
            assert sidor["loadouts"][0]["attachments"] == [{"className": "bag", "quantity": 1}]

            rybak = next(t for t in output_traders if t["givenName"] == "Рыбак")
            assert len(rybak["loadouts"]) == 2
