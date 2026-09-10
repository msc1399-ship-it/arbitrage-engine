from typing import Protocol

from models.market_data import MarketData


class MarketConnector(Protocol):
    @property
    def configured(self) -> bool: ...

    def get_market_data(self, set_num: str, **kwargs) -> MarketData: ...
