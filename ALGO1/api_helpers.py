import os
import functools
import operator
import itertools
from time import sleep
import signal
import requests
from tqdm.auto import tqdm
import constants


class ApiException(Exception):
    pass

# this signal handler allows for a graceful shutdown when CTRL+C is pressed
def signal_handler(signum, frame):
    global shutdown
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    shutdown = True

# set your API key to authenticate to the RIT client
shutdown = False

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
    while(response.status_code != 200):
    
        if response.status_code == 401:
            raise ApiException(
                'The API key provided in this Python code must match that in the RIT client '
                '(please refer to the API hyperlink in the client toolbar and/or the RIT – User Guide – REST API Documentation.pdf)'
            )
        response = session.get(f'http://localhost:9999/v1/{url}')

    return response


def post_from_api(session, url, payload):
    """
    Posts data from the RIT Client REST API for a specified security.

    Args:
        session (requests.Session): An active session object configured to communicate with the RIT API.
        url (str): The URL segment specifying the security to retrieve (appended to the base endpoint).
        payload(dict): Payload we are submitting

    Raises:
        ApiException: If the API returns a 401 Unauthorized status code, indicating that the API key is incorrect.

    Returns:
        requests.Response: The HTTP response object returned by the API call.
    """
        
    response = session.post(f'http://localhost:9999/v1/{url}', params=payload)
    while(response.status_code != 200):
    
        if response.status_code == 401:
            raise ApiException(
                'The API key provided in this Python code must match that in the RIT client '
                '(please refer to the API hyperlink in the client toolbar and/or the RIT – User Guide – REST API Documentation.pdf)'
            )
        response = session.get(f'http://localhost:9999/v1/{url}')

    return response


def get_books(session, with_fees):
    """This function gets a list of all the books

    Args:
        session (requests.Session): An active session object configured to communicate with the RIT API

    Returns:
        dict of dict of lists: books organized by security and bid/ask
    """
    books = {}
    
    for security in constants.SECURITIES.keys():
        books[security] = {}
        for order_type in ["bids", "asks"]:
            books[security][order_type] = get_book(session, security, order_type, with_fees)
    
    return books


def get_book(session, underlying_security, bid_or_ask, with_fees):
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
    for market in constants.MARKETS.keys():
        if len(constants.MARKETS.keys()) > 1:
            markets_books.append(get_from_api(session, f"securities/book?ticker={underlying_security}_{market}").json())
        else:
            markets_books.append(get_from_api(session, f"securities/book?ticker={underlying_security}").json())

    book = []

    for market in markets_books:
        for order in market[bid_or_ask]:
            split_market_from_ticker(order)
            order["quantity"] = (order["quantity"] - order["quantity_filled"])
            if with_fees:
                if bid_or_ask == "bids":
                    order["price"] -= constants.MARKETS[order["market"]]["MARKET_COST"]
                else:
                    order["price"] += constants.MARKETS[order["market"]]["MARKET_COST"]
            book.append(order)

    # Sort the books by 
    book.sort(key=lambda x: x["price"], reverse=(bid_or_ask == "bids"))
    
    return book



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
