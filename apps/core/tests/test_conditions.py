import pytest

from apps.core.conditions import apply_operator, evaluate_condition, resolve_value


def test_resolve_value_prefers_context_over_subject_attribute():
    class Subject:
        field = "from-subject"

    assert resolve_value("field", Subject(), {"field": "from-context"}) == "from-context"
    assert resolve_value("field", Subject(), {}) == "from-subject"


def test_resolve_value_supports_dotted_paths():
    class Inner:
        value = 42

    class Outer:
        inner = Inner()

    assert resolve_value("inner.value", Outer(), {}) == 42


@pytest.mark.parametrize(
    ("op", "actual", "expected", "result"),
    [
        ("eq", 5, 5, True),
        ("neq", 5, 6, True),
        ("in", "a", ["a", "b"], True),
        ("between", 5, [1, 10], True),
        ("between", 15, [1, 10], False),
        ("gte", 5, 5, True),
        ("lte", 4, 5, True),
    ],
)
def test_apply_operator(op, actual, expected, result):
    assert apply_operator(op, actual, expected) is result


def test_apply_operator_none_actual_never_matches():
    assert apply_operator("eq", None, None) is False


def test_apply_operator_rejects_unknown_op():
    with pytest.raises(ValueError, match="Unsupported operator"):
        apply_operator("bogus", 1, 1)


def test_evaluate_condition_empty_always_matches():
    matched, reason = evaluate_condition({}, object(), {})
    assert matched is True
    assert "always applies" in reason
