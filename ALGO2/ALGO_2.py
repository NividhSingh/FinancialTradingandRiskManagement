import signal
import requests
import time
from time import sleep

# --------------------------
# Global settings and API key
# --------------------------
API_KEY = {'X-API-Key': 'ABIXYN28'}
SPREAD = 0.02              # Price offset for bid/ask
ORDER_VOLUME = 500         # Volume per order (each side)
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

def cancel_oldest_order(session, side):
    """
    Cancel the oldest open order for the given side (BUY or SELL).
    """
    # return False
    orders = get_orders(session, 'OPEN')
    side_orders = [order for order in orders if order.get('action') == side]
    if not side_orders:
        return False
    # Sort by timestamp if available; otherwise, by order_id.
    side_orders.sort(key=lambda o: o.get('timestamp', o.get('order_id', 0)))
    oldest_order = side_orders[0]
    order_id = oldest_order.get('order_id')
    url = f'http://localhost:9999/v1/orders/{order_id}'
    response = session.delete(url)
    if response.status_code == 200:
        print(f"Cancelled oldest {side} order with ID {order_id}.")
        return True
    else:
        print(f"Failed to cancel {side} order with ID {order_id}.")
        return False

def cancel_oldest_n_orders(session, n):
    """
    Cancel the oldest n open orders regardless of side.
    """
    orders = get_orders(session, 'OPEN')
    if not orders:
        return
    # Sort orders by timestamp if available, or fallback to order_id.
    orders.sort(key=lambda o: o.get('timestamp', o.get('order_id', 0)))
    orders_to_cancel = orders[:n]
    for order in orders_to_cancel:
        
        # buy_payload = {'ticker': order.get("ticker"), 'type': 'MARKET', 'quantity': order.get("quantity") - order.get("quantity_filled"), 'action': order.get("action")}
        # response2 = session.post('http://localhost:9999/v1/orders', params=buy_payload)
        
        order_id = order.get('order_id')
        url = f'http://localhost:9999/v1/orders/{order_id}'
        response = session.delete(url)
        if response.status_code == 200:
            print(f"Cancelled order ID {order_id}.")
        else:
            print(f"Failed to cancel order ID {order_id}.")

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
        last_cancel_time = time.time()

        while tick < CASE_START or tick > CASE_END and not shutdown:
            print("Waiting to start")

        
        while tick > CASE_START and tick < CASE_END and not shutdown:
            try:
                # Every 5 seconds, cancel the oldest 10 open orders
                current_real_time = time.time()
                if current_real_time - last_cancel_time >= 1:
                    print("Periodic cancellation: Cancelling the oldest 10 orders.")
                    cancel_oldest_n_orders(session, 10)
                    last_cancel_time = current_real_time

                # Calculate current net portfolio position (executed buys minus sells)
                portfolio_position = get_portfolio_position(session)
                # Get total pending volumes for BUY and SELL orders
                pending_buy, pending_sell = get_pending_volumes(session)
                
                # If we add one more BUY order, the potential long position becomes:
                potential_long = portfolio_position + pending_buy + ORDER_VOLUME
                # If we add one more SELL order, the potential short position becomes:
                potential_short = portfolio_position - pending_sell - ORDER_VOLUME
                
                print(f"Portfolio position: {portfolio_position}, Pending BUY: {pending_buy}, Pending SELL: {pending_sell}")
                print(f"Potential long if BUY added: {potential_long}, Potential short if SELL added: {potential_short}")
                
                # Adjust pending BUY orders if adding another would exceed the +25,000 limit
                while potential_long > POSITION_LIMIT:
                    print("Adding another BUY order would exceed the long limit. Cancelling oldest BUY order...")
                    if not cancel_oldest_order(session, 'BUY'):
                        print("No BUY orders available to cancel.")
                        break
                    pending_buy, _ = get_pending_volumes(session)
                    potential_long = portfolio_position + pending_buy + ORDER_VOLUME

                # Adjust pending SELL orders if adding another would exceed the -25,000 limit
                while potential_short < -POSITION_LIMIT:
                    print("Adding another SELL order would exceed the short limit. Cancelling oldest SELL order...")
                    if not cancel_oldest_order(session, 'SELL'):
                        print("No SELL orders available to cancel.")
                        break
                    _, pending_sell = get_pending_volumes(session)
                    potential_short = portfolio_position - pending_sell - ORDER_VOLUME
                
                # Only place new paired orders if both sides are within limits after adding ORDER_VOLUME
                if (portfolio_position + pending_buy + ORDER_VOLUME <= POSITION_LIMIT) and \
                   (portfolio_position - pending_sell - ORDER_VOLUME >= -POSITION_LIMIT):
                    last_price = ticker_close(session, 'ALGO')
                    print(f"Tick {tick}: Submitting new bid/ask pair at price {last_price:.2f}.")
                    txn_time = buy_sell(session, 'ALGO', last_price, SPREAD, ORDER_VOLUME)
                    current_speed_bump = calculate_speed_bump(txn_time)
                    order_count += 1
                    total_speed_bump += current_speed_bump
                    avg_speed_bump = total_speed_bump / order_count
                    print(f"Transaction time: {txn_time:.4f}s, Speed bump: {current_speed_bump:.4f}s (avg: {avg_speed_bump:.4f}s)")
                    sleep(current_speed_bump)
                else:
                    print("Not safe to add new orders due to portfolio risk limits. Waiting...")
                    sleep(1)
                
                tick = get_tick(session)
            except ApiException as e:
                print("API Exception:", e)
                break
            except Exception as e:
                print("Unexpected Exception:", e)
                break
        
        print("Trading session ended or shutdown signal received. Exiting algorithm.")

# --------------------------
# Entry Point
# --------------------------
if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    main()
