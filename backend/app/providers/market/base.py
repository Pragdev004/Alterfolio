from abc import ABC, abstractmethod

from app.schemas.stock import StockQuote


class BaseMarketProvider(ABC):
	"""
	Base contract for all market data providers.
	"""

	@abstractmethod
	def get_stock_quote(
		self,
		symbol: str,
	) -> StockQuote:
		"""
		Returns the latest stock quote.
		"""
		raise NotImplementedError
