"""
Converts 15 minute intervals to 30 minute intervals
"""
import pandas as pd

# Read CSV
df = pd.read_csv('data.csv', parse_dates=['Date'])

df.set_index('Date', inplace=True)

# Resample to 30 minutes (used chatgpt to find this function)
df_half_hour = df.resample('30T').agg({'Last Price': 'last', 'Volume': 'sum'})


df_half_hour = df_half_hour[df_half_hour['Volume'] > 0]
df_half_hour = df_half_hour.reset_index()

# Save and print
df_half_hour.to_csv('data_half_hour.csv', index=False)
print(df_half_hour)
