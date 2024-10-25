# utils/crypto_rate.py

import aiohttp
import logging

logger = logging.getLogger(__name__)

async def get_crypto_rate(crypto: str) -> float:
    """
    Получает текущий курс указанной криптовалюты к RUB.

    :param crypto: Символ криптовалюты (например, 'BTC', 'LTC').
    :return: Курс криптовалюты в RUB.
    :raises ValueError: Если криптовалюта не поддерживается или данные не найдены.
    :raises Exception: При ошибках запроса к API.
    """
    crypto = crypto.lower()
    supported_cryptos = {
        'btc': 'bitcoin',
        'ltc': 'litecoin'
    }

    if crypto not in supported_cryptos:
        logger.error(f"Unsupported crypto type requested: {crypto}")
        raise ValueError(f"Unsupported crypto type: {crypto}")

    crypto_id = supported_cryptos[crypto]
    url = 'https://api.coingecko.com/api/v3/simple/price'
    params = {
        'ids': crypto_id,
        'vs_currencies': 'rub',
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"Failed to fetch rate for {crypto.upper()}: Status {resp.status}")
                    raise Exception(f"API request failed with status {resp.status}")

                data = await resp.json()
                rate = data.get(crypto_id, {}).get('rub')
                if rate is None:
                    logger.error(f"RUB rate not found for {crypto.upper()}")
                    raise ValueError(f"RUB rate not found for {crypto.upper()}")

                logger.info(f"Fetched rate for {crypto.upper()}: {rate} RUB")
                return rate
    except Exception as e:
        logger.exception(f"Error fetching crypto rate for {crypto.upper()}: {e}")
        raise
