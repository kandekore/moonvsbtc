import datetime
import ephem
import yfinance as yf
import pandas as pd
import numpy as np

# --------------------------------
# 1) Set up your date range
# --------------------------------
today = datetime.date.today()
one_year_ago = today - datetime.timedelta(days=365)
start_date = one_year_ago
end_date = today

# We still add a buffer so we don't miss data up to 14 days after the final moon date.
# If the user wants to see 14 days after the last moon in the period, let's add ~15 days.
buffer_days = 15
data_start = start_date
data_end = end_date + datetime.timedelta(days=buffer_days)

# --------------------------------
# 2) Download BTC data (Close only)
# --------------------------------
btc_data = yf.download("BTC-USD", start=data_start.isoformat(), end=data_end.isoformat())
btc_data = btc_data[['Close']].rename(columns={'Close': 'BTC_Close'})
btc_data.index = pd.to_datetime(btc_data.index)

# --------------------------------
# 3) Define a function to get phases
# --------------------------------
def get_moon_phases(start, end, phase_type='full'):
    """
    Return a list of Python date objects corresponding to either Full or New Moons 
    between 'start' and 'end' inclusive. 'start'/'end' are datetime.date.
    """
    phases = []
    # ephem expects an initial time just before our start date
    day_before = start - datetime.timedelta(days=1)
    
    if phase_type == 'full':
        next_phase = ephem.next_full_moon(day_before.isoformat())
    elif phase_type == 'new':
        next_phase = ephem.next_new_moon(day_before.isoformat())
    else:
        raise ValueError("phase_type must be 'full' or 'new'")

    while True:
        phase_dt = next_phase.datetime()  # Python datetime
        phase_date = phase_dt.date()
        if phase_date > end:
            break
        if phase_date >= start:
            phases.append(phase_date)
        # Move to the next occurrence
        if phase_type == 'full':
            next_phase = ephem.next_full_moon(next_phase)
        else:
            next_phase = ephem.next_new_moon(next_phase)

    return phases

full_moons = get_moon_phases(start_date, end_date, phase_type='full')
new_moons = get_moon_phases(start_date, end_date, phase_type='new')

# --------------------------------
# 4) Find local extremes in the 14 days AFTER each moon
# --------------------------------
def find_local_extreme(series, extreme='max'):
    """Given a Pandas Series, return the extreme value and the date it occurred."""
    if series.empty:
        return None, None
    if extreme == 'max':
        local_value = series.max()
        pos = np.argmax(series.values)
    else:  # 'min'
        local_value = series.min()
        pos = np.argmin(series.values)
    date_of_extreme = series.index[pos]
    return local_value, date_of_extreme

results = []

# For Full Moons, find the highest close in [Moon Date, Moon Date + 14 days]
for moon_date in full_moons:
    wstart = pd.Timestamp(moon_date)
    wend = pd.Timestamp(moon_date) + pd.Timedelta(days=14)
    
    window_data = btc_data.loc[(btc_data.index >= wstart) & (btc_data.index <= wend), 'BTC_Close']
    if not window_data.empty:
        local_high, high_date = find_local_extreme(window_data, 'max')
        offset = (high_date.date() - moon_date).days  # can be 0 if same day
        results.append({
            'Moon Type': 'Full',
            'Moon Date': moon_date,
            'Local Extreme Price': local_high,
            'Extreme Date': high_date.date(),
            'Day Offset': offset
        })

# For New Moons, find the lowest close in [Moon Date, Moon Date + 14 days]
for moon_date in new_moons:
    wstart = pd.Timestamp(moon_date)
    wend = pd.Timestamp(moon_date) + pd.Timedelta(days=14)
    
    window_data = btc_data.loc[(btc_data.index >= wstart) & (btc_data.index <= wend), 'BTC_Close']
    if not window_data.empty:
        local_low, low_date = find_local_extreme(window_data, 'min')
        offset = (low_date.date() - moon_date).days
        results.append({
            'Moon Type': 'New',
            'Moon Date': moon_date,
            'Local Extreme Price': local_low,
            'Extreme Date': low_date.date(),
            'Day Offset': offset
        })

df_results = pd.DataFrame(results).sort_values(by='Moon Date').reset_index(drop=True)

# --------------------------------
# 5) Convert DataFrame to HTML
# --------------------------------
html_table = df_results.to_html(
    index=False,
    float_format="%.2f",  # Format floats with 2 decimals
    border=1
)

# --------------------------------
# 6) Build a minimal HTML page
# --------------------------------
html_template = f"""
<html>
<head>
    <meta charset="UTF-8" />
    <title>BTC Moon Correlation (Forward 14 Days)</title>
</head>
<body>
    <h1>BTC Price Extremes vs. Moon Phases (Forward 14 Days)</h1>
    {html_table}
</body>
</html>
"""

# --------------------------------
# 7) Save HTML to a file
# --------------------------------
with open("moon_phase_table.html", "w", encoding="utf-8") as f:
    f.write(html_template)

print("HTML file 'moon_phase_table.html' has been created.")