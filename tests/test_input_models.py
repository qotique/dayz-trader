from models.input import Trader, Category, Product, Loadout, TraderPrices


class TestTraderFromRaw:
    def test_minimal(self) -> None:
        data = {"Имя": "Рыбак", "Описание": "Fisher", "className": "TraderFisher"}
        t = Trader.from_raw(data)
        assert t.givenName == "Рыбак"
        assert t.description == "Fisher"
        assert t.className == "TraderFisher"
        assert t.trader_id >= 0

    def test_currencies_string(self) -> None:
        data = {
            "Имя": "Рыбак",
            "Описание": "Fisher",
            "className": "T",
            "Валюта": "Gold, Euro",
        }
        t = Trader.from_raw(data)
        assert t.currencies == ["Gold", "Euro"]

    def test_position_parsing(self) -> None:
        data = {
            "Имя": "Рыбак",
            "Описание": "Fisher",
            "className": "T",
            "Позиция": "<100, 200, 300>",
        }
        t = Trader.from_raw(data)
        assert t.position == [100.0, 200.0, 300.0]


class TestCategoryFromRaw:
    def test_auto_id(self) -> None:
        data = {"Name": "Оружие", "Наценка": 0.5, "Видимость": True}
        c = Category.from_raw(data)
        assert "cat_oruzhie" in c.category_id
        assert c.name == "Оружие"
        assert c.is_visible is True

    def test_explicit_id(self) -> None:
        data = {
            "category_id": "cat_weapons_<placeholder>",
            "Name": "Weapons",
            "Наценка": 0.5,
            "Видимость": True,
        }
        c = Category.from_raw(data)
        assert c.category_id == "cat_weapons_<placeholder>"

    def test_licenses_string(self) -> None:
        data = {
            "Name": "Test",
            "Наценка": 0.5,
            "Видимость": True,
            "Лицензии": "lic_1, lic_2",
        }
        c = Category.from_raw(data)
        assert c.licenses == ["lic_1", "lic_2"]


class TestProductFromRaw:
    trader_names = ["Рыбак", "Сидор"]

    def test_minimal(self) -> None:
        data = {
            "className": "AK47",
            "product_id": "prod_ak47",
            "Категория": "Weapons",
            "Себестоимость": 100,
            "Наценка продажи игроком": 0.5,
            "Сток": 200,
        }
        p = Product.from_raw(data, self.trader_names)
        assert p.className == "AK47"
        assert p.category == "Weapons"
        assert p.base_price == 100

    def test_access_flags(self) -> None:
        data = {
            "className": "AK47",
            "product_id": "p1",
            "Категория": "W",
            "Себестоимость": 100,
            "Наценка продажи игроком": 0.5,
            "Сток": 200,
            "Рыбак": True,
            "Сидор": False,
        }
        p = Product.from_raw(data, self.trader_names)
        assert p.trader_access["rybak"] is True
        assert p.trader_access["sidor"] is False

    def test_attachments_string(self) -> None:
        data = {
            "className": "AK47",
            "product_id": "p1",
            "Категория": "W",
            "Себестоимость": 100,
            "Наценка продажи игроком": 0.5,
            "Сток": 200,
            "Обвес": "silencer, scope",
        }
        p = Product.from_raw(data, self.trader_names)
        assert p.attachments_list == ["silencer", "scope"]

    def test_parent_class(self) -> None:
        data = {
            "className": "AK47_Variant",
            "product_id": "p2",
            "Категория": "W",
            "Себестоимость": 100,
            "Наценка продажи игроком": 0.5,
            "Сток": 200,
            "Вариант для": "AK47",
        }
        p = Product.from_raw(data, self.trader_names)
        assert p.parent_class == "AK47"


class TestTraderPricesFromRaw:
    trader_names = ["Рыбак", "Сидор"]

    def test_basic(self) -> None:
        data = {
            "className": "AK47",
            "Рыбак продажа": 100,
            "Рыбак покупка": 50,
            "Сидор продажа": 120,
            "Сидор покупка": 60,
        }
        tp = TraderPrices.from_raw(data, self.trader_names)
        assert tp.className == "AK47"
        assert tp.prices["rybak"] == {"sell": 100, "buy": 50}
        assert tp.prices["sidor"] == {"sell": 120, "buy": 60}

    def test_missing_trader(self) -> None:
        data = {"className": "AK47", "Рыбак продажа": 100, "Рыбак покупка": 50}
        tp = TraderPrices.from_raw(data, self.trader_names)
        assert "rybak" in tp.prices
        assert "sidor" not in tp.prices


class TestLoadoutFromRaw:
    def test_attachments_json_string(self) -> None:
        data = {
            "id": 1,
            "className": "Vest",
            "slotName": "Body",
            "attachments": '["item1", "item2"]',
        }
        lo = Loadout.from_raw(data)
        assert lo.attachments == ["item1", "item2"]

    def test_attachments_csv_fallback(self) -> None:
        data = {
            "id": 1,
            "className": "Vest",
            "slotName": "Body",
            "attachments": "item1, item2",
        }
        lo = Loadout.from_raw(data)
        assert lo.attachments == ["item1", "item2"]

    def test_no_attachments(self) -> None:
        data = {"id": 1, "className": "Vest", "slotName": "Body"}
        lo = Loadout.from_raw(data)
        assert lo.attachments == []
