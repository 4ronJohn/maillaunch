import argparse

import pytest

from main import _engine_settings, build_parser
from utils.config import ConfigError, load_settings


def test_engine_settings_uses_yaml_delay_defaults(tmp_path):
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(
        "send:\n  min_delay_seconds: 5\n  max_delay_seconds: 8\n",
        encoding="utf-8",
    )
    settings = load_settings(config_path)

    engine_settings = _engine_settings(
        settings,
        argparse.Namespace(min_delay=None, max_delay=None),
    )

    assert engine_settings.min_delay_seconds == 5
    assert engine_settings.max_delay_seconds == 8


def test_cli_delay_values_override_yaml_for_send_and_resume(tmp_path):
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(
        "send:\n  min_delay_seconds: 60\n  max_delay_seconds: 180\n",
        encoding="utf-8",
    )
    settings = load_settings(config_path)
    parser = build_parser()

    send_args = parser.parse_args(
        [
            "send",
            "--csv",
            "recipients.csv",
            "--subject",
            "Subject",
            "--body-file",
            "body.txt",
            "--min-delay",
            "5",
            "--max-delay",
            "8",
        ]
    )
    resume_args = parser.parse_args(
        ["resume", "campaign-1", "--min-delay", "7", "--max-delay", "9"]
    )

    send_settings = _engine_settings(settings, send_args)
    resume_settings = _engine_settings(settings, resume_args)

    assert (send_settings.min_delay_seconds, send_settings.max_delay_seconds) == (5, 8)
    assert (resume_settings.min_delay_seconds, resume_settings.max_delay_seconds) == (7, 9)


@pytest.mark.parametrize(
    "args",
    [
        argparse.Namespace(min_delay=-1, max_delay=8),
        argparse.Namespace(min_delay=5, max_delay=-1),
    ],
)
def test_engine_settings_rejects_negative_effective_delays(args):
    settings = load_settings()

    with pytest.raises(ConfigError, match="cannot be negative"):
        _engine_settings(settings, args)


def test_engine_settings_rejects_reversed_effective_delays():
    settings = load_settings()

    with pytest.raises(ConfigError, match="delay bounds are invalid"):
        _engine_settings(
            settings,
            argparse.Namespace(min_delay=9, max_delay=8),
        )