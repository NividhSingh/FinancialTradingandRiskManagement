"""
Plots vwap percent differences

"""
import pandas as pd
import matplotlib.pyplot as plt

# Read csv
results = pd.read_csv('vwap_results.csv', parse_dates=['Date'])

# Calculate the percent difference between Execution VWAP and Market VWAP
# Percent Difference = ((Execution_VWAP - Market_VWAP) / Market_VWAP) * 100
results['PercentDifference'] = ((results['Execution_VWAP'] - results['Market_VWAP']) /
                                results['Market_VWAP']) * 100

# Display the updated DataFrame
print(results[['Date', 'Market_VWAP', 'Execution_VWAP', 'PercentDifference']])

# Create a Box Plot
plt.figure(figsize=(8, 6))
plt.boxplot(results['PercentDifference'].dropna(), patch_artist=True)
plt.ylabel('Percent Difference (%)')
plt.title('Box Plot of Percent Differences\n(Execution VWAP vs Market VWAP)')
plt.grid(True)
plt.show()
