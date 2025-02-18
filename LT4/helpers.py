import os
import functools
import operator
import itertools
from time import sleep
import signal
import requests


class ApiException(Exception):
    pass

# this signal handler allows for a graceful shutdown when CTRL+C is pressed
def signal_handler(signum, frame):
    global shutdown
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    shutdown = True

# set your API key to authenticate to the RIT client
API_KEY = {'X-API-Key': '90P5EPK6'}
shutdown = False

def get_portfolio(session):
    """Gets the user's current portfolio positions

    Args:
        session (requests.Session): An active session object configured to communicate with the RIT API.

    Returns:
        dict: dict where the key is the base security and the value is the position of that security
    """

    securities_response = session.get('http://localhost:9999/v1/securities')
    securities_response = securities_response.json()
    
    portfolio = {}

    # Change format into dict where keys are the tickers and values are     
    for security in securities_response:
        portfolio[security["base_security"]] = security["position"]
    
    return portfolio
    
    
def get_tick(session):
    """Gets the current tick of the running case

    Args:
        session (requests.Session): An active session object configured to communicate with the RIT API.

    Returns:
        int: the current tick of the running case
    """
    resp = get_from_api(session, 'case')
    case = resp.json()
    return case['tick']

def get_from_api(session, url):
    """
    Retrieves data from the RIT Client REST API for a specified security.

    Args:
        session (requests.Session): An active session object configured to communicate with the RIT API.
        url (str): The URL segment specifying the security to retrieve (appended to the base endpoint).

    Raises:
        ApiException: If the API returns a 401 Unauthorized status code, indicating that the API key is incorrect.

    Returns:
        requests.Response: The HTTP response object returned by the API call.
    """
    response = session.get(f'http://localhost:9999/v1/{url}')
    
    if response.status_code == 401:
        raise ApiException(
            'The API key provided in this Python code must match that in the RIT client '
            '(please refer to the API hyperlink in the client toolbar and/or the RIT – User Guide – REST API Documentation.pdf)'
        )

    return response

def get_books(session, underlying_security, bid_or_ask, markets_info):
    """This function creates a list of all active orders for a security

    Args:
        session (requests.Session): An active session object configured to communicate with the RIT API.
        underlying_security (string): the underlying security (like CRZY)
        bid_or_ask (string): "bids" or "asks" depending on which one we want

    Raises:
        ApiException: _description_

    Returns:
        List: List of dicts where each dict is an order
    """
    markets_books = []
    for market in markets_info.keys():
        markets_books.append(get_from_api(session, f"securities/book?ticker={underlying_security}_{market}").json())

    book = []

    for market in markets_books:
        for order in market[bid_or_ask]:
            order["market"] = order["ticker"][-1]
            order["quantity"] = (order["quantity"] - order["quantity_filled"]) * markets_info[order["market"]]["safety_factor"]
            book.append(order)

    book.sort(key=lambda x: x["price"], reverse=bid_or_ask == "bids")
    
    return book

def get_tenders(session):
    """Gets all the current tender offers 

    Args:
        session (requests.Session): An active session object configured to communicate with the RIT API.

    Returns:
        list of dicts: Each dict is a tender offer
    """
    tenders = get_from_api(session, "tenders")
    tenders = tenders.json()
    return tenders

def decrease_quantity(quantity, change):
    """Returns the value you get if you decrease quantity by change (even if quantity is negative)

    Args:
        quantity (int): quantity (of security)
        change (int): how much you're getting rid of

    Returns:
        int: new quantity
    """
    return quantity + change * (-1 if quantity > 0 else 1)

def remove_portfolio_quantity_from_book(session, books, portfolio, ticker, markets):
    """Removes the portfolio quantity from the book, with the idea that we get rid of 
    portfolio position before adding position

    Args:
        session (requests.Session): An active session object configured to communicate with the RIT API.
        books (dict of dict of list of dicts): All the orders organized in {ticker: {"asks": [{order info}, {order info}], "bids": []}}
        portfolio (dict): dict of positions for each underlying stock
        ticker (string): ticker we are reducing value of

    Returns:
        dict of dict of list of dicts: returning new books (but pass by reference so probably don't have to do this)
    """
    quantity = portfolio[ticker]
    
    while quantity != 0:
        if len(books[ticker]["bids" if quantity < 0 else "asks"]) and (books[ticker]["bids" if quantity < 0 else "asks"][0]["quantity"] <= quantity):
            order = books[ticker]["bids" if quantity < 0 else "asks"].pop(0)
            quantity = decrease_quantity(quantity, order["quantity"])
        else:
            if len(books[ticker]["bids" if quantity < 0 else "asks"]) > 0:
                books[ticker]["bids" if quantity < 0 else "asks"][0]["quantity"] -= quantity
            quantity = 0
    
    return books

def accept_tender(session, tender_id):
    """Accepts the tender with the tender id

    Args:
        session (requests.Session): An active session object configured to communicate with the RIT API.
        tender_id (int): the tender id for the tender to accept
    """
    print("Accepted Tender")
    # response = session.post(f'http://localhost:9999/v1/tenders/{tender_id}')    

def reject_tender(session, tender_id):
    """Rejects the tender with the tender id

    Args:
        session (requests.Session): An active session object configured to communicate with the RIT API.
        tender_id (int): the tender id for the tender to accept
    """
    print("Rejected Tender")
    response = session.delete(f'http://localhost:9999/v1/tenders/{tender_id}')

def evaluate_tender(books, tender, margin, market_info):
    """Evaluates if a tender is worth taking

    Args:
        books (dict of dict of list of dicts): All the orders organized in {ticker: {"asks": [{order info}, {order info}], "bids": []}}
        tender (dict): Information for the tender
        margin (int): minimum margin for us to take the tender

    Returns:
        boolean: true if user should accept and false if user should decline
    """
    if "price" not in tender.keys():
        tender["price"] = 0
    ticker = tender['ticker'][:4]
    quantity = tender["quantity"] * (-1 if tender["action"] == "SELL" else 1)
    book_for_ticker = books[ticker].copy()
    sum = 0
    
    
    # TODO: The following logic should be modulaized
    while quantity != 0:
        if (books[ticker]["bids" if quantity < 0 else "asks"][0]["quantity"] <= quantity):
            order = book_for_ticker["bids" if quantity < 0 else "asks"].pop(0)
            quantity -= order["quantity"]
            sum += order["quantity"] * order["price"]
        else:
            # book_for_ticker["bids" if quantity < 0 else "asks"][0]["quantity"] -= quantity
            sum += quantity * book_for_ticker["bids" if quantity < 0 else "asks"][0]["price"]
            quantity = 0
    
    vwap = sum / tender["quantity"]
    print(f"vwap: {vwap}", end="\t")
    
    if (tender["action"] == "BUY" and vwap - margin > tender["price"]) or (tender["action"] == "SELL" and vwap + margin < tender["price"]): 
        return True
    
    return False


# def go_through_orders()
