import signal
import requests
import time
from time import sleep

# --------------------------
# Global settings and API key
# --------------------------
API_KEY = {'X-API-Key': 'ABIXYN28'}
SPREAD = 0.02              # Price offset for bid/ask
ORDER_VOLUME = 1000         # Volume per order (each side)
ORDER_RATE = 20             # Maximum orders per second allowed by the API
MIN_SPEED_BUMP = 0.01      # Minimum delay between orders (in seconds)
CASE_START = 5             # Case start time (seconds)
CASE_END = 295             # Case end time (seconds)
POSITION_LIMIT = 25000     # Maximum allowed net position (positive or negative)

shutdown = False
total_speed_bump = 0.0
order_count = 0

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
    
    
    if best_ask - best_bid <= .01:
        best_bid -= 1
        best_ask += 1
        
    return best_bid, best_ask

def buy_sell(session, ticker, last_price, spread, volume):
    buy_price = last_price - spread
    sell_price = last_price + spread
    buy_payload = {'ticker': ticker, 'type': 'LIMIT', 'quantity': volume, 'action': 'BUY', 'price': buy_price}
    sell_payload = {'ticker': ticker, 'type': 'LIMIT', 'quantity': volume, 'action': 'SELL', 'price': sell_price}
    start_time = time.time()
    session.post('http://localhost:9999/v1/orders', params=buy_payload)
    session.post('http://localhost:9999/v1/orders', params=sell_payload)
    end_time = time.time()
    return end_time - start_time

def get_orders(session, status):
    payload = {'status': status}
    resp = session.get('http://localhost:9999/v1/orders', params=payload)
    if resp.status_code == 401:
        raise ApiException('API key error.')
    return resp.json()

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
    volume = order.get('quantity')
    current_price = order.get('price')
    
    best_bid, best_ask = get_best_prices(session, ticker)
    
    if action == 'BUY':
        if best_bid is not None and best_bid > current_price:
            new_price = current_price + (best_bid - current_price) * 3 / 6
        else:
            new_price = current_price
            
        print(f"Buy\t{current_price}")
    elif action == 'SELL':
        if best_ask is not None and best_ask < current_price:
            new_price = current_price - (current_price - best_ask) * 3 / 6
        else:
            new_price = current_price
        print(f"SELL\t{current_price}")
    else:
        return False

    # Simulate modification by canceling and re‑submitting immediately.
    url = f'http://localhost:9999/v1/orders/{order_id}'
    response = session.delete(url)
    if response.status_code == 200:
        # print(f"Modified order ID {order_id}: {action} {volume} shares moved from {current_price:.2f} to {new_price:.2f}.")
        payload = {
            'ticker': ticker,
            'type': 'LIMIT',
            'quantity': volume,
            'action': action,
            'price': new_price
        }
        session.post('http://localhost:9999/v1/orders', params=payload)
        return True
    else:
        # print(f"Failed to modify order ID {order_id}.")
        return False

def modify_farthest_order(session, side, ticker='ALGO'):
    """
    Modify the open order on the given side (BUY or SELL) that is farthest from the current bid/ask.
    For BUY orders, the distance is (best_bid - order_price) if order_price < best_bid.
    For SELL orders, the distance is (order_price - best_ask) if order_price > best_ask.
    """
    orders = get_orders(session, 'OPEN')
    orders_side = [order for order in orders if order.get('action') == side and order.get('ticker') == ticker]
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
    orders = get_orders(session, 'OPEN')
    orders = [order for order in orders if order.get('ticker') == ticker]
    if not orders:
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
    orders.sort(key=lambda o: distance(o), reverse=True)
    orders_to_modify = orders[:n]
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
    orders = get_orders(session, 'TRANSACTED')
    position = 0
    for order in orders:
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
    orders = get_orders(session, 'OPEN')
    pending_buy = sum(order.get('quantity', 0) for order in orders if order.get('action') == 'BUY')
    pending_sell = sum(order.get('quantity', 0) for order in orders if order.get('action') == 'SELL')
    return pending_buy, pending_sell

# --------------------------
# Main Trading Algorithm Logic
# --------------------------
def main():
    global total_speed_bump, order_count, shutdown
    with requests.Session() as session:
        session.headers.update(API_KEY)
        tick = get_tick(session)
        last_modify_time = time.time()
        
        while tick > CASE_START and tick < CASE_END and not shutdown:
            
            try:
                current_real_time = time.time()
                # Every 5 seconds, modify the farthest 10 orders (i.e. move them closer by half the distance).
                if current_real_time - last_modify_time >= 1:
                    # print("Periodic modification: Modifying the farthest 10 orders toward the spread.")
                    modify_farthest_n_orders(session, 10)
                    last_modify_time = current_real_time

                # Calculate current net portfolio position (executed buys minus sells).
                portfolio_position = get_portfolio_position(session)
                
                if (abs(portfolio_position) < 10000):
                    ORDER_RATE = 10
                elif (abs(portfolio_position) < 15000):
                    ORDER_RATE = 5
                elif (abs(portfolio_position) < 20000):
                    ORDER_RATE = 2
                else:
                    ORDER_RATE = 1
                # Get total pending volumes for BUY and SELL orders.
                pending_buy, pending_sell = get_pending_volumes(session)
                
                # Potential exposure if we add a new BUY order:
                potential_long = portfolio_position + pending_buy + ORDER_VOLUME
                # Potential exposure if we add a new SELL order:
                potential_short = portfolio_position - pending_sell - ORDER_VOLUME
                
                # print(f"Portfolio position: {portfolio_position}, Pending BUY: {pending_buy}, Pending SELL: {pending_sell}")
                # print(f"Potential long if BUY added: {potential_long}, Potential short if SELL added: {potential_short}")
                
                # Adjust pending BUY orders by modifying the one farthest from the spread until safe.
                while potential_long > POSITION_LIMIT:
                    # print("Adding another BUY order would exceed the long limit. Modifying the BUY order farthest from the spread...")
                    if not modify_farthest_order(session, 'BUY'):
                        # print("No BUY orders available to modify.")
                        break
                    pending_buy, _ = get_pending_volumes(session)
                    potential_long = portfolio_position + pending_buy + ORDER_VOLUME

                # Adjust pending SELL orders by modifying the one farthest from the spread until safe.
                while potential_short < -POSITION_LIMIT:
                    # print("Adding another SELL order would exceed the short limit. Modifying the SELL order farthest from the spread...")
                    if not modify_farthest_order(session, 'SELL'):
                        # print("No SELL orders available to modify.")
                        break
                    _, pending_sell = get_pending_volumes(session)
                    potential_short = portfolio_position - pending_sell - ORDER_VOLUME
                
                # Only place new paired orders if both sides are within limits after adding ORDER_VOLUME.
                if (portfolio_position + pending_buy + ORDER_VOLUME <= POSITION_LIMIT) and \
                   (portfolio_position - pending_sell - ORDER_VOLUME >= -POSITION_LIMIT):
                    last_price = ticker_close(session, 'ALGO')
                    # print(f"Tick {tick}: Submitting new bid/ask pair at price {last_price:.2f}.")
                    txn_time = buy_sell(session, 'ALGO', last_price, SPREAD, ORDER_VOLUME)
                    current_speed_bump = calculate_speed_bump(txn_time)
                    order_count += 1
                    total_speed_bump += current_speed_bump
                    avg_speed_bump = total_speed_bump / order_count
                    # print(f"Transaction time: {txn_time:.4f}s, Speed bump: {current_speed_bump:.4f}s (avg: {avg_speed_bump:.4f}s)")
                    sleep(current_speed_bump)
                else:
                    # print("Not safe to add new orders due to portfolio risk limits. Waiting...")
                    sleep(1)
                
                tick = get_tick(session)
            except ApiException as e:
                # print("API Exception:", e)
                break
            except Exception as e:
                # print("Unexpected Exception:", e)
                break
        
        # print("Trading session ended or shutdown signal received. Exiting algorithm.")

# --------------------------
# Entry Point
# --------------------------
if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    main()
