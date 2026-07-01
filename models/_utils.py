import itertools
from transliterate import translit


_input_trader_counter = itertools.count(start=0)
_output_trader_counter = itertools.count(start=0)


def next_input_trader_id() -> int:
    return next(_input_trader_counter)


def next_output_trader_id() -> int:
    return next(_output_trader_counter)


def reset_counters() -> None:
    global _input_trader_counter, _output_trader_counter
    _input_trader_counter = itertools.count(start=0)
    _output_trader_counter = itertools.count(start=0)


def translit_key(name: str) -> str:
    return translit(name, 'ru', reversed=True).replace(" ", "_").lower()
