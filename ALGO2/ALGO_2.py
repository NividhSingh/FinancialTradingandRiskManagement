import signal
import requests
import time
from time import sleep

# --------------------------
# Global settings and API key
# --------------------------
API_KEY = {'X-API-Key': 'ABIXYN28'}
SPREAD = 0.01              # Price offset for bid/ask
ORDER_VOLUME = 100         # Volume per order (each side)
ORDER_RATE = 10            # Maximum orders per second allowed by the API
MIN_SPEED_BUMP = 0.01      # Minimum delay between orders (in seconds)
CASE_START = 1             # Case start time (seconds)
CASE_END = 300             # Case end time (seconds)
POSITION_LIMIT = 25001     # Maximum allowed net position (positive or negative)

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
    resp = session.get('http://localhost:9999/v1/case')
    if resp.status_code == 401:
        raise ApiException('API key error.')
    return resp.json()['tick']

def ticker_close(session, ticker):
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
    response = session.post('http://localhost:9999/v1/orders', params=payload)
    if response.status_code == 200:
        print("Order submitted successfully.")
        data = response.json()
        orders[data.get('order_id')] = data  # Store the order in the dictionary
    return response.status_code == 200

def update_order_data(session):
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
            local_portfolio_position += orders[order_id].get('quantity_filled', 0) - data.get('quantity_filled', 0)
        else:
            local_portfolio_position -= orders[order_id].get('quantity_filled', 0) - data.get('quantity_filled', 0)
        
        # Remove fully filled orders or update the order data.
        if data.get('quantity') == data.get('quantity_filled'):
            del orders[order_id]
        else:
            orders[order_id] = data
    return True

def get_best_prices(session, ticker):
    """
    Retrieve the current best bid and ask prices for a given ticker from the order book.
    """
    payload = {'ticker': ticker}
    resp = session.get('http://localhost:9999/v1/securities/book', params=payload)
    if resp.status_code == 401:
        raise ApiException('API key error.')
    data = resp.json()
    best_bid = data["bids"][0]["price"] if "bids" in data and data["bids"] else None
    best_ask = data["asks"][0]["price"] if "asks" in data and data["asks"] else None

    # if best_bid is not None and best_ask is not None and best_ask - best_bid <= .01:
    #     best_bid -= 1
    #     best_ask += 1

    return best_bid, best_ask

def buy_sell(session, ticker, last_price, spread, volume):
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
    # Return orders filtered by status if needed.
    # If no filtering is required, return all orders as a list.
    if status:
        return [order for order in orders.values() if order.get('status') == status]
    else:
        return list(orders.values())

def modify_order(session, order):
    """
    Modify an order by canceling it and re‑submitting with an updated price.
    For a BUY order, if the current best bid is higher than the order's price, 
    set new_price = current_price + (best_bid – current_price)/2.
    For a SELL order, if the current best ask is lower than the order's price, 
    set new_price = current_price - (current_price – best_ask)/2.
    """
    order_id = order.get('order_id')
    action = order.get('action')
    ticker = order.get('ticker')
    volume = order.get('quantity') - order.get('quantity_filled')
    current_price = order.get('price')

    best_bid, best_ask = get_best_prices(session, ticker)

    if action == 'BUY':
        if best_bid is not None and best_bid > current_price:
            new_price = current_price + (best_bid - current_price) #* 5 / 6
        else:
            new_price = current_price
    elif action == 'SELL':
        if best_ask is not None and best_ask < current_price:
            new_price = current_price - (current_price - best_ask) #* 5 / 6
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
    """
    Modify the open order on the given side (BUY or SELL) that is farthest from the current bid/ask.
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
    """
    Modify the n open orders (across both sides) that are farthest from the current bid/ask spread.
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
    
    if len(open_orders) < n:
        n = len(open_orders)
    
    orders_to_modify = open_orders[:n]
    for order in orders_to_modify:
        modify_order(session, order)

def calculate_speed_bump(transaction_time, order_rate=ORDER_RATE):
    required_time = 1.0 / order_rate
    return max(required_time - transaction_time, MIN_SPEED_BUMP)

def get_portfolio_position(session):
    """
    Compute the net portfolio position for ticker 'ALGO' from executed orders.
    BUY orders add to the position; SELL orders subtract.
    """
    transacted_orders = get_orders(session, 'TRANSACTED')
    position = 0
    for order in transacted_orders:
        qty = order.get('quantity', 0)
        if order.get('action') == 'BUY':
            position += qty
        elif order.get('action') == 'SELL':
            position -= qty
    return position

def get_pending_volumes(session):
    """
    Compute total pending volumes separately for BUY and SELL orders.
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
    with requests.Session() as session:
        session.headers.update(API_KEY)
        tick = get_tick(session)
        last_modify_time = time.time()
        
        while tick > CASE_START and tick < CASE_END and not shutdown:
            
            update_order_data(session)
            
            current_real_time = time.time()
            if current_real_time - last_modify_time >= 0.5:
                modify_farthest_n_orders(session, 2)
                last_modify_time = current_real_time

            portfolio_position = get_portfolio_position(session)
            
            if abs(portfolio_position) < 15000:
                ORDER_VOLUME = 5000
            elif abs(portfolio_position) < 20000:
                ORDER_VOLUME = 500
            else:
                ORDER_VOLUME = 100

            pending_buy, pending_sell = get_pending_volumes(session)
            
            potential_long = local_portfolio_position + pending_buy + ORDER_VOLUME
            potential_short = local_portfolio_position - pending_sell - ORDER_VOLUME
            
            if potential_long > POSITION_LIMIT:
                print(f"Potential long position exceeds limit, skipping order.\t{potential_long}")
                continue
            if potential_short < -POSITION_LIMIT:
                print(f"Potential short position exceeds limit, skipping order.\t{potential_short}")
                continue
            
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
