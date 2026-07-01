import json
import tempfile
from pathlib import Path
from typing import Any

from models.input import Product as InputProduct
from models.output import Product as OutputProduct
from trader_concept import (
    ensure_output_dirs,
    get_prices_for_product,
    round_stock_for_vodka,
    write_product_and_stock,
)


def _make_product(**aliased_overrides: Any) -> InputProduct:
    data: dict[str, Any] = {
        "Категория": "W",
        "Себестоимость": 100,
        "Наценка продажи игроком": 0.5,
        "Сток": 200,
        "product_id": "p1",
        "className": "AK47",
        "trader_ratios": {"trader": 1.0},
    }
    data.update(aliased_overrides)
    return InputProduct.model_validate(data)


class TestGetPricesForProduct:
    def test_none_product(self) -> None:
        assert get_prices_for_product("trader", None, {}) == (0, 0)

    def test_exact_price_in_map(self) -> None:
        prod = _make_product()
        price_obj = type("TP", (), {"prices": {"trader": {"buy": 200, "sell": 100}}})()
        prices_map = {"AK47": price_obj}
        assert get_prices_for_product("trader", prod, prices_map) == (200, 100)

    def test_zero_price_falls_back(self) -> None:
        prod = _make_product()
        price_obj = type("TP", (), {"prices": {"trader": {"buy": 0, "sell": 0}}})()
        prices_map = {"AK47": price_obj}
        buy, sell = get_prices_for_product("trader", prod, prices_map)
        assert buy > 0
        assert sell > 0

    def test_calculated_price(self) -> None:
        prod = _make_product(**{"trader_ratios": {"trader": 2.0}})
        buy, sell = get_prices_for_product("trader", prod, {})
        assert buy == 200
        assert sell == 100


class TestRoundStockForVodka:
    def test_vodka_on_black_market_zero(self) -> None:
        prod = _make_product(
            className="Vodka",
            product_id="prod_vodka_001",
            **{"Запас": 50},
            Категория="Drinks",
            Себестоимость=50,
        )
        assert round_stock_for_vodka(prod, "chernyi_rynok") == 0

    def test_vodka_on_other_trader(self) -> None:
        prod = _make_product(
            className="Vodka",
            product_id="prod_vodka_001",
            **{"Запас": 50},
            Категория="Drinks",
            Себестоимость=50,
        )
        assert round_stock_for_vodka(prod, "rybak") == 50

    def test_non_vodka_product(self) -> None:
        prod = _make_product(
            className="AK47",
            product_id="prod_ak47_001",
            **{"Запас": 30},
        )
        assert round_stock_for_vodka(prod, "chernyi_rynok") == 30


class TestWriteProductAndStock:
    def test_writes_product_and_stock_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ensure_output_dirs(tmpdir)
            prod_out = OutputProduct(
                className="AK47",
                buyPrice=200,
                sellPrice=100,
            )
            pid = write_product_and_stock(prod_out, "rybak", 50, tmpdir)

            assert pid == "prod_ak47_rybak_001"

            prod_path = Path(tmpdir) / "TraderXConfig/Products" / f"{pid}.json"
            assert prod_path.exists()
            prod_data = json.loads(prod_path.read_text(encoding="utf-8"))
            assert prod_data["className"] == "AK47"
            assert prod_data["buyPrice"] == 200

            stock_path = Path(tmpdir) / "TraderXDatabase/Stock" / f"{pid}.json"
            assert stock_path.exists()
            stock_data = json.loads(stock_path.read_text(encoding="utf-8"))
            assert stock_data["productId"] == pid
            assert stock_data["stock"] == 50


class TestEnsureOutputDirs:
    def test_creates_all_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ensure_output_dirs(tmpdir)
            assert (Path(tmpdir) / "TraderXConfig/Categories").is_dir()
            assert (Path(tmpdir) / "TraderXConfig/Products").is_dir()
            assert (Path(tmpdir) / "TraderXDatabase/Stock").is_dir()
