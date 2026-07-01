from models.output import Category, Currency, CurrencyType, Product, Stock


class TestProduct:
    def test_minimal(self) -> None:
        p = Product(className="AK47", buyPrice=100, sellPrice=50)
        assert p.className == "AK47"
        assert p.buyPrice == 100
        assert p.sellPrice == 50
        assert p.stockSettings == 306
        assert p.variants == []
        assert p.attachments == []


class TestStock:
    def test_basic(self) -> None:
        s = Stock(productId="p1", stock=50)
        assert s.productId == "p1"
        assert s.stock == 50


class TestCategory:
    def test_minimal(self) -> None:
        c = Category(isVisible=1, categoryName="[Weapons]", productIds=["p1"])
        assert c.categoryName == "[Weapons]"
        assert c.licensesRequired == []


class TestCurrency:
    def test_value_strict_int(self) -> None:
        Currency(className="Gold", value=5)


class TestCurrencyType:
    def test_basic(self) -> None:
        c = Currency(
            className="Gold", value=5
        )
        ct = CurrencyType(
            currencyName="Gold",
            currencies=[c],
        )
        assert ct.currencyName == "Gold"
        assert len(ct.currencies) == 1
