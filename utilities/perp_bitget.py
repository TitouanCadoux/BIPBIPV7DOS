import ccxt
import pandas as pd
import time
from multiprocessing.pool import ThreadPool as Pool
import numpy as np

class PerpBitget():
    def __init__(self, apiKey=None, secret=None, password=None):
        bitget_auth_object = {
            "apiKey": apiKey,
            "secret": secret,
            "password": password,
            'options': {
                'defaultType': 'swap',
            }
        }
        if bitget_auth_object['secret'] is None:
            self._auth = False
            self._session = ccxt.bitget()
        else:
            self._auth = True
            self._session = ccxt.bitget(bitget_auth_object)
        self.market = self._session.load_markets()

    def authentication_required(fn):
        def wrapped(self, *args, **kwargs):
            if not self._auth:
                raise Exception("You must be authenticated to use this method")
            return fn(self, *args, **kwargs)
        return wrapped

    def get_last_historical(self, symbol, timeframe, limit):
        result = pd.DataFrame(data=self._session.fetch_ohlcv(
            symbol, timeframe, None, limit=limit))
        result.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        result['timestamp'] = pd.to_datetime(result['timestamp'], unit='ms')
        result.set_index('timestamp', inplace=True)
        return result

    def get_more_last_historical_async(self, symbol, timeframe, limit):
        max_threads = 4
        pool_size = round(limit / 100)

        def worker(i):
            try:
                return self._session.fetch_ohlcv(
                    symbol, timeframe, round(time.time() * 1000) - (i * 1000 * 60 * 60), limit=100)
            except Exception as err:
                raise Exception("Error on last historical on " + symbol + ": " + str(err))

        pool = Pool(max_threads)
        full_result = pool.map(worker, range(limit, 0, -100))
        full_result = np.array(full_result).reshape(-1, 6)
        result = pd.DataFrame(data=full_result, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        result['timestamp'] = pd.to_datetime(result['timestamp'], unit='ms')
        result.set_index('timestamp', inplace=True)
        return result.sort_index()

    def get_bid_ask_price(self, symbol):
        try:
            ticker = self._session.fetch_ticker(symbol)
        except BaseException as err:
            raise Exception(err)
        return {"bid": ticker["bid"], "ask": ticker["ask"]}

    def get_min_order_amount(self, symbol):
        return self._session.market(symbol)["limits"]["amount"]["min"]

    def convert_amount_to_precision(self, symbol, amount):
        return self._session.amount_to_precision(symbol, amount)

    def convert_price_to_precision(self, symbol, price):
        return self._session.price_to_precision(symbol, price)

    @authentication_required
    def place_limit_order(self, symbol, side, amount, price, reduce=False):
        try:
            return self._session.create_order(
                symbol,
                'limit',
                side,
                self.convert_amount_to_precision(symbol, amount),
                self.convert_price_to_precision(symbol, price),
                params={"reduceOnly": reduce}
            )
        except BaseException as err:
            raise Exception(err)

    @authentication_required
    def place_limit_stop_loss(self, symbol, side, amount, trigger_price, price, reduce=False):
        try:
            return self._session.create_order(
                symbol,
                'limit',
                side,
                self.convert_amount_to_precision(symbol, amount),
                self.convert_price_to_precision(symbol, price),
                params={
                    'stopPrice': self.convert_price_to_precision(symbol, trigger_price),
                    "triggerType": "market_price",
                    "reduceOnly": reduce
                }
            )
        except BaseException as err:
            raise Exception(err)

    @authentication_required
    def place_market_order(self, symbol, side, amount, reduce=False):
        try:
            return self._session.create_order(
                symbol,
                'market',
                side,
                self.convert_amount_to_precision(symbol, amount),
                None,
                params={"reduceOnly": reduce}
            )
        except BaseException as err:
            raise Exception(err)

    @authentication_required
    def place_market_stop_loss(self, symbol, side, amount, trigger_price, reduce=False):
        try:
            return self._session.create_order(
                symbol,
                'market',
                side,
                self.convert_amount_to_precision(symbol, amount),
                None,
                params={
                    'stopPrice': self.convert_price_to_precision(symbol, trigger_price),
                    "triggerType": "market_price",
                    "reduceOnly": reduce
                }
            )
        except BaseException as err:
            raise Exception(err)

    @authentication_required
    def get_balance_of_one_coin(self, coin):
        try:
            balance = self._session.fetch_balance()
            return balance['total'].get(coin, 0)
        except BaseException as err:
            raise Exception("An error occurred", err)

    @authentication_required
    def get_all_balance(self):
        try:
            return self._session.fetch_balance()
        except BaseException as err:
            raise Exception("An error occurred", err)

    @authentication_required
    def get_usdt_equity(self):
        try:
            balance = self._session.fetch_balance()
            return balance["info"][0]["usdtEquity"]
        except BaseException as err:
            raise Exception("An error occurred", err)

    @authentication_required
    def get_open_order(self, symbol, conditionnal=False):
        try:
            return self._session.fetch_open_orders(symbol, params={'stop': conditionnal})
        except BaseException as err:
            raise Exception("An error occurred", err)

    @authentication_required
    def get_my_orders(self, symbol):
        try:
            return self._session.fetch_orders(symbol)
        except BaseException as err:
            raise Exception("An error occurred", err)

    @authentication_required
    def get_open_position(self, symbol=None):
        try:
            symbols = [symbol] if symbol else list(self._session.markets.keys())
            positions = self._session.fetch_positions(symbols=symbols, params={"productType": "umcbl"})
            return [
                p for p in positions
                if float(p.get('contracts', 0)) > 0 and (symbol is None or p['symbol'] == symbol)
            ]
        except BaseException as err:
            raise Exception("An error occurred in get_open_position", err)

    @authentication_required
    def cancel_order_by_id(self, id, symbol, conditionnal=False):
        try:
            params = {'stop': True, "planType": "normal_plan"} if conditionnal else {}
            return self._session.cancel_order(id, symbol, params=params)
        except BaseException as err:
            raise Exception("An error occurred in cancel_order_by_id", err)

    @authentication_required
    def cancel_all_open_order(self):
        try:
            return self._session.cancel_all_orders(params={"marginCoin": "USDT"})
        except BaseException as err:
            raise Exception("An error occurred in cancel_all_open_order", err)

    @authentication_required
    def cancel_order_ids(self, ids=[], symbol=None):
        try:
            return self._session.cancel_orders(
                ids=ids,
                symbol=symbol,
                params={"marginCoin": "USDT"}
            )
        except BaseException as err:
            raise Exception("An error occurred in cancel_order_ids", err)

