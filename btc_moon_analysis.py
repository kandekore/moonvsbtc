import datetime
import ephem
import yfinance as yf
import pandas as pd
import numpy as np

# Define the period: past 12 months (adjust as needed)
start_date = datetime.date(2024, 3, 13)
end_date = datetime.date(2025, 3, 13)

# Download BTC-USD daily data for an extended period to cover window edges.
# We add 15 days extra on each side to ensure our 28-day windows are covered.
data_start = start_date - datetime.timedelta(days=15)
data_end = end_date + datetime.timedelta(days=15)
btc_data = yf.download("BTC-USD", start=data_start.isoformat(), end=data_end.isoformat())
btc_data = btc_data[['Close']]  # we'll use the closing price

# Keep the index as a DatetimeIndex (do NOT convert to plain Python dates)
btc_data.index = pd.to_datetime(btc_data.index)

# Function to get moon phases in a date range using ephem.
def get_moon_phases(start, end, phase_type='full'):
    # phase_type: 'full' or 'new'
    phases = []
    dt = start - datetime.timedelta(days=1)
    if phase_type == 'full':
        next_phase = ephem.next_full_moon(dt)
    elif phase_type == 'new':
        next_phase = ephem.next_new_moon(dt)
    else:
        raise ValueError("phase_type must be 'full' or 'new'")
    
    while True:
        phase_date = next_phase.datetime().date()  # Python date
        if phase_date > end:
            break
        if phase_date >= start:
            phases.append(phase_date)
        if phase_type == 'full':
            next_phase = ephem.next_full_moon(next_phase)
        else:
            next_phase = ephem.next_new_moon(next_phase)
    return phases

# Get full and new moon dates in our period.
full_moons = get_moon_phases(start_date, end_date, phase_type='full')
new_moons = get_moon_phases(start_date, end_date, phase_type='new')

results = []

# For full moons: find the local high within a 28-day window (±14 days).
for moon_date in full_moons:
    window_start = pd.Timestamp(moon_date) - pd.Timedelta(days=14)
    window_end = pd.Timestamp(moon_date) + pd.Timedelta(days=14)
    window_data = btc_data.loc[(btc_data.index >= window_start) & (btc_data.index <= window_end)]
    if window_data.empty:
        continue
    local_high = window_data['Close'].max()
    # Use numpy to get the index position:
    pos = np.argmax(window_data['Close'].values)
    high_date = window_data.index[pos]  # This is a Timestamp
    day_offset = abs((high_date.date() - moon_date).days)
    results.append({
        'Moon Type': 'Full',
        'Moon Date': moon_date,
        'Local Extreme Price': local_high,
        'Extreme Date': high_date.date(),
        'Day Offset': day_offset
    })

# For new moons: find the local low within a 28-day window (±14 days).
for moon_date in new_moons:
    window_start = pd.Timestamp(moon_date) - pd.Timedelta(days=14)
    window_end = pd.Timestamp(moon_date) + pd.Timedelta(days=14)
    window_data = btc_data.loc[(btc_data.index >= window_start) & (btc_data.index <= window_end)]
    if window_data.empty:
        continue
    local_low = window_data['Close'].min()
    pos = np.argmin(window_data['Close'].values)
    low_date = window_data.index[pos]  # This is a Timestamp
    day_offset = abs((low_date.date() - moon_date).days)
    results.append({
        'Moon Type': 'New',
        'Moon Date': moon_date,
        'Local Extreme Price': local_low,
        'Extreme Date': low_date.date(),
        'Day Offset': day_offset
    })

# Convert results to a DataFrame and sort by Moon Date.
df_results = pd.DataFrame(results)
df_results = df_results.sort_values(by='Moon Date').reset_index(drop=True)

# Print the table to the terminal.
print(df_results)
