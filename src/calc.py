import datetime
from math import floor
from typing import List, Dict, Optional
import pandas as pd

def largest_remainder_method(total_integer: int, proportions: List[float]) -> List[int]:
    """
    Distributes a total integer into parts based on proportions using the Largest Remainder Method.
    Ensures the sum of parts exactly equals total_integer.
    """
    if total_integer < 0:
        raise ValueError("Total integer must be non-negative.")
    
    # Calculate raw shares
    raw_values = [total_integer * p for p in proportions]
    
    # integer parts
    int_parts = [floor(v) for v in raw_values]
    
    # fractional parts
    remainders = [v - i for v, i in zip(raw_values, int_parts)]
    
    # The number of units left to distribute
    leftover = total_integer - sum(int_parts)
    
    # Zip indices with remainders to sort by remainder descending
    # We use a stable sort or just simple sort. 
    # If remainders are equal, the earlier index gets priority (standard implementation detail).
    indexed_remainders = sorted(enumerate(remainders), key=lambda x: x[1], reverse=True)
    
    # Add 1 to the top 'leftover' items
    for i in range(leftover):
        index, _ = indexed_remainders[i]
        int_parts[index] += 1
        
    return int_parts

def predict_single_house(
    house_name: str,
    variety: str,
    area_tsubo: float,
    blackout_date: datetime.date,
    coeff: float = 1.2,
    days_to_start: int = 49,
    color: str = "",
    shape: str = "",
    distribution_ratio: Optional[List[float]] = None,
    producer: str = ""
) -> List[Dict]:
    """
    Generates a 9-day shipment prediction for a single house.
    
    Returns a list of dictionaries:
    {
        'date': datetime.date,
        'house_name': str,
        'variety': str,
        'color': str,
        'shape': str,
        'producer': str,
        'boxes': int
    }
    """
    if distribution_ratio is None:
        # Default ratio for 14 days (updated based on user request)
        distribution_ratio = [
            0.0314, 0.0952, 0.1404, 0.1543, 0.1442, 0.1218, 0.0958,
            0.0716, 0.0515, 0.0358, 0.0244, 0.0162, 0.0106, 0.0068
        ]

    # Validate ratio (optional: normalized if not summing to 1, but user requested error or normalize.
    # Logic: Let's normalize it to be safe for the calculation, assuming the inputs might be slightly off floating point wise.
    total_ratio = sum(distribution_ratio)
    if not (0.99 < total_ratio < 1.01):
        # Normalize
        distribution_ratio = [r / total_ratio for r in distribution_ratio]
        

        
    # Logic: start_date = blackout_date + days_to_start
    start_date = blackout_date + datetime.timedelta(days=days_to_start)
    
    # Logic: total_boxes = round(area_tsubo * coeff)
    total_boxes = int(round(area_tsubo * coeff))
    
    # distribute
    daily_boxes = largest_remainder_method(total_boxes, distribution_ratio)
    
    results = []
    current_date = start_date
    for boxes in daily_boxes:
        results.append({
            "date": current_date,
            "house_name": house_name,
            "variety": variety,
            "color": color,
            "shape": shape,
            "producer": producer,
            "boxes": boxes
        })
        current_date += datetime.timedelta(days=1)
        
    return results

def aggregate_shipments(
    records: List[Dict],
    view_start_date: datetime.date,
    days: int = 14
) -> pd.DataFrame:
    """
    Aggregates a list of detailed records into a summary DataFrame for the view period.
    The view period is [view_start_date, view_start_date + days - 1].
    """
    
    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=["date", "variety", "boxes"])
    
    # Filter by date range
    end_date = view_start_date + datetime.timedelta(days=days - 1)
    mask = (df['date'] >= view_start_date) & (df['date'] <= end_date)
    filtered_df = df.loc[mask].copy()
    
    return filtered_df

def adjust_to_shipping_days(records: List[Dict]) -> List[Dict]:
    """
    Adjusts shipment dates to Monday, Wednesday, or Saturday.
    - Sun, Mon -> Mon
    - Tue, Wed -> Wed
    - Thu, Fri, Sat -> Sat
    """
    adjusted_records = []
    
    # We need to aggregate boxes if they fall on the same adjusted date for the same house, variety, etc.
    # A simple way is to modify the date first, then re-aggregate or just append and let the main app aggregate (but main app aggregation is for view).
    # Since predict_single_house returns detailed list, we can just modify dates here.
    # However, if we just change dates, we might have multiple entries for the same day (e.g. original Thu and Fri both become Sat).
    # It is cleaner to merge them here so the list remains clean, though not strictly necessary if the UI handles it.
    # Let's simple-shift first. If exact same attributes, we merge.
    
    temp_map = {} # Key: (producer, house_name, variety, color, shape, adjusted_date) -> boxes
    
    for r in records:
        original_date = r['date']
        weekday = original_date.weekday() # Mon=0, Sun=6
        
        # Logic:
        # Mon(0) -> Mon(0) (diff 0)
        # Tue(1) -> Wed(2) (diff +1)
        # Wed(2) -> Wed(2) (diff 0)
        # Thu(3) -> Sat(5) (diff +2)
        # Fri(4) -> Sat(5) (diff +1)
        # Sat(5) -> Sat(5) (diff 0)
        # Sun(6) -> Mon(next) ?? Wait, user said "(月)なら(日)(月)分を合算".
        # Usually this means Sunday shipment is moved to Mon. 
        # CAUTION: Is it NEXT Monday or THIS Monday? 
        # "Week starts on Monday" usually. Sunday is end of week.
        # Impl: Sun(6) -> Mon(0) of NEXT week? Or just move to closest forward date?
        # Context: "shipping date". If harvested on Sunday, ship on Monday. Yes, next day.
        
        shift_days = 0
        if weekday == 0: # Mon
            pass
        elif weekday == 1: # Tue -> Wed
            shift_days = 1
        elif weekday == 2: # Wed
            pass
        elif weekday == 3: # Thu -> Sat
            shift_days = 2
        elif weekday == 4: # Fri -> Sat
            shift_days = 1
        elif weekday == 5: # Sat
            pass
        elif weekday == 6: # Sun -> Mon (Next Day)
            shift_days = 1
            
        new_date = original_date + datetime.timedelta(days=shift_days)
        
        # Include producer in key. Use get() with default empty string for backward compatibility
        prod = r.get('producer', '')
        key = (prod, r['house_name'], r['variety'], r['color'], r['shape'], new_date)
        
        if key in temp_map:
            temp_map[key] += r['boxes']
        else:
            temp_map[key] = r['boxes']
            
    # Reconstruct list
    for (prod, h, v, c, s, d), boxes in temp_map.items():
        adjusted_records.append({
            "date": d,
            "producer": prod,
            "house_name": h,
            "variety": v,
            "color": c,
            "shape": s,
            "boxes": boxes
        })
        
    # Sort by date for tidiness
    adjusted_records.sort(key=lambda x: x['date'])
    return adjusted_records
