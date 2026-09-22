from __future__ import annotations

import re
from collections.abc import Mapping


class TemplateError(ValueError):
    """Raised when a template references an unavailable value."""


_TOKEN = re.compile(r"{{\s*([^{}]+?)\s*}}")


def render_template(template: str, values: Mapping[str, object]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        if key not in values:
            raise TemplateError(f"template variable {key!r} is missing from the CSV")
        return str(values[key])

    return _TOKEN.sub(replace, template)
