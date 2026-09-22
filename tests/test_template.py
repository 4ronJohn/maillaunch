import pytest

from utils.template import TemplateError, render_template


def test_template_substitution():
    assert render_template("Hi {{name}} at {{ company }}", {"name": "John", "company": "ABC"}) == "Hi John at ABC"


def test_missing_key_is_actionable():
    with pytest.raises(TemplateError, match="company"):
        render_template("Hi {{name}} at {{company}}", {"name": "John"})


def test_nested_braces_are_left_literal():
    assert render_template("Value {{outer {{inner}}", {"inner": "x"}) == "Value {{outer x"
