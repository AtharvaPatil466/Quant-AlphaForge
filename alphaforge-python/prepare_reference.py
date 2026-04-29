import pandas as pd
import sys

def find_data_start(filepath, marker):
    with open(filepath, 'r') as f:
        for i, line in enumerate(f):
            if line.strip().startswith(marker):
                return i
    raise ValueError(f"Could not find marker '{marker}' in {filepath}")

def is_valid_date(val):
    try:
        s = str(val).strip()
        return len(s) == 8 and s.isdigit()
    except:
        return False

def load_ff5(path):
    skip = find_data_start(path, ',Mkt-RF')
    df = pd.read_csv(path, skiprows=skip, index_col=0, on_bad_lines='skip')
    df = df[df.index.map(is_valid_date)]
    df.index = pd.to_datetime(df.index.astype(str), format='%Y%m%d')
    df.index.name = 'date'
    df = df.rename(columns={'Mkt-RF': 'MKT'})
    df = df[['MKT', 'SMB', 'HML', 'RMW', 'CMA', 'RF']].astype(float)
    return df / 100

def load_mom(path):
    skip = find_data_start(path, ',Mom')
    df = pd.read_csv(path, skiprows=skip, header=0, names=['date', 'Mom'], on_bad_lines='skip')
    df = df[df['date'].map(is_valid_date)]
    df['date'] = pd.to_datetime(df['date'].astype(str).str.strip(), format='%Y%m%d')
    df = df.set_index('date')
    df['UMD'] = pd.to_numeric(df['Mom'], errors='coerce') / 100
    return df[['UMD']].dropna()

ff5 = load_ff5(sys.argv[1])
mom = load_mom(sys.argv[2])
merged = ff5.join(mom, how='inner').dropna()

print(f"Rows: {len(merged)}")
print(f"Columns: {list(merged.columns)}")
print(f"Date range: {merged.index[0].date()} → {merged.index[-1].date()}")
print(merged.head(3))

merged.to_csv(sys.argv[3])
print(f"\nSaved to {sys.argv[3]}")
