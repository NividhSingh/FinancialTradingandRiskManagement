"""
plots the complementary CDF

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

# Plot and calculation for CDF graph
sorted_volumes = np.sort(df['Volume'].values)
n = len(sorted_volumes)
ccdf_percentage = np.arange(n, 0, -1) / n * 100

plt.figure(figsize=(10, 6))
plt.step(sorted_volumes, ccdf_percentage, where='post', color='tab:blue')
plt.xlabel('Daily Total Volume')
plt.ylabel('Percentage of Days with Volume Above (%)')
plt.title('Complementary CDF (CCDF) of Daily Total Volume')
plt.grid(True)

# Annotate at thresholds x = 1,000,000 and 2,000,000
for threshold in [1_000_000, 2_000_000]:
    
    idx = np.searchsorted(sorted_volumes, threshold, side='left')
    if idx < n:
        y_val = ccdf_percentage[idx]
        plt.scatter(threshold, y_val, color='red', zorder=5)
        plt.annotate(f'({threshold:,}, {y_val:.1f}%)', 
                     xy=(threshold, y_val), 
                     xytext=(threshold * 1.05, y_val + 5),
                     arrowprops=dict(arrowstyle='->', color='red'),
                     fontsize=9)

plt.tight_layout()
plt.show()
