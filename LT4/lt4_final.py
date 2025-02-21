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

# Variables to change
margin = .2 # Minimum margin 
market_info = {"M": {"safety_factor": 1.0}, "A": {"safety_factor": 1.0}} 
securities = ["CRZY", "TAME"]

# this is the main method containing the actual order routing logic
def main():
    # creates a session to manage connections and requests to the RIT Client
    with requests.Session() as s:
        while True:
            # Create Progress Bar
            # max_progress = 300        
            # pbar = tqdm(total=max_progress, desc="Processing")

            # add the API key to the session to authenticate during requests
            s.headers.update(API_KEY)
            # get the current time of the case
            tick = get_tick(s)

            books = api_helpers.get_books(s, False)
            books_with_fees = api_helpers.get_books(s, True)
            portfolio = api_helpers.get_portfolio(s)
            tenders = api_helpers.get_tenders(s)

            a = (api_helpers.get_from_api(s, "case").json())
            for tender in tenders:
                helpers.split_market_from_ticker(tender)
                if helpers.evaluate_tender(books, books_with_fees, portfolio, tender, tick):
                    api_helpers.accept_tender(s, tender["tender_id"])


            sleep(1)


# this calls the main() method when you type 'python lt3.py' into the command prompt
if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    main()
