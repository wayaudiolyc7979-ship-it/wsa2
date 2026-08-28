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


# ── 옥타브 밴드 정의/합산 (IEC 61260) ──
THIRD_OCT = [
    20,25,31.5,40,50,63,80,100,125,160,200,250,
    315,400,500,630,800,1000,1250,1600,2000,2500,
    3150,4000,5000,6300,8000,10000,12500,16000,20000
]
def make_oct_bands(bpo):
    bands, ratio = [], 2**(1/bpo)
    fc = 1000.0
    while fc/ratio > 15: fc /= ratio
    while fc <= 22000:
        if 18 <= fc <= 20000: bands.append(round(fc,4))
        fc *= ratio
    return bands
BANDS = {'oct3':THIRD_OCT,'oct12':make_oct_bands(12),'oct24':make_oct_bands(24)}


_OCT_MASK_CACHE = {}   # (len(freqs), nyquist반올림, mode) → 밴드별 인덱스 캐시(매 프레임 마스크 재계산 방지)
def _octave_bands(freqs, db_vals, mode):
    """빈별 dB → 옥타브 밴드 dB (IEC 61260 파워 합산). MainWindow._calc_oct의 모듈판 — TF RTA용.
    밴드별 빈 인덱스를 그리드별로 캐시해 매 프레임 마스크 재계산을 피함(렌더 부하 절감)."""
    key = (len(freqs), int(round(float(freqs[-1]))), mode)
    plan = _OCT_MASK_CACHE.get(key)
    if plan is None:
        bands = BANDS[mode]
        bpo = 3 if mode == 'oct3' else 12 if mode == 'oct12' else 24
        half = 1 / (2 * bpo)
        plan = []
        for fc in bands:
            fl, fh = fc / 2 ** half, fc * 2 ** half
            idxs = np.where((freqs >= fl) & (freqs <= fh))[0]
            if len(idxs):
                plan.append(('sum', idxs))
            else:
                idx = int(np.argmin(np.abs(freqs - fc)))
                if 0 < idx < len(freqs) - 1:
                    f0, f1 = float(freqs[idx - 1]), float(freqs[idx])
                    t = max(0.0, min(1.0, (fc - f0) / (f1 - f0) if f1 > f0 else 0.5))
                    plan.append(('interp', idx, t))
                else:
                    plan.append(('one', idx))
        _OCT_MASK_CACHE[key] = plan
    res = []
    for item in plan:
        if item[0] == 'sum':
            res.append(float(10 * np.log10(np.sum(10 ** (db_vals[item[1]] / 10)))))
        elif item[0] == 'interp':
            _, idx, t = item
            res.append(float(db_vals[idx - 1]) * (1 - t) + float(db_vals[idx]) * t)
        else:
            res.append(float(db_vals[item[1]]))
    return res
