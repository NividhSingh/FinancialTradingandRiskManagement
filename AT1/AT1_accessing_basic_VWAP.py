"""
Access basic VWAP strategy on given data

"""

import pandas as pd

# Compute purchase schedule from aggregated data
agg_df = pd.read_csv('dates_in_rows.csv', na_values=[''])
agg_df.set_index('Interval', inplace=True)
average_volumes = agg_df.mean(axis=1)
print("Average Volumes by Interval:")
print(average_volumes)
factor = 100000 / average_volumes.sum()
purchase_schedule = factor * average_volumes
print("\nPurchase Schedule (shares to buy at each interval):")
print(purchase_schedule)

# Compute VWAPs from half‐hour data
data_df = pd.read_csv('data_half_hour.csv', parse_dates=['Date'])
data_df['Time'] = data_df['Date'].dt.strftime('%H:%M')
data_df['Day'] = data_df['Date'].dt.date
results = []

for day, group in data_df.groupby('Day'):
    market_vwap = (group['Last Price'] * group['Volume']).sum() / group['Volume'].sum()
    group = group.copy()
    group['Purchase'] = group['Time'].map(purchase_schedule).fillna(0)
    total_purchase = group['Purchase'].sum()
    execution_vwap = (group['Last Price'] * group['Purchase']).sum() / total_purchase if total_purchase > 0 else None
    results.append({
        'Date': day,
        'Market_VWAP': market_vwap,
        'Execution_VWAP': execution_vwap,
        'Total_Target_Purchase': total_purchase
    })

results_df = pd.DataFrame(results)
print("\nDaily VWAPs (Market vs. Execution):")
print(results_df)
results_df['Date'] = pd.to_datetime(results_df['Date'])
results_df.to_csv('vwap_results.csv', index=False)
print("Results saved to vwap_results.csv")
