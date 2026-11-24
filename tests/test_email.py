from email import message_from_bytes
from pathlib import Path

import pytest

from tracker.core.email import Email, send
from tracker.core.settings import Settings


def make_settings(tmp_path: Path, **overrides) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path, **overrides)


def test_dry_run_writes_an_eml_file(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, smtp_user="me@gmail.com", alert_to="me@gmail.com")

    path = send(Email("[tracker] OK run", "all good\n", "<p>all good</p>"), settings)

    assert path is not None and path.parent == tmp_path / "outbox"
    msg = message_from_bytes(path.read_bytes())
    assert msg["Subject"] == "[tracker] OK run"
    assert msg["To"] == "me@gmail.com"
    assert msg.is_multipart()  # plain text + HTML alternative


def test_real_send_requires_credentials(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, email_dry_run=False)

    with pytest.raises(RuntimeError, match="SMTP_APP_PASSWORD"):
        send(Email("x", "y"), settings)
