"""
Plots box and whisker for volumes

"""
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# Read CSV
df = pd.read_csv('data.csv', parse_dates=['Date'])

# Group by date
daily_volume = df.groupby('Date')['Volume'].sum()

# Exclude days with zero volume.
daily_volume = daily_volume[daily_volume != 0]

# Convert to NumPy
data = daily_volume.values

# Calculate box and whisker boundries
Q1 = np.percentile(data, 25)
Q3 = np.percentile(data, 75)
IQR = Q3 - Q1

# Calculate the typical whisker range.
lower_whisker = Q1 - 1.5 * IQR
upper_whisker = Q3 + 1.5 * IQR

# Create a horizontal box and whisker plot.
plt.figure(figsize=(8, 6))
plt.boxplot(data, patch_artist=True, notch=True, vert=False, showfliers=False)

# Set the title and axis labels.
plt.title('Horizontal Box and Whisker Plot of Total Volume Traded per Date\n(Cropped to Exclude Outliers)')
plt.xlabel('Total Volume Traded')
plt.yticks([1], ['Daily Volume'])

# Adjust the x-axis limits to zoom in on the whisker range.
plt.xlim(lower_whisker, upper_whisker)

# Display the plot.
plt.show()
