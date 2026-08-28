"""주파수 가중(IEC 61672 A/C) — 순수 함수.

v2.0 분해 1차 추출(wayaudo2.py에서 이동). 동작 0 변경.
골든: tests/test_dsp_golden.py::test_a_weight_db / test_c_weight_db.
"""
import math


# A-가중치 계수 (IEC 61672)
def a_weight_db(f):
    if f < 10: return -100
    f2 = f*f; f4 = f2*f2
    ra = (12200**2 * f4) / ((f2+20.6**2)*math.sqrt((f2+107.7**2)*(f2+737.9**2))*(f2+12200**2))
    return 20*math.log10(max(ra, 1e-20)) + 2.0


# C-가중치 계수
def c_weight_db(f):
    if f < 10: return -100
    f2 = f*f
    rc = (12200**2 * f2) / ((f2+20.6**2)*(f2+12200**2))
    return 20*math.log10(max(rc, 1e-20)) + 0.06
