import signal
import requests
import time
from time import sleep

# --------------------------
# Global Settings and API Key
# --------------------------
API_KEY = {'X-API-Key': 'ABIXYN28'}

SPREAD = 0.15              # Fixed price offset for bid/ask orders.
BASE_ORDER_VOLUME = 1000   # Base volume per order (each side).
ORDER_RATE = 10            # Maximum orders per second allowed by the API.
MIN_SPEED_BUMP = 0.01      # Minimum delay between orders (seconds).
CASE_START = 5             # Case start time in seconds.
CASE_END = 295             # Case end time in seconds.
POSITION_LIMIT = 25000     # Maximum net position allowed per security.
TICK_THRESHOLD = 10         # Ticks after which an unfilled limit order is converted to a market order.

shutdown = False
# Moving average storage for transaction times.
transaction_times = []
MOVING_AVERAGE_WINDOW = 10

# Global orders dictionary for tracking open orders.
orders = {}

# --------------------------
# Exception and Signal Handling
# --------------------------
class ApiException(Exception):
    pass

def signal_handler(signum, frame):
    global shutdown
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    shutdown = True

# --------------------------
# Helper Functions for REST API Calls
# --------------------------
def get_tick(session):
    resp = session.get('http://localhost:9999/v1/case')
    if resp.status_code == 401:
        raise ApiException('API key error.')
    return resp.json()['tick']

def ticker_close(session, ticker):
    """
    Retrieve the most recent close price (last tick).
    (This function is retained for reference but is now replaced in trading logic.)
    """
    payload = {'ticker': ticker, 'limit': 1}
    resp = session.get('http://localhost:9999/v1/securities/history', params=payload)
    if resp.status_code == 401:
        raise ApiException('API key error.')
    data = resp.json()
    if data:
        return data[0]['close']
    else:
        raise ApiException(f'No price history for ticker {ticker}')

def get_average_price(session, ticker, num_ticks=5):
    """
    Compute the average close price from the last num_ticks.
    This smooths out random fluctuations by averaging recent tick data.
    """
    payload = {'ticker': ticker, 'limit': num_ticks}
    resp = session.get('http://localhost:9999/v1/securities/history', params=payload)
    if resp.status_code == 401:
        raise ApiException('API key error.')
    data = resp.json()
    if data:
        total = 0
        count = 0
        for tick_data in data:
            close_price = tick_data.get('close')
            if close_price is not None:
                total += close_price
                count += 1
        if count > 0:
            return total / count
        else:
            raise ApiException("No close price data found.")
    else:
        raise ApiException(f"No price history for ticker {ticker}")

def submit_order(session, payload):
    """
    Submit an order while checking for rate-limit errors.
    If a 429 error is returned, respect the Retry-After header.
    """
    response = session.post('http://localhost:9999/v1/orders', params=payload)
    if response.status_code == 429:
        retry_after = float(response.headers.get('Retry-After', 1))
        print(f"Rate limit hit. Retrying after {retry_after} seconds.")
        sleep(retry_after)
        return submit_order(session, payload)
    if response.status_code == 200:
        data = response.json()
        orders[data.get('order_id')] = data
    return response.status_code == 200

def update_order_data(session):
    """
    Update orders from the API; remove fully filled orders.
    """
    global orders
    for order_id, order in list(orders.items()):
        response = session.get(f'http://localhost:9999/v1/orders/{order_id}')
        if response.status_code != 200:
            print(f"Failed updating order data for order id {order_id}.")
            continue
        data = response.json()
        if data.get('quantity') == data.get('quantity_filled'):
            del orders[order_id]
        else:
            orders[order_id] = data
    return True

def get_best_prices(session, ticker):
    """
    Retrieve current best bid and ask prices for a given ticker.
    """
    payload = {'ticker': ticker}
    resp = session.get('http://localhost:9999/v1/securities/book', params=payload)
    if resp.status_code == 401:
        raise ApiException('API key error.')
    data = resp.json()
    best_bid = data["bid"][0]["price"] if "bid" in data and data["bid"] else None
    best_ask = data["ask"][0]["price"] if "ask" in data and data["ask"] else None
    if best_bid is not None and best_ask is not None and best_ask - best_bid <= 0.01:
        best_bid -= 1
        best_ask += 1
    return best_bid, best_ask

def buy_sell(session, ticker, avg_price, spread, volume):
    """
    Submit a paired BUY and SELL order using the average price as the reference.
    Returns the transaction time.
    """
    buy_price = avg_price - spread
    sell_price = avg_price + spread
    buy_payload = {'ticker': ticker, 'type': 'LIMIT', 'quantity': volume, 'action': 'BUY', 'price': buy_price}
    sell_payload = {'ticker': ticker, 'type': 'LIMIT', 'quantity': volume, 'action': 'SELL', 'price': sell_price}
    start_time = time.time()
    submit_order(session, buy_payload)
    submit_order(session, sell_payload)
    end_time = time.time()
    return end_time - start_time

def modify_order(session, order):
    """
    Cancel and re-submit an order with an updated price.
    Adjust the price if the market has moved.
    """
    order_id = order.get('order_id')
    action = order.get('action')
    ticker = order.get('ticker')
    volume = order.get('quantity') - order.get('quantity_filled')
    current_price = order.get('price')
    best_bid, best_ask = get_best_prices(session, ticker)

    if action == 'BUY':
        if best_bid is not None and best_bid > current_price:
            new_price = current_price + 0.02
        else:
            new_price = current_price
    elif action == 'SELL':
        if best_ask is not None and best_ask < current_price:
            new_price = current_price - 0.2
        else:
            new_price = current_price
    else:
        return False

    new_price = round(new_price, 2)
    if new_price == current_price:
        return False

    url = f'http://localhost:9999/v1/orders/{order_id}'
    response = session.delete(url)
    if response.status_code == 200:
        print(f"Modified order ID {order_id} on {ticker}: {action} for {volume} shares updated from {current_price:.2f} to {new_price:.2f}.")
        payload = {'ticker': ticker, 'type': 'LIMIT', 'quantity': volume, 'action': action, 'price': new_price}
        submit_order(session, payload)
        return True
    else:
        print(f"Failed to modify order {order_id} on {ticker}.")
        return False

def modify_farthest_n_orders(session, n, ticker):
    """
    For a given ticker, fetch open orders and modify the n orders with the greatest price deviation.
    """
    resp = session.get('http://localhost:9999/v1/orders', params={'status': 'OPEN'})
    if resp.status_code != 200:
        return
    open_orders = resp.json()
    open_orders = [order for order in open_orders if order.get('ticker') == ticker]
    if not open_orders:
        return

    best_bid, best_ask = get_best_prices(session, ticker)
    def distance(order):
        action = order.get('action')
        price = order.get('price')
        if action == 'BUY' and best_bid is not None and price < best_bid:
            return best_bid - price
        elif action == 'SELL' and best_ask is not None and price > best_ask:
            return price - best_ask
        return 0
    open_orders.sort(key=lambda o: distance(o), reverse=True)
    orders_to_modify = open_orders[:n]
    for order in orders_to_modify:
        modify_order(session, order)

def calculate_speed_bump(txn_time):
    """
    Compute the adaptive delay (speed bump) based on a moving average of transaction times.
    """
    transaction_times.append(txn_time)
    if len(transaction_times) > MOVING_AVERAGE_WINDOW:
        transaction_times.pop(0)
    avg_txn_time = sum(transaction_times) / len(transaction_times)
    required_time = 1.0 / ORDER_RATE
    return max(required_time - avg_txn_time, MIN_SPEED_BUMP)

# --------------------------
# Conversion of Limit Orders to Market Orders
# --------------------------
def convert_stale_orders_to_market(session, current_tick, tick_threshold):
    """
    Iterate through tracked orders and convert orders that have been open
    for more than tick_threshold ticks from limit to market orders.
    """
    global orders
    for order_id, order in list(orders.items()):
        order_tick = order.get('tick', current_tick)
        if current_tick - order_tick >= tick_threshold:
            ticker = order.get('ticker')
            action = order.get('action')
            volume = order.get('quantity') - order.get('quantity_filled')
            url = f'http://localhost:9999/v1/orders/{order_id}'
            response = session.delete(url)
            if response.status_code == 200:
                print(f"Converting stale order {order_id} on {ticker} to MARKET order ({action}, volume: {volume}).")
                payload = {'ticker': ticker, 'type': 'MARKET', 'quantity': volume, 'action': action}
                submit_order(session, payload)
                del orders[order_id]
    return

# --------------------------
# Multi-Security and Evaluation Functions
# --------------------------
def get_available_securities(session):
    """
    Retrieve available securities from the API; filter for tradeable ones.
    """
    resp = session.get('http://localhost:9999/v1/securities')
    if resp.status_code == 401:
        raise ApiException('API key error.')
    securities = resp.json()
    return [sec for sec in securities if sec.get('is_tradeable')]

def evaluate_security(session, sec):
    """
    Compute a simple effective profit metric for a security based on the spread.
    """
    ticker = sec.get('ticker')
    best_bid, best_ask = get_best_prices(session, ticker)
    if best_bid is None or best_ask is None:
        return 0
    effective_spread = best_ask - best_bid
    return effective_spread

def choose_best_security(session):
    """
    Evaluate available securities and select the one with the highest effective spread.
    """
    securities = get_available_securities(session)
    best_sec = None
    best_metric = -1
    for sec in securities:
        metric = evaluate_security(session, sec)
        if metric > best_metric:
            best_metric = metric
            best_sec = sec
    if best_sec is None:
        raise ApiException("No tradeable securities available.")
    return best_sec

def get_portfolio_position(session, ticker):
    """
    Retrieve the current portfolio position for a given ticker from the API.
    """
    payload = {'ticker': ticker}
    resp = session.get('http://localhost:9999/v1/securities', params=payload)
    if resp.status_code == 401:
        raise ApiException('API key error.')
    if resp.status_code == 200:
        data = resp.json()
        for sec in data:
            if sec.get('ticker') == ticker:
                return sec.get('position', 0)
        return 0
    else:
        raise ApiException('Error retrieving portfolio position.')

def get_pending_volumes(session, ticker):
    """
    Retrieve total pending BUY and SELL volumes for a given ticker via the API.
    """
    resp = session.get('http://localhost:9999/v1/orders', params={'status': 'OPEN'})
    if resp.status_code == 401:
        raise ApiException('API key error.')
    if resp.status_code == 200:
        open_orders = resp.json()
        open_orders = [o for o in open_orders if o.get('ticker') == ticker]
        pending_buy = sum(o.get('quantity', 0) - o.get('quantity_filled', 0)
                          for o in open_orders if o.get('action') == 'BUY')
        pending_sell = sum(o.get('quantity', 0) - o.get('quantity_filled', 0)
                           for o in open_orders if o.get('action') == 'SELL')
        return pending_buy, pending_sell
    else:
        raise ApiException('Error retrieving pending orders.')

# --------------------------
# Main Trading Algorithm Logic (ALGO2e Improved)
# --------------------------
def main():
    global shutdown, BASE_ORDER_VOLUME
    with requests.Session() as session:
        session.headers.update(API_KEY)
        tick = get_tick(session)
        last_modify_time = time.time()
        
        while tick > CASE_START and tick < CASE_END and not shutdown:
            # Update local order state.
            update_order_data(session)
            
            # Retrieve the current tick and convert stale limit orders to market orders.
            tick = get_tick(session)
            convert_stale_orders_to_market(session, tick, TICK_THRESHOLD)
            
            current_time = time.time()
            # Every second, iterate over every available tradeable ticker and modify stale orders.
            if current_time - last_modify_time >= 1:
                securities = get_available_securities(session)
                for sec in securities:
                    ticker = sec.get('ticker')
                    modify_farthest_n_orders(session, 1, ticker)
                last_modify_time = current_time

            # Choose the best security to trade based on effective profit potential.
            best_sec = choose_best_security(session)
            ticker = best_sec.get('ticker')
            print(f"Trading on: {ticker}")

            # Retrieve portfolio position and pending volumes for the chosen security.
            position = get_portfolio_position(session, ticker)
            pending_buy, pending_sell = get_pending_volumes(session, ticker)
            print(f"Ticker: {ticker}\tPosition: {position}\tPending BUY: {pending_buy}\tPending SELL: {pending_sell}")
            
            potential_long = position + pending_buy + BASE_ORDER_VOLUME
            potential_short = position - pending_sell - BASE_ORDER_VOLUME
            
            if potential_long > POSITION_LIMIT or potential_short < -POSITION_LIMIT:
                print(f"Skipping orders for {ticker} due to position limits.")
                tick = get_tick(session)
                sleep(0.5)
                continue

            try:
                # Instead of using the last price, use the average of the last 5 ticks.
                avg_price = get_average_price(session, ticker, num_ticks=10)
            except ApiException as e:
                print(e)
                tick = get_tick(session)
                continue

            txn_time = buy_sell(session, ticker, avg_price, SPREAD, BASE_ORDER_VOLUME)
            delay = calculate_speed_bump(txn_time)
            print(f"Order pair submitted for {ticker}. Transaction time: {txn_time:.3f}s, delay: {delay:.3f}s")
            sleep(delay)
            tick = get_tick(session)
        
if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    main()
