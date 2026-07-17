from __future__ import annotations

from typing import Any

from models import input as input_models

_SINGLE_MODELS: dict[str, type] = {
    "general_settings": input_models.GeneralSettings,
    "accepted_states": input_models.AcceptedStates,
}

_LIST_MODELS: dict[str, type] = {
    "licenses": input_models.License,
    "traders_raw": input_models.Trader,
    "traders_loadouts": input_models.Loadout,
    "categories_template": input_models.Category,
    "products_all": input_models.Product,
    "currency_types_raw": input_models.CurrencyType,
    "currencies_raw": input_models.Currency,
}

_DICT_MODELS: dict[str, tuple[type, bool]] = {
    "prices_map": (input_models.TraderPrices, False),
}

_DICT_LIST_MODELS: dict[str, tuple[type, bool]] = {
    "loadouts_by_trader": (input_models.Loadout, True),
}


def serialize_data(data: dict[str, Any]) -> dict[str, Any]:
    """Pydantic models -> plain dicts for JSON storage."""
    result: dict[str, Any] = {}
    for key, val in data.items():
        if key in _SINGLE_MODELS:
            result[key] = val.model_dump(by_alias=True)
        elif key in _LIST_MODELS:
            result[key] = [v.model_dump(by_alias=True) for v in val]
        elif key in _DICT_MODELS:
            result[key] = {str(k): v.model_dump(by_alias=True) for k, v in val.items()}
        elif key in _DICT_LIST_MODELS:
            result[key] = {
                str(k): [item.model_dump(by_alias=True) for item in v] for k, v in val.items()
            }
        else:
            result[key] = val
    return result


def deserialize_data(data: dict[str, Any]) -> dict[str, Any]:
    """Plain dicts -> Pydantic models."""
    result: dict[str, Any] = {}
    for key, val in data.items():
        if key in _SINGLE_MODELS:
            result[key] = _SINGLE_MODELS[key].model_validate(val)
        elif key in _LIST_MODELS:
            model_cls = _LIST_MODELS[key]
            result[key] = [model_cls.model_validate(item) for item in val]
        elif key in _DICT_MODELS:
            model_cls, is_int_key = _DICT_MODELS[key]
            if is_int_key:
                result[key] = {
                    int(k): [model_cls.model_validate(i) for i in v] for k, v in val.items()
                }
            else:
                result[key] = {k: model_cls.model_validate(v) for k, v in val.items()}
        elif key in _DICT_LIST_MODELS:
            model_cls, is_int_key = _DICT_LIST_MODELS[key]
            if is_int_key:
                result[key] = {
                    int(k): [model_cls.model_validate(i) for i in v] for k, v in val.items()
                }
            else:
                result[key] = {k: [model_cls.model_validate(i) for i in v] for k, v in val.items()}
        else:
            result[key] = val
    return result
