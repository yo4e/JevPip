import pytest

from jevpip.config import Settings


def test_live_trading_cannot_be_enabled():
    with pytest.raises(ValueError):
        Settings(live_trading=True)
