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


# ─────────────────────────────────────────────────────────────────
# CRUD helpers — לשימוש ה-UI
# בדיקות מבוצעות מול קובץ זמני בנפרד מ-data/customer_mappings.json
# כדי לא לדרוס את הקובץ האמיתי.
# ─────────────────────────────────────────────────────────────────
class TestCRUD:
    @pytest.fixture
    def temp_mappings(self, tmp_path, monkeypatch):
        """מפנה את _DATA_PATH לקובץ זמני, טוען בסיס תקין, ומחזיר קבועים."""
        import json as _json

        from core import _customer_data as cd

        temp_file = tmp_path / "customer_mappings.json"
        temp_file.write_text(
            _json.dumps(_valid_data(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        monkeypatch.setattr(cd, "_DATA_PATH", temp_file)
        cd.reload_mappings()
        yield cd
        # cleanup: ננסה להחזיר את המצב המקורי כדי לא להפיל בדיקות אחרות
        try:
            monkeypatch.undo()
            cd.reload_mappings()
        except Exception:
            pass

    def test_list_customers_returns_canonical_names(self, temp_mappings):
        names = temp_mappings.list_customers()
        assert "RAFAEL" in names
        assert all(isinstance(n, str) and n.strip() for n in names)

    def test_get_customer_record_returns_all_fields(self, temp_mappings):
        rec = temp_mappings.get_customer_record("RAFAEL")
        assert rec["name"] == "RAFAEL"
        assert "1931" in rec["cage_codes"]
        assert rec["default_cage"] == "1931"
        assert "RAFAEL DEFENSE" in rec["aliases"]
        assert "BP" in rec["pn_prefixes"]
        assert rec["spec_patterns"] == [r"^GEN[\._\s]?\d"]

    def test_get_record_for_unknown_customer_is_empty(self, temp_mappings):
        rec = temp_mappings.get_customer_record("NONEXISTENT")
        assert rec["cage_codes"] == []
        assert rec["default_cage"] == ""

    def test_empty_record_template(self, temp_mappings):
        rec = temp_mappings.empty_customer_record("ACME")
        assert rec["name"] == "ACME"
        assert rec["cage_codes"] == []
        assert rec["spec_patterns"] == []

    def test_upsert_adds_new_customer(self, temp_mappings):
        temp_mappings.upsert_customer({
            "name": "ACME Aerospace",
            "cage_codes": ["AC001", "AC002"],
            "default_cage": "AC001",
            "aliases": ["ACME", "ACME AEROSPACE"],
            "pn_prefixes": ["AC"],
            "spec_patterns": [r"^AC-\d{4}"],
        })
        assert "ACME Aerospace" in temp_mappings.list_customers()
        rec = temp_mappings.get_customer_record("ACME Aerospace")
        assert "AC001" in rec["cage_codes"]
        assert "AC002" in rec["cage_codes"]
        assert rec["default_cage"] == "AC001"

    def test_upsert_normalizes_to_uppercase(self, temp_mappings):
        """CAGE / aliases / prefixes צריכים להיכתב ב-uppercase."""
        temp_mappings.upsert_customer({
            "name": "Test Customer",
            "cage_codes": ["ab12"],
            "default_cage": "ab12",
            "aliases": ["test"],
            "pn_prefixes": ["tx"],
            "spec_patterns": [],
        })
        rec = temp_mappings.get_customer_record("Test Customer")
        assert "AB12" in rec["cage_codes"]
        assert rec["default_cage"] == "AB12"
        assert "TEST" in rec["aliases"]
        assert "TX" in rec["pn_prefixes"]

    def test_upsert_replaces_existing_customer(self, temp_mappings):
        """upsert על שם קיים מחליף את כל הערכים שלו."""
        temp_mappings.upsert_customer({
            "name": "RAFAEL",
            "cage_codes": ["9999"],
            "default_cage": "9999",
            "aliases": ["NEW ALIAS"],
            "pn_prefixes": ["XX"],
            "spec_patterns": [],
        })
        rec = temp_mappings.get_customer_record("RAFAEL")
        assert rec["cage_codes"] == ["9999"]
        assert "1931" not in rec["cage_codes"]
        assert "BP" not in rec["pn_prefixes"]
        assert rec["aliases"] == ["NEW ALIAS"]

    def test_upsert_with_rename(self, temp_mappings):
        temp_mappings.upsert_customer(
            {
                "name": "RAFAEL Advanced",
                "cage_codes": ["1931"],
                "default_cage": "1931",
                "aliases": [],
                "pn_prefixes": [],
                "spec_patterns": [],
            },
            original_name="RAFAEL",
        )
        names = temp_mappings.list_customers()
        assert "RAFAEL Advanced" in names
        assert "RAFAEL" not in names

    def test_upsert_with_empty_name_raises(self, temp_mappings):
        with pytest.raises(ValueError):
            temp_mappings.upsert_customer({"name": "  "})

    def test_upsert_with_invalid_cage_raises(self, temp_mappings):
        with pytest.raises(ValueError):
            temp_mappings.upsert_customer({
                "name": "Bad CAGE Customer",
                "cage_codes": ["AB-CD"],
                "spec_patterns": [],
            })

    def test_upsert_with_invalid_regex_raises(self, temp_mappings):
        with pytest.raises(ValueError):
            temp_mappings.upsert_customer({
                "name": "Bad Regex Customer",
                "cage_codes": [],
                "spec_patterns": ["[invalid("],
            })

    def test_delete_removes_customer(self, temp_mappings):
        temp_mappings.delete_customer("RAFAEL")
        assert "RAFAEL" not in temp_mappings.list_customers()
        rec = temp_mappings.get_customer_record("RAFAEL")
        assert rec["cage_codes"] == []
        assert rec["default_cage"] == ""

    def test_delete_with_empty_name_raises(self, temp_mappings):
        with pytest.raises(ValueError):
            temp_mappings.delete_customer("")

    def test_save_is_atomic_persists_to_disk(self, temp_mappings, tmp_path):
        """אחרי upsert — הקובץ JSON על הדיסק מכיל את הערך החדש."""
        import json as _json
        temp_mappings.upsert_customer({
            "name": "Persistence Test",
            "cage_codes": ["1234"],
            "default_cage": "1234",
            "aliases": [],
            "pn_prefixes": [],
            "spec_patterns": [],
        })
        # קוראים את הקובץ ישירות
        raw = _json.loads(temp_mappings._DATA_PATH.read_text(encoding="utf-8"))
        assert raw["customer_to_default_cage"]["Persistence Test"] == "1234"
        assert raw["cage_to_customer"]["1234"] == "Persistence Test"

    def test_reload_mutates_constants_in_place(self, temp_mappings):
        """אחרי reload — הקבועים שב-import מודולים אחרים ראו עדיין המעודכנים.

        בודקים זאת ע"י שמירת הזהות (id) של הקבוע לפני ואחרי reload — id חייב
        להיות זהה (אותו object), אבל התוכן שונה.
        """
        original_id = id(temp_mappings.CAGE_TO_CUSTOMER)
        temp_mappings.upsert_customer({
            "name": "Mutate Test",
            "cage_codes": ["AB123"],
            "spec_patterns": [],
        })
        assert id(temp_mappings.CAGE_TO_CUSTOMER) == original_id
        assert temp_mappings.CAGE_TO_CUSTOMER.get("AB123") == "Mutate Test"
