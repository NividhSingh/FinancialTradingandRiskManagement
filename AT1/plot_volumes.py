"""
This program plots the volume for every thirty minutes 

"""
import pandas as pd
import matplotlib.pyplot as plt

# Read CSV
df = pd.read_csv('data.csv')

# Convert date to datetime object
df['DateTime'] = pd.to_datetime(df['Date'], format="%m/%d/%y %H:%M")

# Convert extra columns for the intervals
df['Date_str'] = df['DateTime'].dt.strftime("%m/%d/%Y")
df['Interval'] = df['DateTime'].dt.floor('30T').dt.strftime("%H:%M")

# Group by the interval column
grouped = df.groupby(['Date_str', 'Interval'])['Volume'].sum().reset_index()

# Transpose
pivot_df = grouped.pivot(index='Interval', columns='Date_str', values='Volume')

# Sort by times
pivot_df.index = pd.to_datetime(pivot_df.index, format="%H:%M")
pivot_df = pivot_df.sort_index()
# Convert back to HH:MM string format for display.
pivot_df.index = pivot_df.index.strftime("%H:%M")

# Reset index
final_df = pivot_df.reset_index().rename(columns={'index': 'Interval'})

# Write to a csv file
final_df.to_csv('dates_in_rows.csv', index=False)
print("CSV file 'dates_in_rows.csv' created.")

# Graph data
plt.figure(figsize=(10, 6))
for date in pivot_df.columns:
    plt.plot(pivot_df.index, pivot_df[date], marker='o', linestyle='-', label=date)

plt.xlabel("Interval")
plt.ylabel("Volume")
plt.title("Volume by 30-Minute Intervals for Each Day")
plt.xticks(rotation=45)
# plt.legend(title="Date")
plt.grid(True)
plt.tight_layout()
plt.show()
