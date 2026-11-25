import pytest


@pytest.fixture(autouse=True)
def _no_real_ais_archive(monkeypatch, request):
    """completeness.check() reads the private AIS archive on the owner's PC.
    Keep tests independent of that file unless a test asks for the real one."""
    if "real_ais_check" in request.keywords:
        return
    from src import completeness
    monkeypatch.setattr(completeness, "check_ais_archive", lambda now, *a, **k: [])


def pytest_configure(config):
    config.addinivalue_line("markers", "real_ais_check: use the real completeness.check_ais_archive")
