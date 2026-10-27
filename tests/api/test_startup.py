from pathlib import Path

import pytest

from app.core.config import get_settings
from app.main import create_app


def test_the_app_refuses_to_start_without_a_policy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)  # no .env file here
    monkeypatch.delenv("SCREENING_UNAVAILABLE_POLICY", raising=False)
    get_settings.cache_clear()
    with pytest.raises(SystemExit) as caught:
        create_app()
    assert "SCREENING_UNAVAILABLE_POLICY" in str(caught.value)
    get_settings.cache_clear()
