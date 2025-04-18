import os
import functools
import operator
import itertools
from time import sleep
import signal
import requests
import constants_6 as constants
from scipy.stats import norm
import math
from tqdm.auto import tqdm

NORMAL_TENDER = 1
WINNER_TAKES_ALL = 2
COMPETATIVE_TENDERS = 3

underlying_price = {}

def type_of_tender(tender):
    """Figures out what type of tender it is

    Args:
        tender (dict): dict with tender information

    Returns:
        int: represents what type of tender
    """
    
    # If fixed bid, its a normal tender
    if tender["is_fixed_bid"]:
        return NORMAL_TENDER
    
    # TODO: Test the following
    # If winner in tender caption, winner take all tender
    elif "winner" in tender["caption"]:
        return WINNER_TAKES_ALL
    
    # If none of the above, its a competative tender
    else:
        return COMPETATIVE_TENDERS


def split_market_from_ticker(d):
    """Takes a dict and splits the security so there's a key for dictionary and the ticker is "CRZY" instead of "CRZY_M"

    Args:
        d (dict): dict of something (could be order, or tender or portfolio, etc)
    """
    
    # If there is more than one market, split it
    if len(constants.MARKETS.keys()) > 1:
        d["market"] = d["ticker"][-1]
        d["ticker"] = d["ticker"][:-2]
        
    # If there is just one market, everything is in the main market
    else:
        d["market"] = "M"

def combine_market_with_ticker(d):
    """Adds market back to ticker for the final security ticker to send back

    Args:
        d (dict): dict that we are trying to combine for
    """
    # If there is more than one market, combine with market
    if len(constants.MARKETS.keys()) > 1:
        d["ticker"] = d["ticker"] + "_" + d["market"]

def remove_quantity_from_book(quantity, book):
    """Removes some quantity of shares from the book

    Args:
        quantity (int): the quantity being removed
        book (list of dicts): list of dicts representing orders
    """
    
    # While the quantity isn't 0, keep going 
    while quantity != 0:
        
        # If no more orders in book, return -1 to signal no more orders
        if len(book) == 0:
            return -1
        
        # The next order is bigger than the quantity left
        if book[0]["quantity"] > quantity:
            book[0]["quantity"] -= quantity
            quantity = 0
            
        # The quantity left is bigger than the next order quantity
        else:
            order = book.pop(0)
            quantity -= order["quantity"]
            
def get_underlying_price(books, tick):
    """
    Gets the underlying price by finding the bid-ask spread based on anonymous users.
    
    Each security_book is a dict with two keys, "bids" and "asks". If EVERYONE_ANON is True,
    then we select the first bid and ask where the quantity is not 1000 or 10000.
    Otherwise, we select the first bid and ask where the trader_id is "anon".
    The underlying price is the average of the selected bid and ask prices.
    
    Args:
        books (dict): A dictionary where each key is a security and each value is a dict
                      with keys "bids" and "asks", and each of these is a list of orders.
        tick (int): The current tick.
    
    Returns:
        dict: A dictionary mapping each security to its computed underlying price.
    """
    underlying_prices = {}
    
    for security, security_book in books.items():
        # If there might not be any orders yet, return the start price.
        if tick < 2:
            underlying_prices[security] = constants.SECURITIES[security]["START_PRICE"]
            continue

        # Select bid order.
        bid_order = None
        for order in security_book.get("bids", []):
            # Skip non-dictionary entries.
            if not isinstance(order, dict):
                continue
            if constants.EVERYONE_ANON:
                # When everyone is anonymous, we want orders where quantity isn't 1000 or 10000.
                if int(order.get("quantity", 0)) not in [1000, 10000]:
                    bid_order = order
                    break
            else:
                # Otherwise, we want orders where the trader_id is "anon".
                if order.get("trader_id") == "anon":
                    bid_order = order
                    break

        # Select ask order.
        ask_order = None
        for order in security_book.get("asks", []):
            if not isinstance(order, dict):
                continue
            if constants.EVERYONE_ANON:
                if int(order.get("quantity", 0)) not in [1000, 10000]:
                    ask_order = order
                    break
            else:
                if order.get("trader_id") == "anon":
                    ask_order = order
                    break

        # If we didn't find a valid bid or ask, we can default to the first valid order if available.
        if bid_order is None and security_book.get("bids"):
            bid_order = next((o for o in security_book["bids"] if isinstance(o, dict)), None)
        if ask_order is None and security_book.get("asks"):
            ask_order = next((o for o in security_book["asks"] if isinstance(o, dict)), None)

        # If both orders were found, average their prices.
        if bid_order is not None and ask_order is not None:
            bid_price = float(bid_order.get("price", 0))
            ask_price = float(ask_order.get("price", 0))
            underlying_prices[security] = (bid_price + ask_price) / 2
        else:
            # In case one of the sides is missing, fallback to start price.
            underlying_prices[security] = constants.SECURITIES[security]["START_PRICE"]
    
    return underlying_prices



def evaluate_tender(books, books_with_fees, portfolio, tender, tick):
    """Evaluate if a tender is profitable

    Args:
        books (dict of dict of list of dicts): represents the book seperated by securities and bids/asks
        books_with_fees (dict of dict of list of dicts): same as above but includes fees
        portfolio (dict): dict where key is security and value is portfolio quantity
        tender (dict): dict representing information about tender
        tick (int): tick we are on

    Returns:
        bool: boolean for if it is profitible or not profitible
    """
    
    underlying_price = get_underlying_price(books, tick)
    
    # Do step 3 first (because its easier in terms of programming this way). Step 3 based on write up
    if try_not_selling(tick, tender, underlying_price):
        tqdm.write("No Selling")
        return True
    
    total_portfolio_quantity = total = sum(abs(value) for value in portfolio.values())
    
    # Step 1: Remove Portfolio Quantity
    if portfolio[tender["ticker"]] != 0:
        
        # Same direction (either negative quantity and we're selling or positive quantity and we're buying)
        if (portfolio[tender["ticker"]] < 0) == (tender["action"] == "SELL"):
            
            # Exceeds Limit
            if (abs(portfolio[tender["ticker"]]) + abs(tender["quantity"]) > constants.TRADING_LIMITS["SECURITY_LIMIT"] or total_portfolio_quantity + abs(tender["quantity"]) > constants.TRADING_LIMITS["GROSS_LIMIT"]):
                print("Here")
                return False

            # Remove portfolio quantity from book
            else:
                remove_quantity_from_book(abs(portfolio[tender["ticker"]]), books_with_fees[tender["ticker"]]["asks" if portfolio[tender["ticker"]] < 0 else "bids"])
                portfolio[tender["ticker"]] = 0


        # Opposite direction (like we're short and we are buying stock)
        else:
            # Portfolio Quantity is greater
            if portfolio[tender["ticker"]] > tender["quantity"]:
                remove_quantity_from_book(abs(portfolio[tender["ticker"]] - tender["quantity"]), books_with_fees[tender["ticker"]]["asks" if portfolio[tender["ticker"]] < 0 else "bids"])
                tender["quantity"] -= tender["quantity"]
            
            # Tender quantity is greater
            else:
                tender["quantity"] -= tender["quantity"]

    # Step 2: Account for market Change
    vwap = calculate_vwap(tender["quantity"], books_with_fees[tender["ticker"]]["asks" if tender["action"] == "SELL" else "bids"])
    
    # We want a lower bound if we're buying (we want price to be higher than) or a higher bound if selling
    probability = .05 if tender["action"] == "BUY" else .95
    
    orders = math.ceil(tender["quantity"]/constants.TRADING_LIMITS["ORDER_LIMIT"])
    
    order_time = orders * constants.RATE_LIMIT
    
    ticks_to_offload = order_time / constants.SPEED
    
    # Factor in the volitility
    val = underlying_price[tender["ticker"]] * (1 + constants.SECURITIES[tender["ticker"]]["VOLITILITY"] * norm.ppf(probability, 0, constants.SECURITIES[tender["ticker"]]["VOLITILITY"] * math.sqrt(ticks_to_offload / constants.TICKS)))
    
    # Average between worst case price and vwap or if vwap isn't deep enough just the worst case underlying price
    average = (val + vwap) / 2 if vwap != -1 else val

    if constants.DEBUG:
        tqdm.write("underlying price: " + str(underlying_price[tender["ticker"]]))
        tqdm.write(f"val: {val}")


        tqdm.write("tender price: " + str(tender["price"]))
        tqdm.write(f"tender action:" + str(tender["action"]))
        
        tqdm.write(tender["price"] > average)
        tqdm.write(tender["action"] == "SELL")
        
    
    print(f"{type_of_tender(tender)} average: ", end="\t")
    print(average)
    
    if type_of_tender(tender) == NORMAL_TENDER:
        return (tender["price"] > average) == (tender["action"] == "SELL")
    return False
    
def calculate_vwap(quantity, book):
    """Calcualtes volume weighted average for the first quantity in book

    Args:
        quantity (int): quantity to find vwap for
        book (list of dicts): list of orders

    Returns:
        float: vwap
    """
    
    book_copy = book.copy()
    
    # If quantity is 0 (doesn't make sense for this context), we return 0
    if quantity == 0:
        return -1
    
    # Initialize variables
    sum = 0
    original_quantity = quantity
    
    # While quantity isn't 0
    while quantity != 0:
        
        # If no more orders in book, we return -1 (otherwise vwap might be a lot less than it should be)
        if len(book_copy) <= 0:
            return -1
        
        # If first order is bigger, calculated based on quantity
        if book_copy[0]["quantity"] > quantity:
            sum += book_copy[0]["price"] * quantity
            book_copy[0]["quantity"] -= quantity
            quantity = 0
            
        # If quantity is bigger, remove the first one (which only doesn't cause errors because we're working with a copy of the book)
        else:
            order = book_copy.pop(0)
            sum += order["price"] * order["quantity"]
            quantity -= order["quantity"]
    
    vwap = float(sum) / float(original_quantity)
    
    if constants.DEBUG:
        tqdm.write(f"VWAP: {vwap}")
    
    return vwap
    
def try_not_selling(tick, tender, underlying_price):
    return False
    """Checks if its profitible to not sell and just pay penalties with a 95% certainty

    Args:
        tick (int): What tick we're at
        tender (dict): dict representing current tender
        underlying_price (float): underlying price based on ANOM traders

    Returns:
        bool: whether its profitible or not profitible
    """
    # Step 3: Check not selling offers
    ticks_left = constants.TICKS - tick
    
    # We want a lower bound if we're buying (we want price to be higher than) or a higher bound if selling
    probability = .05 if tender["action"] == "BUY" else .95
    
    # Factor in the volitility
    # TODO: the line below and above is repeated so modulize 
    val = underlying_price[tender["ticker"]] * (1 + norm.ppf(probability, 0, constants.SECURITIES[tender["ticker"]]["VOLITILITY"] * constants.SECURITIES[tender["ticker"]]["VOLITILITY"] * math.sqrt(ticks_left / constants.TICKS)))
    
    tender_price = tender["price"]
    
    # Factor in the fees
    # TODO: Change to val instead of tender_price
    if tender["action"] == "BUY":
        tender_price += constants.ENV_INFO["D"]
    else:
        tender_price -= constants.ENV_INFO["D"]
    
    # If the tender price is below the final price (withi 95% certainty) and we're selling, this is good. If tender is above final price and we're buying this is also good
    return tender_price > val == tender["action"] == "SELL"
