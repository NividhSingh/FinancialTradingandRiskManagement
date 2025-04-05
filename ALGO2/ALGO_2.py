import signal
import requests
import time
from time import sleep

# --------------------------
# Global settings and API key
# --------------------------
API_KEY = {'X-API-Key': 'ABIXYN28'}
SPREAD = 0.02              # Price offset for bid/ask
ORDER_VOLUME = 5000         # Volume per order (each side)
ORDER_RATE = 10            # Maximum orders per second allowed by the API
MIN_SPEED_BUMP = 0.01      # Minimum delay between orders (in seconds)
CASE_START = 5             # Case start time (seconds)
CASE_END = 295             # Case end time (seconds)
POSITION_LIMIT = 25001     # Maximum allowed net position (positive or negative)
CHANGE_RATE = 3 / 60      # Rate at which to change the order price
FURTHEST_ORDERS_TO_MODIFY = 1 # Number of orders to modify every half second

shutdown = False
total_speed_bump = 0.0
order_count = 0

# Global orders is a dictionary, keyed by order_id.
orders = {}
local_portfolio_position = 0

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
# Helper Functions for REST API calls
# --------------------------
def get_tick(session):
    """Gets tick from the API.
    This function retrieves the current tick from the API, which indicates the current time in seconds.

    Args:
        session (requests session class): session object for API calls

    Returns:
        int: the current tick
    """
    resp = session.get('http://localhost:9999/v1/case')
    if resp.status_code == 401:
        raise ApiException('API key error.')
    return resp.json()['tick']

def ticker_close(session, ticker):
    """Gets the last price for a given ticker from the API.

    Args:
        session (requests session class): session object for API calls
        ticker (string): ticker symbol

    Returns:
        float: last price
    """
    payload = {'ticker': ticker, 'limit': 1}
    resp = session.get('http://localhost:9999/v1/securities/history', params=payload)
    if resp.status_code == 401:
        raise ApiException('API key error.')
    data = resp.json()
    if data:
        return data[0]['close']
    else:
        raise ApiException('No price history for ticker ' + ticker)

def submit_order(session, payload):
    """Submit an order to the API.
    This function sends a POST request to the API to submit an order with the given payload.

    Args:
        session (requests session class): session object for API calls
        payload (dict): information about the order to be submitted

    Returns:
        boolean: if it got successfully submitted or not
    """
    response = session.post('http://localhost:9999/v1/orders', params=payload)
    if response.status_code == 200:
        print("Order submitted successfully.")
        data = response.json()
        orders[data.get('order_id')] = data  # Store the order in the dictionary
    return response.status_code == 200

def update_order_data(session):
    """Updates local order data with the latest information from the API.
    This function iterates over the orders dictionary and retrieves the latest status of each order.

    Args:
        session (requests session class): session object for API calls

    Returns:
        boolean: if it got successfully updated or not
    """
    global orders, local_portfolio_position
    # Iterate over a copy of the dictionary items.
    for key, order in list(orders.items()):
        order_id = order.get('order_id')
        response = session.get(f'http://localhost:9999/v1/orders/{order_id}')
        if response.status_code != 200:
            return False
        
        data = response.json()
        
        # Update local portfolio position based on changes in quantity_filled.
        if orders[order_id].get('action') == 'BUY':
            local_portfolio_position += data.get('quantity_filled', 0) - orders[order_id].get('quantity_filled', 0)
        else:
            local_portfolio_position -= data.get('quantity_filled', 0) - orders[order_id].get('quantity_filled', 0)
        
        # Remove fully filled orders or update the order data.
        if data.get('quantity') == data.get('quantity_filled'):
            del orders[order_id]
        else:
            orders[order_id] = data
    return True

def get_best_prices(session, ticker):
    """Gets the best prices from the market for a given ticker.
    This function retrieves the current best bid and ask prices for a given ticker from the order book.

    Args:
        session (requests session class): session object for API calls
        ticker (string): ticker symbol

    Returns:
        float, float: best bid and best ask prices
    """
    payload = {'ticker': ticker}
    resp = session.get('http://localhost:9999/v1/securities/book', params=payload)
    if resp.status_code == 401:
        raise ApiException('API key error.')
    data = resp.json()
    best_bid = data["bids"][0]["price"] if "bids" in data and data["bids"] else None
    best_ask = data["asks"][0]["price"] if "asks" in data and data["asks"] else None

    if best_bid is not None and best_ask is not None and best_ask - best_bid <= .01:
        best_bid -= 1
        best_ask += 1

    return best_bid, best_ask

def buy_sell(session, ticker, last_price, spread, volume):
    """buy and sell a given ticker at the given price with the given spread and volume.
    This function submits two orders: a buy order at the last price minus the spread and a sell order at the last price plus the spread.

    Args:
        session (requests session class): session object for API calls
        ticker (string): ticker symbol
        last_price (float): last price of the ticker
        spread (float): spread to be applied to the last price
        volume (int): volume of shares to be bought/sold

    Returns:
        time: time taken for order submission
    """
    buy_price = last_price - spread
    sell_price = last_price + spread
    buy_payload = {'ticker': ticker, 'type': 'LIMIT', 'quantity': volume, 'action': 'BUY', 'price': buy_price}
    sell_payload = {'ticker': ticker, 'type': 'LIMIT', 'quantity': volume, 'action': 'SELL', 'price': sell_price}
    start_time = time.time()
    submit_order(session, buy_payload)
    submit_order(session, sell_payload)
    end_time = time.time()
    return end_time - start_time

def get_orders(session, status):
    """Converts order dict to list because thats how API was returning it before we transitioned to local

    Args:
        session (requests session class): session object for API calls
        status (string): type of orders we want

    Returns:
        list: list of odres
    """
    if status:
        return [order for order in orders.values() if order.get('status') == status]
    else:
        return list(orders.values())

def modify_order(session, order):
    """Moves said order closer to the best price.
    This function modifies the given order by canceling it and submitting a new one with a price closer to the best bid/ask.

    Args:
        session (requests session class): session object for API calls
        order (dict): order to be modified

    Returns:
        boolean: if the order was changed or not
    """
    order_id = order.get('order_id')
    action = order.get('action')
    ticker = order.get('ticker')
    volume = order.get('quantity') - order.get('quantity_filled')
    current_price = order.get('price')

    best_bid, best_ask = get_best_prices(session, ticker)

    if action == 'BUY':
        if best_bid is not None and best_bid > current_price:
            new_price = current_price + (best_bid - current_price) * CHANGE_RATE
        else:
            new_price = current_price
    elif action == 'SELL':
        if best_ask is not None and best_ask < current_price:
            new_price = current_price - (current_price - best_ask) * CHANGE_RATE
        else:
            new_price = current_price
    else:
        return False

    new_price = round(new_price, 2)

    if new_price == current_price:
        return False

    # Cancel the existing order.
    url = f'http://localhost:9999/v1/orders/{order_id}'
    response = session.delete(url)
    if response.status_code == 200:
        print(f"Modified order ID {order_id}: {action} {volume} shares moved from {current_price:.2f} to {new_price:.2f}.")
        payload = {
            'ticker': ticker,
            'type': 'LIMIT',
            'quantity': volume,
            'action': action,
            'price': new_price
        }
        submit_order(session, payload)
        return True
    else:
        return False

def modify_farthest_order(session, side, ticker='ALGO'):
    """Modifies the open order on the given side (BUY or SELL) that is farthest from the current bid/ask.

    Args:
        session (_type_): _description_
        side (string): BUY or SELL side
        ticker (str, optional): ticker symbol. Defaults to 'ALGO'.

    Returns:
        boolean: if it got successfully modified or not
    """
    open_orders = get_orders(session, 'OPEN')
    orders_side = [order for order in open_orders if order.get('action') == side and order.get('ticker') == ticker]
    if not orders_side:
        return False
    best_bid, best_ask = get_best_prices(session, ticker)
    if side == 'BUY':
        distance = lambda o: best_bid - o.get('price') if best_bid is not None and o.get('price') < best_bid else 0
    elif side == 'SELL':
        distance = lambda o: o.get('price') - best_ask if best_ask is not None and o.get('price') > best_ask else 0
    else:
        return False
    farthest_order = max(orders_side, key=distance)
    return modify_order(session, farthest_order)

def modify_farthest_n_orders(session, n, ticker='ALGO'):
    """Modifies the furthest n orders

    Args:
        session (requests session class): session object for API calls
        n (int): number of orders to modify
        ticker (str, optional): ticker symbol. Defaults to 'ALGO'.

    Returns:
        float: return not used
    """
    open_orders = get_orders(session, 'OPEN')
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

def calculate_speed_bump(transaction_time, order_rate=ORDER_RATE):
    """Calculates the speed bump based on transaction time and order rate."""
    required_time = 1.0 / order_rate
    return max(required_time - transaction_time, MIN_SPEED_BUMP)

# def get_portfolio_position(session):
#     transacted_orders = get_orders(session, 'TRANSACTED')
#     position = 0
#     for order in transacted_orders:
#         qty = order.get('quantity', 0)
#         if order.get('action') == 'BUY':
#             position += qty
#         elif order.get('action') == 'SELL':
#             position -= qty
#     return position

def get_pending_volumes(session):
    """Gets the pending buy and sell volumes

    Args:
        session (requests session class): session object for API calls

    Returns:
        int, int: number of shares that are pending for buy and sell
    """
    open_orders = get_orders(session, 'OPEN')
    pending_buy = sum(order.get('quantity', 0) - order.get('quantity_filled', 0)
                      for order in open_orders if order.get('action') == 'BUY')
    pending_sell = sum(order.get('quantity', 0) - order.get('quantity_filled', 0)
                       for order in open_orders if order.get('action') == 'SELL')
    return pending_buy, pending_sell

# --------------------------
# Main Trading Algorithm Logic
# --------------------------
def main():
    global total_speed_bump, order_count, shutdown, ORDER_VOLUME
    
    # Initialize the session and set the API key
    with requests.Session() as session:
        session.headers.update(API_KEY)
        tick = get_tick(session)
        last_modify_time = time.time()
        
        # Main trading loop
        while tick > CASE_START and tick < CASE_END and not shutdown:
            
            # Update order data and portfolio position
            update_order_data(session)
            
            current_real_time = time.time()
            
            # If its been 0.5 seconds since the last modify, modify the farthest 1 order
            if current_real_time - last_modify_time >= 0.5:
                modify_farthest_n_orders(session, FURTHEST_ORDERS_TO_MODIFY)
                last_modify_time = current_real_time
            
            # If portfolio position is less than 20000, order size should be 5000, otherwise 100
            if abs(local_portfolio_position) < 20000:
                ORDER_VOLUME = 5000
            else:
                ORDER_VOLUME = 100

            # Get pending volume for buy and sell
            pending_buy, pending_sell = get_pending_volumes(session)
            
            # Figure out if buying/selling more is going to put us over the limit
            potential_long = local_portfolio_position + pending_buy + ORDER_VOLUME
            potential_short = local_portfolio_position - pending_sell - ORDER_VOLUME
            
            # Check if the potential positions exceed the limits, and if so skip the order
            if potential_long > POSITION_LIMIT:
                print(f"Potential long position exceeds limit, skipping order.\t{potential_long}")
                continue
            if potential_short < -POSITION_LIMIT:
                print(f"Potential short position exceeds limit, skipping order.\t{potential_short}")
                continue
            
            # Submit buy sell pair orders if within limits
            if (potential_long <= POSITION_LIMIT) and (potential_short >= -POSITION_LIMIT):
                last_price = ticker_close(session, 'ALGO')
                txn_time = buy_sell(session, 'ALGO', last_price, SPREAD, ORDER_VOLUME)
                current_speed_bump = calculate_speed_bump(txn_time)
                order_count += 1
                total_speed_bump += current_speed_bump
                avg_speed_bump = total_speed_bump / order_count
                sleep(current_speed_bump)
            else:
                sleep(1)
            
            tick = get_tick(session)
        
if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    main()
