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
        
        # add the API key to the session to authenticate during requests
        s.headers.update(constants.API_KEY)
        
        helpers.session = s
        
        # r1 = s.post("http://localhost:9999/v1/orders", params={"ticker": "CRZY_M", "type": "MARKET", "quantity": 1000, "action": "BUY"})
        
        
        while True:

            # get the current time of the case
            tick = api_helpers.get_tick(s)
            
            # Gets book, portfolio information
            books_with_fees = api_helpers.get_books(session=s, with_fees=True)
            
            # Gets the information about possible arbitrage opportunities (from helpers)
            amounts = helpers.arbitrage_opportunity(books_with_fees)

            # Tries to arbitrage
            helpers.try_arbitrage(amounts=amounts, session=s)
            
                

# this calls the main() method when you type 'python lt3.py' into the command prompt
if __name__ == '__main__':
    signal.signal(signal.SIGINT, api_helpers.signal_handler)
    main()
