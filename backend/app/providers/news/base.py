from abc import ABC, abstractmethod

from app.schemas.news import CompanyNews


class BaseNewsProvider(ABC):
	"""
	Base contract for all news providers.
	"""

	@abstractmethod
	def get_company_news(
		self,
		symbol: str,
	) -> CompanyNews:
		"""
		Returns recent company news.
		"""
		raise NotImplementedError
