import os
import functools
import operator
import itertools
from time import sleep
import signal
import requests
import constants
from scipy.stats import norm
import math
from tqdm.auto import tqdm
import copy
import api_helpers
import time

past_arbitrage_information = {} # This stores any past arbitrage opportunity that has come up in the following format

"""
{
    "ticker": [
        {
            "margin": main - alternate,
            "time": time
        }
    ]
    
}
"""

def arbitrage_opportunity(book):
    """This function finds all current arbitrage opportunities

    Args:
        book (dict of list of orders): This is a dict of the books, in the following format:
        {
            "ticker": book that the api returns
        }

    Returns:
        dict: dict with information about the arbitrage opportunities
    """
    
    # Make a copy of the book so that the changes we make don't effect other parts of the code
    book_copy = copy.deepcopy(book)
    
    # Amounts stores arbitrage opportunities
    amounts = {}
    
    # Goes through each underlying security (like CRZY not CRZY_M) 
    for security, security_book in book_copy.items():
        # security is something like CRZY
        # security book is a list of orders
        
        # Margin is the profit margin
        margin = -1
        
        # Amount is how much we can arbitrage profitably
        amount = 0
        
        # bid and ask index are the index we're on
        bid_index = 0
        ask_index = 0
        
        # Which market we are getting the ask from and which we're getting the bid from
        ask_market = None
        bid_market = None
        
        
        # While we still have more items in the book and the ask is lower the bid
        # Also, the bids and asks book combines both markets, so if there is an arbigrage opportunity, it will show it
        while (len(security_book["asks"]) > ask_index and len(security_book["bids"]) > bid_index and (security_book["asks"][ask_index]["price"] < security_book["bids"][bid_index]["price"])):

            # If the margin is -1, update it so that the margin value is the best margin
            if margin == -1:
                margin = security_book["bids"][0]["price"] - security_book["asks"][0]["price"]

            # Increase amount by the minimum of the first ask and first bid
            amount += min(security_book["asks"][0]["quantity"], security_book["bids"][0]["quantity"])
            
            # Record which market has the ask we want and which market has the bid. This will always be different markets
            ask_market = security_book["asks"][0]["market"]
            bid_market = security_book["bids"][0]["market"]
            
            # Remove the order from the book (depending on which one is smaller) and remove that quantity for the other
            if (security_book["asks"][0]["quantity"] < security_book["bids"][0]["quantity"]):
                security_book["bids"][0]["quantity"] -= security_book["asks"][0]["quantity"]
                security_book["asks"].pop()
            else:
                security_book["asks"][0]["quantity"] -= security_book["bids"][0]["quantity"]
                security_book["bids"].pop()
        
            # Record this arbitrage opportunity
            amounts[security] = {"amount": amount, "margin": margin, "ask_market": ask_market, "bid_market": bid_market}
        
        # If the amount is more than 0, it means that there is an arbitrage opportunity so record that in our history log
        if amount > 0:
            
            # Make a new list if the security isn't there
            if security not in past_arbitrage_information.keys():
                past_arbitrage_information[security] = []
                
            # Add the time and margin into the history. To be clear, here we have that the margin is main market - alternate market, so margin could be negative
            past_arbitrage_information[security].append({"margin": margin * -1 if ask_market == "A" else 1, "time": time.time() * 1000})
                
    return amounts


def try_arbitrage(amounts, session):
    """This analyzes if it is worth arbitraging or using a contrarian strategy

    Args:
        amounts (information about the arbitrage opportunities): Comes straight from the function above
        session (requests.session): session variable
    """
    
    # Go through each security and the arbirage information for that security
    for security, security_arbitrage_info in amounts.items():
        
        # The next bit of code basically goes through the history for this security and finds the minimum margin thats bigger than the current margin and isn't the last entry. 
        # We are only looking at this security because we're assuming there are people that accidentally have their code made so it only arbitrages for one security
        min_index = -1
        min_value = past_arbitrage_information[security][0]["margin"]
        for i, past_arbitrage_opportunity in enumerate((past_arbitrage_information[security])[:-1]):
            if (abs(past_arbitrage_information[security][min_index]["margin"]) < security_arbitrage_info["margin"] 
                or (abs(past_arbitrage_opportunity["margin"]) < security_arbitrage_info["margin"] and abs(past_arbitrage_opportunity["margin"]) > abs(past_arbitrage_information[security][min_index]["margin"]))):
                min_index = i
                min_value = past_arbitrage_opportunity["margin"]
        
        # Now, we look at the arbitrage opportunity after the one we found. If the next one is withihin 20 milliseconds, and the direction is flipped, this means a lot of people are arbitraging
        # If this is the case, then we assume that it will flip again, so we wait 10 ms and then submit the opposite of what we should be submitting. This, in theory, is profitable
        if min_index != -1 and (past_arbitrage_information[security][min_index]["margin"] < 0 != past_arbitrage_information[security][min_index + 1]["margin"] < 0) and (past_arbitrage_information[security][min_index + 1]["time"] - past_arbitrage_information[security][min_index]["time"] < .2):
            print("Submitting with flipping")
            sleep(1/100)
            
            submit_arbitrage(security=security, security_arbitrage_info=security_arbitrage_info, flipped = True, session=session)
        
        else:
            print("Submitting without flipping")
            submit_arbitrage(security=security, security_arbitrage_info=security_arbitrage_info, flipped = False, session=session)
            

def submit_arbitrage(security, security_arbitrage_info, flipped, session):
    """This function submits the orders

    Args:
        security (string): underlying security
        security_arbitrage_info (information about the arbitrage): a dictionary with information. We're using ask_market, bid_market and amount
        flipped (if we are flipping the markets): Boolean
        session (request.session): session
    """
    
    # Record the ask and bid securities
    ask_security = security + "_" + security_arbitrage_info["ask_market"]
    bid_security = security + "_" + security_arbitrage_info["bid_market"]
    
    # The only difference below is hte fact that one flips buy and sell
    if not flipped:
        api_helpers.post_from_api(session, "orders", {"ticker": ask_security, "type": "MARKET", "quantity": min(constants.TRADING_LIMITS["ORDER_LIMIT"], security_arbitrage_info["amount"]), "action": "BUY"})
        api_helpers.post_from_api(session, "orders", {"ticker": bid_security, "type": "MARKET", "quantity": min(constants.TRADING_LIMITS["ORDER_LIMIT"], security_arbitrage_info["amount"]), "action": "SELL"})
    else:
        api_helpers.post_from_api(session, "orders", {"ticker": ask_security, "type": "MARKET", "quantity": min(constants.TRADING_LIMITS["ORDER_LIMIT"], security_arbitrage_info["amount"]), "action": "SELL"})
        api_helpers.post_from_api(session, "orders", {"ticker": bid_security, "type": "MARKET", "quantity": min(constants.TRADING_LIMITS["ORDER_LIMIT"], security_arbitrage_info["amount"]), "action": "BUY"})
