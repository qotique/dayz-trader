from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, StrictInt

from models._utils import next_output_trader_id as next_trader_id
from models._utils import translit_key


class Product(BaseModel):
    className: str
    coefficient: float = 1.0
    maxStock: int = 100
    tradeQuantity: int = 16
    buyPrice: int
    sellPrice: int
    stockSettings: int = 306
    attachments: list = []
    variants: list = []


class Stock(BaseModel):
    productId: str
    stock: int


class Category(BaseModel):
    isVisible: int
    icon: str = ""
    categoryName: str
    licensesRequired: list[str] = []
    productIds: list[str] = []


class License(BaseModel):
    licenseId: str
    licenseName: str
    description: str


class Currency(BaseModel):
    className: str
    value: StrictInt


class CurrencyType(BaseModel):
    currencyName: str
    currencies: list[Currency]


class CurrencySettings(BaseModel):
    version: str = "1.0.1"
    currencyTypes: list[CurrencyType]


class Loadout(BaseModel):
    className: str
    quantity: int = -1
    slotName: str
    attachments: list[dict] = []


class Attachment(BaseModel):
    className: str
    quantity: int = -1


class Trader(BaseModel):
    npcId: int = Field(default_factory=next_trader_id)
    className: str
    givenName: str
    role: str = Field(..., alias="description")
    position: list[float]
    orientation: list[float]
    categoriesId: list[str] = Field(..., alias="categories")
    currenciesAccepted: list[str] = Field(..., alias="currencies")
    loadouts: list[Loadout] = Field(default_factory=list)

    @classmethod
    def from_raw(
        cls,
        data: dict[str, Any],
        categories: list[str],
        loadouts: list[Loadout],
    ) -> Trader:
        trader_name = translit_key(data["givenName"])
        data["categories"] = [cat.replace("<placeholder>", trader_name) for cat in categories]
        data["currencies"] = data.get("currencies", [])
        data["description"] = data.get("description", "")
        data["position"] = data.get("position", [])
        data["orientation"] = data.get("orientation", [])
        data["loadouts"] = [lo.model_dump() for lo in loadouts]
        return cls.model_validate(data)
