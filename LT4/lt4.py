import os
import functools
import operator
import itertools
from time import sleep
import signal
from tqdm.auto import tqdm
import requests
import api_helpers
import helpers
import constants


# this is the main method containing the actual order routing logic
def main():
    # creates a session to manage connections and requests to the RIT Client
    with requests.Session() as s:
            
        if constants.PROGRESS_BAR:
            # Create Progress Bar
            max_progress = 300        
            pbar = tqdm(total=max_progress, desc="Processing")
        
        # add the API key to the session to authenticate during requests
        s.headers.update(constants.API_KEY)
        
        while True:

            # get the current time of the case
            tick = api_helpers.get_tick(s)

            books = api_helpers.get_books(s, False)
            books_with_fees = api_helpers.get_books(s, True)
            portfolio = api_helpers.get_portfolio(s)
            tenders = api_helpers.get_tenders(s)
            print("running")
            for tender in tenders:
                print("Here")
                helpers.split_market_from_ticker(tender)
                if helpers.evaluate_tender(books, books_with_fees, portfolio, tender, tick):
                    api_helpers.accept_tender(s, tender["tender_id"])
                else:
                    print("Not taking it yet")

            if constants.PROGRESS_BAR:
                # Update Progress Bar
                pbar.n = tick
                pbar.refresh()


# this calls the main() method when you type 'python lt3.py' into the command prompt
if __name__ == '__main__':
    signal.signal(signal.SIGINT, api_helpers.signal_handler)
    main()
