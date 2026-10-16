import pytest

from research_core.json_integrity import strict_json_object


@pytest.mark.parametrize(
    "raw", ['{"code":"1234","code":"5678"}', '{"nested":{"units":1,"units":2}}', '{"value":NaN}', '{"value":Infinity}', '{"value":-Infinity}', "[]", "null"]
)
def test_ambiguous_or_non_object_artifact_json_is_rejected(raw: str):
    with pytest.raises(ValueError):
        strict_json_object(raw)


def test_artifact_values_keep_zero_missing_unicode_and_numeric_units():
    raw = '{"issuer":"測試","cash":0,"missing":null,"shares":0.125,"nested":{"status":"source_explicit"}}'
    expected = {"issuer": "測試", "cash": 0, "missing": None, "shares": 0.125, "nested": {"status": "source_explicit"}}
    assert strict_json_object(raw) == expected
    assert strict_json_object(raw.encode("utf-8")) == expected
