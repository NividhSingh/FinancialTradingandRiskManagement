import tkinter as tk
import requests
import api_helpers
import helpers
import constants_1 as constants

# Create a Tkinter window.
root = tk.Tk()
root.title("Order Routing Dashboard")

# Create UI element for tick.
label_tick = tk.Label(root, text="Tick: Loading...", font=('Arial', 12))
label_tick.pack(pady=5)

# Create a frame for the table.
table_frame = tk.Frame(root)
table_frame.pack(pady=10)

# Global dictionaries to store the label widgets.
header_labels = {}
underlying_labels = {}
current_labels = {}
difference_labels = {}

# This flag indicates whether the table has been built.
table_built = False

# Create a requests session outside the update loop.
session = requests.Session()
session.headers.update(constants.API_KEY)

def format_number(num):
    """
    Attempts to convert num to a float and round it to 2 decimal places.
    If num is not a number, returns it unchanged.
    """
    try:
        return f"{round(float(num), 2)}"
    except Exception:
        return str(num)

def update_ui():
    global table_built
    # Call API functions.
    tick = api_helpers.get_tick(session)
    original_books = api_helpers.get_original_books(session)
    # prices API call and conversion to a dict.
    prices_response = api_helpers.get_from_api(session, "securities")
    prices_list = prices_response.json()
    # Convert list of dicts to a single dict.
    prices = {x["ticker"]: x["last"] for x in prices_list}
    
    # Get underlying prices.
    # Here we assume helpers.get_underlying_price returns a dict mapping tickers to values.
    underlying_prices = helpers.get_underlying_price(original_books, tick)
    print(underlying_prices)
    
    # Update the tick label.
    label_tick.config(text=f"Tick: {tick}")
    
    # Create or update table.
    # Use the tickers from the prices dict. (Assume underlying_prices has the same keys.)
    tickers = sorted(prices.keys())
    if not table_built:
        # Build the header row.
        for col, ticker in enumerate(tickers):
            header = tk.Label(table_frame, text=ticker, borderwidth=1, relief="solid", 
                              font=('Arial', 10, 'bold'), width=12)
            header.grid(row=0, column=col, padx=1, pady=1)
            header_labels[ticker] = header
        
        # Build the row for underlying prices.
        for col, ticker in enumerate(tickers):
            underlying_val = underlying_prices.get(ticker, "N/A")
            label = tk.Label(table_frame, 
                             text=format_number(underlying_val), 
                             borderwidth=1, relief="solid", 
                             font=('Arial', 10), width=12)
            label.grid(row=1, column=col, padx=1, pady=1)
            underlying_labels[ticker] = label
            
        # Build the row for current prices.
        for col, ticker in enumerate(tickers):
            current_val = prices.get(ticker, "N/A")
            label = tk.Label(table_frame, 
                             text=format_number(current_val), 
                             borderwidth=1, relief="solid", 
                             font=('Arial', 10), width=12)
            label.grid(row=2, column=col, padx=1, pady=1)
            current_labels[ticker] = label
        
        # Build the row for difference (current - underlying).
        for col, ticker in enumerate(tickers):
            underlying_val = underlying_prices.get(ticker)
            current_val = prices.get(ticker)
            # Calculate difference only if both values are numbers.
            try:
                difference = float(current_val) - float(underlying_val)
                diff_str = format_number(difference)
            except Exception:
                diff_str = "N/A"
                
            label = tk.Label(table_frame, 
                             text=diff_str, 
                             borderwidth=1, relief="solid", 
                             font=('Arial', 10), width=12)
            label.grid(row=3, column=col, padx=1, pady=1)
            difference_labels[ticker] = label
            
        table_built = True
    else:
        # Update the existing table labels.
        for ticker in header_labels:
            # Update underlying prices.
            new_underlying = underlying_prices.get(ticker, "N/A")
            underlying_labels[ticker].config(text=format_number(new_underlying))
            # Update current prices.
            new_current = prices.get(ticker, "N/A")
            current_labels[ticker].config(text=format_number(new_current))
            # Update difference.
            try:
                difference = float(new_current) - float(new_underlying)
                diff_str = format_number(difference)
            except Exception:
                diff_str = "N/A"
            difference_labels[ticker].config(text=diff_str)
                
    # Schedule the next update in 1000ms (1 second).
    root.after(1000, update_ui)

if __name__ == "__main__":
    # Start the update loop.
    root.after(1000, update_ui)
    # Start the Tkinter main loop.
    root.mainloop()
