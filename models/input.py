from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, StrictInt

from models._utils import next_input_trader_id as next_trader_id, translit_key


class Trader(BaseModel):
    trader_id: int = Field(default_factory=next_trader_id)
    className: str = Field(...)
    givenName: str = Field(..., alias="Имя")
    description: str = Field(..., alias="Описание")
    tradeCoeficient: float = Field(1.0, alias="Наценка")
    currencies: list[str] = Field([], alias="Валюта")
    position: list[float] = Field([], alias="Позиция")
    orientation: list[float] = Field([], alias="Ориентация")

    @classmethod
    def from_raw(cls, data: dict[str, Any]) -> Trader:
        currencies = data.get("Валюта")
        if not currencies:
            data["Валюта"] = []
        elif isinstance(currencies, str):
            data["Валюта"] = currencies.split(", ")
        position = data.get("Позиция")
        if not position:
            data["Позиция"] = []
        elif position:
            data["Позиция"] = position.replace("<", "").replace(">", "").split(", ")
        orientation = data.get("Ориентация")
        if not orientation:
            data["Ориентация"] = []
        elif orientation:
            data["Ориентация"] = orientation.replace("<", "").replace(">", "").split(", ")
        return cls.model_validate(data)


class Category(BaseModel):
    category_id: str = Field(...)
    name: str = Field(..., alias="Name")
    sell_ratio: float = Field(..., alias="Наценка")
    is_visible: bool = Field(..., alias="Видимость")
    licenses: list[str] = Field([], alias="Лицензии")

    @classmethod
    def from_raw(cls, data: dict[str, Any]) -> Category:
        if not data.get("category_id"):
            category_name = translit_key(data.get("Name") or "").replace("|", "_")
            data["category_id"] = f"cat_{category_name}_<placeholder>"
        licenses = data.get("Лицензии")
        if not licenses:
            data["Лицензии"] = []
        elif isinstance(licenses, str):
            data["Лицензии"] = [lic.strip() for lic in licenses.split(",") if lic.strip()]
        return cls.model_validate(data)


class Currency(BaseModel):
    className: str = Field(...)
    value: StrictInt = Field(...)

    @classmethod
    def from_raw(cls, data: dict[str, Any]) -> Currency:
        return cls.model_validate(data)


class CurrencyType(BaseModel):
    currencyName: str = Field(..., alias="Валюта")
    currencies: list[str] = Field(...)

    @classmethod
    def from_raw(cls, data: dict[str, Any]) -> CurrencyType:
        currencies = data.get("currencies")
        if not currencies:
            data["currencies"] = []
        elif isinstance(currencies, str):
            data["currencies"] = [c.strip() for c in currencies.split(",") if c.strip()]
        return cls.model_validate(data)


class License(BaseModel):
    licenseId: str = Field(...)
    licenseName: str = Field(...)
    description: str = Field(...)

    @classmethod
    def from_raw(cls, data: dict[str, Any]) -> License:
        return cls.model_validate(data)


class GeneralSettings(BaseModel):
    version: str = Field("1.0.1", alias="версия")
    serverID: str = Field(..., alias="сервер")
    licenses: list[str] = Field([], alias="лицензии")
    traders: list[str] = Field([], alias="торговцы")
    traderObjects: list = Field([], alias="объекты торговцев")

    @classmethod
    def from_raw(cls, data: list[dict[str, Any]]) -> GeneralSettings:
        row: dict[str, Any] = data[0]
        licenses = row.get("лицензии")
        if not licenses:
            row["лицензии"] = []
        traders = row.get("торговцы")
        if not traders:
            row["торговцы"] = []
        elif isinstance(traders, str):
            row["торговцы"] = [t.strip() for t in traders.split(",") if t.strip()]
        trader_objects = row.get("объекты торговцев")
        if not trader_objects:
            row["объекты торговцев"] = []
        return cls.model_validate(row)


class AcceptedStates(BaseModel):
    acceptWorn: bool = Field(..., alias="принимать поношенное")
    coefficientWorn: float = Field(..., alias="коеффициент поношенного")
    acceptDamaged: bool = Field(..., alias="принимать поврежденное")
    coefficientDamaged: float = Field(..., alias="коеффициент поврежденного")
    acceptBadlyDamaged: bool = Field(..., alias="принимать сильно поврежденное")
    coefficientBadlyDamaged: float = Field(..., alias="коеффициент сильно поврежденного")

    @classmethod
    def from_raw(cls, data: list[dict[str, Any]]) -> AcceptedStates:
        row: dict[str, Any] = data[0]
        return cls.model_validate(row)


class TraderPrices(BaseModel):
    className: str = Field(...)
    prices: dict[str, dict[str, int]] = Field(default_factory=dict)

    @classmethod
    def from_raw(cls, data: dict[str, Any], trader_names: list[str]) -> TraderPrices:
        prices_dict: dict[str, dict[str, int]] = {}
        for name in trader_names:
            key = translit_key(name)
            sell_val = data.get(f"{name} продажа")
            buy_val = data.get(f"{name} покупка")
            if sell_val is None and buy_val is None:
                continue
            prices_dict[key] = {"sell": int(sell_val or 0), "buy": int(buy_val or 0)}
        data["prices"] = prices_dict
        return cls.model_validate(data)


class Product(BaseModel):
    parent_class: str | None = Field(None, alias="Вариант для")
    product_id: str = Field(...)
    className: str = Field(...)
    category: str = Field(..., alias="Категория")
    base_price: int = Field(..., alias="Себестоимость")
    buy_ratio: float = Field(..., alias="Наценка продажи игроком")
    stockSettings: float = Field(..., alias="Сток")
    maxStock: float | None = Field(100, alias="Запас")
    tradeQuantity: float = Field(16, alias="Режим")
    coefficient: float = Field(1.0, alias="Коефициент")
    attachments_list: list[str] = Field([], alias="Обвес")
    trader_access: dict[str, bool] = Field(default_factory=dict)
    trader_ratios: dict[str, float] = Field(default_factory=dict)

    @classmethod
    def from_raw(cls, data: dict[str, Any], trader_names: list[str]) -> Product:
        if not data.get("product_id"):
            data["product_id"] = f"prod_{data.get('className')}_<placeholder>"
        data["Вариант для"] = data.get("Вариант для") or None

        raw_att = data.get("Обвес")
        if isinstance(raw_att, str) and raw_att.strip():
            data["Обвес"] = [a.strip() for a in raw_att.split(",") if a.strip()]
        elif not raw_att:
            data["Обвес"] = []

        access_dict: dict[str, bool] = {}
        ratios_dict: dict[str, float] = {}
        for name in trader_names:
            key = translit_key(name)
            access_val = data.get(name)
            if access_val is None:
                access_dict[key] = False
            elif isinstance(access_val, str):
                access_dict[key] = access_val.lower() in ("true", "1")
            else:
                access_dict[key] = bool(access_val)

            ratio_col = f"{name} наценка"
            ratio_val = data.get(ratio_col)
            if ratio_val is None:
                ratios_dict[key] = 1.0
            else:
                try:
                    ratios_dict[key] = float(ratio_val)
                except (ValueError, TypeError):
                    ratios_dict[key] = 1.0

        data["trader_access"] = access_dict
        data["trader_ratios"] = ratios_dict

        return cls.model_validate(data)


class Loadout(BaseModel):
    id: int = Field(...)
    className: str = Field(...)
    slotName: str = Field(...)
    attachments: list[str] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, data: dict[str, Any]) -> Loadout:
        raw_att = data.get("attachments")
        if raw_att and isinstance(raw_att, str):
            try:
                parsed = json.loads(raw_att)
                if isinstance(parsed, list):
                    data["attachments"] = [str(item) for item in parsed if item]
                else:
                    data["attachments"] = []
            except json.JSONDecodeError:
                data["attachments"] = [a.strip() for a in raw_att.split(",") if a.strip()]
        elif not raw_att:
            data["attachments"] = []
        return cls.model_validate(data)
