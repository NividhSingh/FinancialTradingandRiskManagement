"""
Plots the Total Daily Volume over the 32 trading days 

"""
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# Read the CSV file
df = pd.read_csv('data_half_hour.csv')
df['Date'] = pd.to_datetime(df['Date'])
daily_volume = df.groupby(df['Date'].dt.date)['Volume'].sum().reset_index()
daily_volume['Date'] = daily_volume['Date'].astype(str)
data = {
    'Date': daily_volume['Date'].tolist(),
    'Volume': daily_volume['Volume'].tolist()
}

print(data)


# Create pandas dataframe
df = pd.DataFrame(data)
df['Date'] = pd.to_datetime(df['Date'])
df.set_index('Date', inplace=True)

# Plot timeseries with data
plt.figure(figsize=(10, 6))
plt.plot(df.index, df['Volume'], marker='o', linestyle='-', color='tab:blue')
plt.xlabel('Date')
plt.ylabel('Daily Total Volume')
plt.title('Daily Total Volume Over Time')
plt.xticks(rotation=45)
plt.grid(True)
plt.tight_layout()
plt.show()
