from app.providers.news.yahoo import YahooNewsProvider

provider = YahooNewsProvider()

news = provider.get_company_news("RELIANCE")

print(news)