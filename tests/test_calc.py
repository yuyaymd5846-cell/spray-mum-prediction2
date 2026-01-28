import datetime
import pytest
from src.calc import largest_remainder_method, predict_single_house

def test_largest_remainder_method_simple():
    total = 100
    ratios = [0.3, 0.3, 0.4]
    result = largest_remainder_method(total, ratios)
    assert result == [30, 30, 40]
    assert sum(result) == total

def test_largest_remainder_method_rounding():
    # total=10, ratios=[0.33, 0.33, 0.34] -> 3.3, 3.3, 3.4
    # floor: 3, 3, 3. sum=9. remainder=1.
    # decimal parts: 0.3, 0.3, 0.4.
    # largest decimal is 0.4 (index 2) -> index 2 gets +1.
    # result: 3, 3, 4.
    total = 10
    ratios = [0.33, 0.33, 0.34]
    result = largest_remainder_method(total, ratios)
    assert result == [3, 3, 4]
    assert sum(result) == total

def test_largest_remainder_method_complex_rounding():
    # Test case where multiple remainders might compete
    total = 5
    # 5 * 0.5 = 2.5
    # 5 * 0.5 = 2.5
    ratios = [0.5, 0.5]
    # base: 2, 2. sum=4. rem=1.
    # decimals: 0.5, 0.5. Tie.
    # First one should get it usually if stable sort/implementation.
    result = largest_remainder_method(total, ratios)
    assert sum(result) == total
    assert result == [3, 2] # Depending on sort stability, usually first index wins if simple sort

def test_predict_single_house_start_date():
    b_date = datetime.date(2023, 10, 1)
    # 49 days later
    # 30 remaining in Oct (31-1 = 30? No, 31 days in Oct. 1+49 = Oct 50?
    # Oct has 31 days. 10/1 + 30 days = 10/31. 10/31 + 19 days = 11/19.
    # Let's trust timedelta.
    expected_date = b_date + datetime.timedelta(days=49)
    
    res = predict_single_house("H1", "V1", 100, b_date, 1.0)
    assert res[0]['date'] == expected_date
    assert len(res) == 9

def test_predict_single_house_total_boxes():
    # area 100, coeff 1.2 -> 120 boxes
    b_date = datetime.date(2023, 10, 1)
    res = predict_single_house("H1", "V1", 100, b_date, 1.2)
    total_boxes = sum(r['boxes'] for r in res)
    assert total_boxes == 120

def test_predict_single_house_custom_ratio():
    # ratio with 2 elements for testing simplicity (though app uses 9)
    b_date = datetime.date(2023, 10, 1)
    ratio = [0.5, 0.5]
    res = predict_single_house("H1", "V1", 10, b_date, 1.0, distribution_ratio=ratio)
    assert len(res) == 2
    assert sum(r['boxes'] for r in res) == 10
