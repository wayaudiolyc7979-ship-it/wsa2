"""주파수 가중(IEC 61672 A/C) — 순수 함수.

v2.0 분해 1차 추출(wayaudo2.py에서 이동). 동작 0 변경.
골든: tests/test_dsp_golden.py::test_a_weight_db / test_c_weight_db.
"""
import math
import numpy as np


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


_HANN_CACHE = {}   # {n: (hanning_win, Σw²)} — power_spectrum_db 윈도우 메모이즈
def power_spectrum_db(buf):
    """단측(one-sided) 파워 스펙트럼 → 빈별 dBFS 배열.
    Hanning 윈도우 파워 보정(Σw², ENBW) + 단측 ×2 정규화 → 밴드 파워 합산값이
    실제 RMS 파워와 정합(Parseval). 톤/광대역 정규화가 일치하고 FFT 해상도·
    윈도우 종류에 무관 → Smaart 등 표준 RTA와 절대 레벨이 맞음.
    (FS 사인파 = -3 dBFS, 즉 RMS 기준)"""
    n = len(buf)
    cached = _HANN_CACHE.get(n)                 # n별 윈도우·Σw² 캐시 (매 청크 재계산 방지)
    if cached is None:
        win = np.hanning(n).astype(np.float32)
        cached = (win, float(np.dot(win, win)))  # Σw² (Hanning ≈ 0.375·n)
        _HANN_CACHE[n] = cached
    win, win_pow = cached
    ps = np.abs(np.fft.rfft(buf * win)) ** 2
    ps *= 2.0 / (n * win_pow)                   # 단측 파워 정규화 (윈도우/해상도 무관)
    ps[0] *= 0.5
    if n % 2 == 0: ps[-1] *= 0.5               # DC·Nyquist는 단측 ×2 제외
    np.maximum(ps, 1e-20, out=ps)
    return 10.0 * np.log10(ps)
