import pytest

from app.services.report.templates import DEFAULT_TEMPLATE_KEY, get_template, register_template


def test_default_template_is_registered():
    builder = get_template(None)
    assert builder is not None


def test_explicit_known_key_resolves_to_same_builder_as_default():
    assert get_template(DEFAULT_TEMPLATE_KEY) is get_template(None)


def test_unknown_template_key_raises_clear_error():
    with pytest.raises(ValueError, match="Unknown report template"):
        get_template("no_existe")


def test_register_template_makes_a_new_key_resolvable():
    def _dummy_builder(collected, narrative):
        return []

    register_template("dummy_test_template", _dummy_builder)
    assert get_template("dummy_test_template") is _dummy_builder
