"""
Unit tests ל-core._customer_data — schema validation של data/customer_mappings.json.

הרצה:
    pytest tests/test_customer_data.py -v
"""
import pytest

from core._customer_data import _validate


# ─────────────────────────────────────────────────────────────────
# בסיס תקין — כל הבדיקות מתחילות מ-deep copy של זה
# ─────────────────────────────────────────────────────────────────
def _valid_data():
    return {
        "cage_to_customer": {"1931": "RAFAEL"},
        "customer_to_default_cage": {"RAFAEL": "1931"},
        "customer_aliases": {"RAFAEL DEFENSE": "RAFAEL"},
        "pn_prefix_to_customer": {"BP": "RAFAEL"},
        "customer_internal_spec_patterns": {
            "RAFAEL": [r"^GEN[\._\s]?\d"],
        },
    }


# ─────────────────────────────────────────────────────────────────
# Happy path
# ─────────────────────────────────────────────────────────────────
class TestValidatePasses:
    def test_minimal_valid_data(self):
        # לא זורק
        _validate(_valid_data())

    def test_empty_pattern_lists_allowed(self):
        d = _valid_data()
        d["customer_internal_spec_patterns"]["NEW_CUSTOMER"] = []
        _validate(d)


# ─────────────────────────────────────────────────────────────────
# Missing keys
# ─────────────────────────────────────────────────────────────────
class TestRequiredKeys:
    @pytest.mark.parametrize("missing_key", [
        "cage_to_customer",
        "customer_to_default_cage",
        "customer_aliases",
        "pn_prefix_to_customer",
        "customer_internal_spec_patterns",
    ])
    def test_missing_key_raises(self, missing_key):
        d = _valid_data()
        del d[missing_key]
        with pytest.raises(KeyError) as exc:
            _validate(d)
        assert missing_key in str(exc.value)


# ─────────────────────────────────────────────────────────────────
# Type validation
# ─────────────────────────────────────────────────────────────────
class TestTypeValidation:
    def test_value_is_not_dict_raises(self):
        d = _valid_data()
        d["cage_to_customer"] = "not a dict"
        with pytest.raises(TypeError) as exc:
            _validate(d)
        assert "object" in str(exc.value) or "dict" in str(exc.value).lower()

    def test_int_value_raises(self):
        # ערך מספרי במקום string
        d = _valid_data()
        d["customer_aliases"]["KEY"] = 123
        with pytest.raises(TypeError):
            _validate(d)

    def test_empty_string_value_raises(self):
        d = _valid_data()
        d["customer_aliases"]["KEY"] = ""
        with pytest.raises(ValueError):
            _validate(d)


# ─────────────────────────────────────────────────────────────────
# CAGE format validation
# ─────────────────────────────────────────────────────────────────
class TestCageValidation:
    @pytest.mark.parametrize("bad_cage", [
        "1!1",         # special char
        "AB-CD",       # dash
        "AB",          # too short (2 chars)
        "ABCDEFG",     # too long (7 chars)
    ])
    def test_invalid_cage_in_keys_raises(self, bad_cage):
        d = _valid_data()
        d["cage_to_customer"][bad_cage] = "Some Customer"
        with pytest.raises(ValueError) as exc:
            _validate(d)
        assert "CAGE" in str(exc.value)

    @pytest.mark.parametrize("bad_cage", ["1!1", "AB-CD", "X"])
    def test_invalid_cage_in_default_values_raises(self, bad_cage):
        d = _valid_data()
        d["customer_to_default_cage"]["Some Customer"] = bad_cage
        with pytest.raises(ValueError):
            _validate(d)

    @pytest.mark.parametrize("good_cage", ["1931", "0772A", "1GYX", "36035"])
    def test_valid_cage_passes(self, good_cage):
        d = _valid_data()
        d["cage_to_customer"][good_cage] = "Some Customer"
        _validate(d)  # לא זורק


# ─────────────────────────────────────────────────────────────────
# Internal spec patterns — regex compilation
# ─────────────────────────────────────────────────────────────────
class TestInternalSpecPatterns:
    def test_invalid_regex_raises(self):
        d = _valid_data()
        d["customer_internal_spec_patterns"]["RAFAEL"] = ["[invalid("]
        with pytest.raises(ValueError) as exc:
            _validate(d)
        assert "regex" in str(exc.value).lower()

    def test_pattern_must_be_string(self):
        d = _valid_data()
        d["customer_internal_spec_patterns"]["RAFAEL"] = [123]
        with pytest.raises(TypeError):
            _validate(d)

    def test_patterns_must_be_list(self):
        d = _valid_data()
        d["customer_internal_spec_patterns"]["RAFAEL"] = "not a list"
        with pytest.raises(TypeError):
            _validate(d)


# ─────────────────────────────────────────────────────────────────
# Real file passes validation
# ─────────────────────────────────────────────────────────────────
class TestRealDataLoads:
    def test_actual_customer_mappings_json_passes(self):
        """data/customer_mappings.json הקיים חייב לעבור validation."""
        # אם זה לא עובר — קובץ הנתונים פגום וצריך לתקן
        from core._customer_data import _RAW
        _validate(_RAW)
