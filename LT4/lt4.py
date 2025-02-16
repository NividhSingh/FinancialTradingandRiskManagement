import os
import functools
import operator
import itertools
from time import sleep
import signal
from tqdm.auto import tqdm
import requests
from helpers import *

# Variables to change
margin = .2 # Minimum margin 
market_info = {"M": {"safety_factor": 1.0}, "A": {"safety_factor": 1.0}}
securities = ["CRZY", "TAME"]

# this is the main method containing the actual order routing logic
def main():
    # creates a session to manage connections and requests to the RIT Client
    with requests.Session() as s:

        # Create Progress Bar
        # max_progress = 300        
        # pbar = tqdm(total=max_progress, desc="Processing")

        # add the API key to the session to authenticate during requests
        s.headers.update(API_KEY)
        # get the current time of the case
        tick = get_tick(s)

        # while the time is <= 300
        while tick <= 300:
            # get and print the two books to the prompt
            books = {}
            portfolio = get_portfolio(s) #, markets)
            for ticker in securities:
                books[ticker] = {}
                for order_type in ["bids", "asks"]:
                    books[ticker][order_type] = get_books(s, ticker, order_type, market_info)
            tenders = get_tenders(s)
            
            # Go through orders
            
            for tender in tenders:
                # 1. Adjust portfolio or books
                convert_to_bid_ask = {"BUY": "bids", "SELL": "asks"}
                ticker = tender["ticker"][:4]
                book = books[ticker][convert_to_bid_ask[tender["action"]]]
                if ticker in portfolio.keys() and portfolio[ticker] != 0:
                    # Tender goes in the same direction as portfolio
                    if (portfolio[ticker] > 0) == (tender["action"] == "BUY"):
                        remove_portfolio_quantity_from_book(s, books, portfolio, ticker, market_info)
                    else:
                        if (abs(portfolio[ticker]) > abs(tender["quantity"])):
                            # TODO: Accept Tender
                            print("Accepting Tender")
                            accept_tender(s, tender["tender_id"])
                            continue
                        else:
                            tender["quantity"] -= portfolio
                
                if evaluate_tender(books, tender, margin, market_info):
                    accept_tender(s, tender["tender_id"])
                
                else:
                    print("Did not choose tender")
                    # print(tender)
                    # print(books[ticker])
                    # reject_tender(s, tender["tender_id"])
                    
                # 2. Calculate margin
                # 3. If accept, create limit order
            
            tick = get_tick(s)
            
            # Update Progress Bar
            # pbar.n = tick
            # pbar.refresh()

# this calls the main() method when you type 'python lt3.py' into the command prompt
if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    main()
