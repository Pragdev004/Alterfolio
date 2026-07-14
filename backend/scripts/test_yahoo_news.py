from yfinance import Ticker

ticker = Ticker("RELIANCE.NS")

print("=" * 80)
print("NEWS")
print("=" * 80)

for article in ticker.news[:5]:
    print(article)
    print("-" * 80)