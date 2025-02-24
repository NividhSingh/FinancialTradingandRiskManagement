import os
import functools
import operator
import itertools
from time import sleep
import signal
from tqdm.auto import tqdm
import requests
from old_code.helpers import *
import api_helpers
import helpers
import constants

# Variables to change
margin = .2 # Minimum margin 
market_info = {"M": {"safety_factor": 1.0}, "A": {"safety_factor": 1.0}} 
securities = ["CRZY", "TAME"]

# this is the main method containing the actual order routing logic
def main():
    # creates a session to manage connections and requests to the RIT Client
    with requests.Session() as s:
            
        if constants.PROGRESS_BAR:
            # Create Progress Bar
            max_progress = 300        
            pbar = tqdm(total=max_progress, desc="Processing")
        

        # add the API key to the session to authenticate during requests
        s.headers.update(API_KEY)
        
        while True:
            # get the current time of the case
            tick = get_tick(s)

            books = api_helpers.get_books(s, False)
            books_with_fees = api_helpers.get_books(s, True)
            portfolio = api_helpers.get_portfolio(s)
            tenders = api_helpers.get_tenders(s)

            for security, security_books in books.items():
                # print(security_books["bids"][0]["price"])
                # print(security_books["asks"][0]["price"])
                if len(security_books["bids"]) > 0 and len(security_books["asks"]) > 0:
                    if security_books["bids"][0]["price"] > security_books["asks"][0]["price"] + .20:
                        print(security_books["bids"][0]["price"] - security_books["asks"][0]["price"])

                    # if security_books["bids"][0]["price"] - constants.MARKETS[security_books["bids"][0]["market"]]["MARKET_COST"] > security_books["asks"][0]["price"] + constants.MARKETS[security_books["bids"][0]["market"]]["MARKET_COST"]:
                        print("Doing stuff")
                        minimum_quantity = min(security_books["bids"][0]["quantity"], security_books["asks"][0]["quantity"]) * .7
                        helpers.combine_market_with_ticker(security_books["bids"][0])
                        helpers.combine_market_with_ticker(security_books["asks"][0])
                        response1 = s.post('http://localhost:9999/v1/orders', params={'ticker': security_books["bids"][0]["ticker"], 'type': 'MARKET', 'quantity': minimum_quantity, 'action': 'SELL'})
                        response2 = s.post('http://localhost:9999/v1/orders', params={'ticker': security_books["asks"][0]["ticker"], 'type': 'MARKET', 'quantity': minimum_quantity, 'action': 'BUY'})
                        
                        print(security_books["bids"][0]["price"])
                        print(security_books["asks"][0]["price"])
                        
                        print(response1.json()["vwap"])
                        print(response2.json()["vwap"])
                        return 1
                        continue
                    
                    

# this calls the main() method when you type 'python lt3.py' into the command prompt
if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    main()
