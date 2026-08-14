from app.models.enums import AssetType, Exchange


_KNOWN_EXCHANGE_SUFFIXES = (".NS", ".BO")


def canonicalize_symbol(*, symbol: str, asset_type: AssetType, exchange: Exchange) -> str:
    normalized = symbol.strip().upper()

    if not normalized:
        return normalized

    if asset_type == AssetType.STOCK and exchange in {Exchange.NSE, Exchange.BSE}:
        for suffix in _KNOWN_EXCHANGE_SUFFIXES:
            if normalized.endswith(suffix):
                return normalized[: -len(suffix)]

    return normalized
