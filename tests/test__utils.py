from models._utils import next_input_trader_id, next_output_trader_id, reset_counters, translit_key


class TestTranslitKey:
    def test_cyrillic_to_latin(self) -> None:
        assert translit_key("Рыбак") == "rybak"

    def test_with_spaces(self) -> None:
        assert translit_key("Баба Нюра") == "baba_njura"

    def test_already_latin(self) -> None:
        assert translit_key("hello") == "hello"

    def test_empty_string(self) -> None:
        assert translit_key("") == ""

    def test_mixed(self) -> None:
        assert translit_key("Черный рынок") == "chernyj_rynok"


class TestCounters:
    def setup_method(self) -> None:
        reset_counters()

    def test_input_counter_starts_at_zero(self) -> None:
        assert next_input_trader_id() == 0

    def test_output_counter_starts_at_zero(self) -> None:
        assert next_output_trader_id() == 0

    def test_counters_are_independent(self) -> None:
        i1 = next_input_trader_id()
        o1 = next_output_trader_id()
        i2 = next_input_trader_id()
        o2 = next_output_trader_id()
        assert i2 == i1 + 1
        assert o2 == o1 + 1
