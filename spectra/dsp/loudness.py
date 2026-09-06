"""Loudness (ITU-R BS.1770-4) — 순수 DSP.

v2.0 분해: wayaudo2.py에서 _biquad/_KWeightFilter/LoudnessMeter 이동(동작 0 변경).
골든: tests/test_dsp_golden.py::test_loudness_1khz_tone / test_biquad_impulse / test_kweight_coefficients_48k.
"""
import math
import numpy as np
from collections import deque


_lfilter = None      # None=미해결 / False=사용불가 / callable=사용가능 (첫 호출 때 지연 해결)


def _resolve_lfilter():
    """scipy.signal을 지연 로딩.

    [기동시간] 모듈 최상단에서 import하면 scipy.signal이 scipy.stats/interpolate/optimize·
    numpy.f2py까지 끌고 와 **앱 기동에 411ms**가 붙는다(main_window import 540ms 중 76%).
    이 코드베이스의 다른 scipy 사용처는 전부 지연 로딩이라 여기만 예외였다.

    ⚠️ 단순 지연 로딩만 하면 안 된다 — 라우드니스는 (오디오 스레드가 아니라) **GUI 스레드**에서
    돌기 때문에, 첫 _biquad 호출이 Stereo 시작 순간 GUI를 ~600ms 얼린다(실측으로 확인).
    그래서 아래 _warm_lfilter()가 import 직후 데몬 스레드로 미리 당겨온다:
    기동은 안 막고(스레드 시작 ~0.1ms), 실제 사용 시점엔 이미 준비돼 있다."""
    global _lfilter
    try:
        from scipy.signal import lfilter
        _lfilter = lfilter
    except Exception:
        _lfilter = False
    return _lfilter


def _warm_lfilter():
    """백그라운드에서 scipy.signal을 미리 로드 — 기동도, 첫 측정도 막지 않게."""
    import threading
    threading.Thread(target=_resolve_lfilter, name='scipy-warm', daemon=True).start()


_warm_lfilter()


def _biquad(x, b, a, z):
    """Transposed direct form II biquad — stateful via z[0..1] (in-place 갱신).

    scipy.signal.lfilter의 zi 상태 규약이 이 형식과 정확히 같아 그대로 대체 가능하다
    (y[n]=b0·x[n]+z0 / z0'=b1·x[n]−a1·y[n]+z1 / z1'=b2·x[n]−a2·y[n]).
    순수 파이썬 샘플 루프는 512프레임 스테레오 push마다 ~2.15ms가 들고 초당 ~94회 호출돼
    **상시 코어 10~14%** 를 먹었다(실측). C 루프로 바꿔 회수한다. scipy 없으면 기존 루프 폴백."""
    _lf = _lfilter if _lfilter is not None else _resolve_lfilter()
    if _lf:
        y, zf = _lf(b, a, x, zi=z)
        z[0] = zf[0]; z[1] = zf[1]      # 호출부가 in-place 상태 유지를 기대
        return y
    b0,b1,b2=b[0],b[1],b[2]; a1,a2=a[1],a[2]
    y=np.empty_like(x)
    for i in range(len(x)):
        xi=float(x[i]); yi=b0*xi+z[0]
        z[0]=b1*xi-a1*yi+z[1]; z[1]=b2*xi-a2*yi; y[i]=yi
    return y


class _KWeightFilter:
    """ITU-R BS.1770-4 K-weighting: pre-filter(high-shelf) → RLB(high-pass)."""
    # 48000 = 규격 상수(골든 락). 그 외 SR(44.1/88.2/96/176.4/192k…)은 _gen_coeffs로 정확 생성.
    # ※ 예전엔 44100 계수도 표에 있었으나 값이 오타로 틀려(pre-filter가 저역서 0dB가 아니고
    #   @100Hz K-gain −3.12dB로 48k의 −1.14dB와 불일치) 44.1kHz 라우드니스가 원래부터 비규격이었다.
    #   생성기는 48000을 오차 ~1e-14로 재현하고 44100을 규격값(@100Hz −1.13dB)으로 산출 → 표에서 제거.
    _C={
        48000:{
            'pre':([1.53512485958697,-2.69169618940638,1.19839281085285],
                   [1.0,-1.69065929318241,0.73248077421585]),
            'rlb':([1.0,-2.0,1.0],[1.0,-1.99004745483398,0.99007225036621])},
    }
    @staticmethod
    def _gen_coeffs(sr):
        """표에 없는 샘플레이트용 K-weighting 계수 생성 — pyloudnorm/BS.1770 방식
        (K=tan 프리워핑 bilinear). 예전엔 44.1/48k 외 전부 48k 계수로 폴백(리샘플 없음)해
        88.2/96/176.4/192k에서 필터 코너가 어긋나 M/S/I/LRA가 비규격이던 것을 바로잡음.
        48000에서 표값을 오차 ~1e-14로 재현하므로 경계 불연속 없음."""
        # pre-filter: high-shelf
        G=3.999843853973347; Q=0.7071752369554196; fc=1681.9744509555319
        K=math.tan(math.pi*fc/sr); Vh=10.0**(G/20.0); Vb=Vh**0.499666774155
        a0=1.0+K/Q+K*K
        pre_b=[(Vh+Vb*K/Q+K*K)/a0, 2.0*(K*K-Vh)/a0, (Vh-Vb*K/Q+K*K)/a0]
        pre_a=[1.0, 2.0*(K*K-1.0)/a0, (1.0-K/Q+K*K)/a0]
        # RLB: high-pass
        Q2=0.5003270373253953; fc2=38.13547087602444
        K2=math.tan(math.pi*fc2/sr); a0b=1.0+K2/Q2+K2*K2
        rlb_b=[1.0,-2.0,1.0]
        rlb_a=[1.0, 2.0*(K2*K2-1.0)/a0b, (1.0-K2/Q2+K2*K2)/a0b]
        return {'pre':(pre_b,pre_a), 'rlb':(rlb_b,rlb_a)}

    def __init__(self,sr):
        c=self._C.get(sr) or self._gen_coeffs(sr)   # 44.1/48k=검증된 표, 그 외=SR별 정확 생성
        self._pb=np.array(c['pre'][0],dtype=np.float64)
        self._pa=np.array(c['pre'][1],dtype=np.float64)
        self._rb=np.array(c['rlb'][0],dtype=np.float64)
        self._ra=np.array(c['rlb'][1],dtype=np.float64)
        self._pz=np.zeros(2,dtype=np.float64)
        self._rz=np.zeros(2,dtype=np.float64)
    def process(self,x):
        y=_biquad(x.astype(np.float64),self._pb,self._pa,self._pz)
        return _biquad(y,self._rb,self._ra,self._rz).astype(np.float32)
    def reset(self): self._pz[:]=0; self._rz[:]=0


class LoudnessMeter:
    """ITU-R BS.1770-4 기반 LUFS / LRA / TruePeak 미터.

    [장시간 구동] 적분 누적을 '무한히 자라는 파이썬 리스트 + 매번 전체 재스캔'으로 두면
    경과시간에 비례해 GUI 스레드를 잡아먹는다(8시간 구동 시 코어 17%, push p95 18.8ms 실측).
    그래서 ①I는 100ms 부분블록을 저장하지 않고 **400ms 게이팅 블록만 증분 계산해 ndarray로 축적**
    (list→array 변환·cumsum 제거) ②LRA는 **0.01 LU 히스토그램**으로 누적해 percentile을
    O(bins) 상수시간으로 만든다. 둘 다 값은 규격 그대로."""
    _BLK_MS=100  # 100ms 블록
    # LRA 히스토그램(EBU 3342): 절대게이트 −70 LUFS 위만 담으므로 −70..+10 LUFS, 0.01 LU 분해능
    _LRA_LO=-70.0; _LRA_HI=10.0; _LRA_BW=0.01
    _LRA_NB=int(round((_LRA_HI-_LRA_LO)/_LRA_BW))          # 8000 bins
    _LRA_CENTERS=_LRA_LO+(np.arange(_LRA_NB)+0.5)*_LRA_BW  # 각 bin 중앙 LUFS (클래스 1회 계산)
    _LRA_MS=10.0**((_LRA_CENTERS+0.691)/10.0)              # 중앙 LUFS → 평균제곱 (상대게이트 평균용)

    def __init__(self,sr):
        self.sr=sr
        self._kfl=_KWeightFilter(sr); self._kfr=_KWeightFilter(sr)
        self._blk=max(1,sr*self._BLK_MS//1000)
        self._sq_hist=deque(maxlen=30)   # 3초 = 30블록 (short-term)
        self._fast_hist=deque(maxlen=5)  # 0.5초 = 5블록 (레이더용)
        self._int_on=False
        # I용: 400ms 게이팅 블록(75% 겹침)의 평균제곱을 증분 축적하는 성장형 ndarray
        self._gb=np.empty(4096,dtype=np.float64); self._gb_n=0
        self._sub4=deque(maxlen=4)       # 최근 100ms 부분블록 4개(=400ms 게이팅 블록 재료)
        self._acc_l=0.0; self._acc_r=0.0; self._acc_n=0
        self._M=-100.0; self._S=-100.0; self._S_fast=-100.0
        self._I=-100.0; self._LRA=0.0; self._TP=-100.0; self._PH=-100.0
        self._tp_tail_l=None; self._tp_tail_r=None   # True Peak 4× 오버샘플 연속성 테일
        self._lra_hist=np.zeros(self._LRA_NB,dtype=np.int64)  # EBU 3342 short-term 분포(히스토그램)
        self._maxM=-100.0; self._maxS=-100.0   # Max Momentary / Max Short-term

    def _gb_push(self, ms):
        """400ms 게이팅 블록 하나를 성장형 배열에 추가(용량 2배씩 확장 = 상각 O(1))."""
        if self._gb_n >= self._gb.shape[0]:
            self._gb=np.resize(self._gb, self._gb.shape[0]*2)
        self._gb[self._gb_n]=ms; self._gb_n+=1

    @staticmethod
    def _lufs(ms):
        return float(-0.691+10*math.log10(max(ms,1e-12)))

    def _true_peak_db(self, L, R):
        """ITU-R BS.1770 True Peak — 4× 오버샘플로 샘플 사이 피크(inter-sample)까지 검출.
        블록 경계 연속성 위해 직전 8샘플(테일) 이어붙여 워밍업 구간 제거."""
        try:
            from scipy.signal import resample_poly
        except Exception:
            pk = max(float(np.max(np.abs(L))), float(np.max(np.abs(R))))
            return 20.0*math.log10(max(pk,1e-9))   # 폴백: 샘플 피크
        def ch(x, tail):
            x = np.asarray(x, dtype=np.float64)
            t = tail if tail is not None else np.zeros(8)
            seg = np.concatenate([t, x])
            os = resample_poly(seg, 4, 1)[32:]      # 테일 8샘플×4 워밍업 제거 → 새 블록 구간
            pk = float(np.max(np.abs(os))) if os.size else 0.0
            nt = x[-8:] if x.size >= 8 else seg[-8:]
            return pk, nt
        pl, self._tp_tail_l = ch(L, self._tp_tail_l)
        pr, self._tp_tail_r = ch(R, self._tp_tail_r)
        return 20.0*math.log10(max(max(pl, pr), 1e-9))

    def push(self,L,R):
        pk_db=self._true_peak_db(L,R)
        if pk_db>self._TP: self._TP=pk_db
        if pk_db>self._PH: self._PH=pk_db
        lk=self._kfl.process(L); rk=self._kfr.process(R)
        sq_l=lk.astype(np.float64)**2; sq_r=rk.astype(np.float64)**2
        i=0; n=len(L); blk_done=False
        while i<n:
            space=self._blk-self._acc_n; take=min(space,n-i)
            self._acc_l+=float(np.sum(sq_l[i:i+take]))
            self._acc_r+=float(np.sum(sq_r[i:i+take]))
            self._acc_n+=take; i+=take
            if self._acc_n>=self._blk:
                ms=(self._acc_l+self._acc_r)/self._blk   # BS.1770: 채널 평균제곱의 합(z_L+z_R). /2(평균) 아님 → 이전 대비 +3.01 LU
                self._sq_hist.append(ms)
                self._fast_hist.append(ms)
                if self._int_on:
                    # 400ms/75%겹침 게이팅 블록을 '그 자리에서' 하나 만들어 축적
                    # (100ms 부분블록 전체를 들고 있다가 매번 재스캔하지 않는다)
                    self._sub4.append(ms)
                    if len(self._sub4)==4:
                        self._gb_push((self._sub4[0]+self._sub4[1]+self._sub4[2]+self._sub4[3])*0.25)
                    # EBU 3342: full 3s short-term 값을 히스토그램에 누적 (블록당 1회)
                    if len(self._sq_hist)>=30:
                        _st=self._lufs(float(np.mean(self._sq_hist)))
                        if _st>self._LRA_LO:          # 절대 게이트 −70 위만 분포에 반영
                            _bi=int((_st-self._LRA_LO)/self._LRA_BW)
                            if _bi<0: _bi=0
                            elif _bi>=self._LRA_NB: _bi=self._LRA_NB-1
                            self._lra_hist[_bi]+=1
                self._acc_l=0.0; self._acc_r=0.0; self._acc_n=0
                blk_done=True
        N=len(self._sq_hist)
        if N>=4: self._M=self._lufs(float(np.mean(list(self._sq_hist)[-4:])))
        if N>=5: self._S_fast=self._lufs(float(np.mean(self._fast_hist)))
        if N>=10: self._S=self._lufs(float(np.mean(list(self._sq_hist))))
        if self._M>self._maxM: self._maxM=self._M
        if self._S>self._maxS: self._maxS=self._S
        # I/LRA는 누적배열(_int_sq·_lra_st)이 바뀔 때만 변함 → 새 블록이 완성됐을 때만 재계산.
        # raw 청크마다(초당 ~94회) 호출하면 O(n)·O(n log n) 재계산이 경과시간에 비례해 커져
        # 장시간 구동 시 GUI 스레드가 raw_ready 큐를 못 따라가 멈춤. 블록 단위(초당 10회)로 한정.
        if blk_done:
            self._compute_I()
            self._compute_LRA()

    def _compute_I(self):
        """BS.1770-4 게이팅: 400ms 블록·75% 오버랩. 블록은 push()에서 이미 증분 생성돼
        _gb[:_gb_n]에 있으므로 여기선 두 번의 마스크 평균만 한다(예전의 list→array·cumsum 제거)."""
        if self._gb_n<1: return                            # 게이팅 블록 1개(=400ms) 미만이면 보류
        gb=self._gb[:self._gb_n]
        abs_gate=10**((-70+0.691)/10)
        gated=gb[gb>abs_gate]                              # 절대 게이트 −70 LUFS
        if gated.size==0: return
        ms_g=float(gated.mean())
        rel_gate=10**((self._lufs(ms_g)-10+0.691)/10)      # 상대 게이트 −10 LU
        # 규격은 두 게이트의 **AND**(l_j > Γa AND l_j > Γr) — 절대게이트를 빠뜨리면
        # 게이팅 평균이 −70에 가까울 때 Γr < Γa 가 되어 −70 이하 블록이 다시 섞인다
        # (실측: −68 LUFS 프로그램 −0.84 LU, 랜덤 최악 −5.3 LU).
        g2=gb[(gb>abs_gate)&(gb>rel_gate)]
        if g2.size>0: self._I=self._lufs(float(g2.mean()))

    def _compute_LRA(self):
        """EBU Tech 3342: 프로그램 전체 short-term 분포 → 절대게이트(−70, 적재 시 적용) +
        상대게이트(절대게이트 평균 −20 LU) → 10~95 백분위 차이.
        분포는 0.01 LU 히스토그램이라 백분위가 O(bins) 상수시간(예전 np.percentile은 O(n log n))."""
        h=self._lra_hist
        tot=int(h.sum())
        if tot<4: return
        # 절대게이트 분포의 평균 라우드니스(평균제곱 평균 → LUFS)
        mean_lufs=self._lufs(float((h*self._LRA_MS).sum()/tot))
        rel=mean_lufs-20.0                                  # 상대 게이트(−20 LU)
        sel=self._LRA_CENTERS>rel
        c=h[sel]
        n=int(c.sum())
        if n<2: return
        centers=self._LRA_CENTERS[sel]
        cum=np.cumsum(c)
        # 히스토그램 백분위 — 누적분포가 목표 비율을 넘는 첫 bin의 중앙값(오차 ≤ 반 bin = 0.005 LU)
        p10=float(centers[int(np.searchsorted(cum, 0.10*n, side='left'))])
        i95=int(np.searchsorted(cum, 0.95*n, side='left'))
        if i95>=centers.size: i95=centers.size-1
        p95=float(centers[i95])
        self._LRA=float(max(0.0, p95-p10))

    def start_integration(self):
        self._gb=np.empty(4096,dtype=np.float64); self._gb_n=0; self._sub4.clear()
        self._int_on=True; self._I=-100.0
        self._lra_hist[:]=0; self._LRA=0.0; self._maxM=-100.0; self._maxS=-100.0
        self._TP=-100.0; self._PH=-100.0   # 새 프로그램 적분 → 트루피크도 리셋(PLR/PSR·표시 피크가 stale 안 되게)

    def stop_integration(self): self._int_on=False

    def reset(self):
        self._kfl.reset(); self._kfr.reset()
        self._sq_hist.clear(); self._fast_hist.clear()
        self._gb=np.empty(4096,dtype=np.float64); self._gb_n=0; self._sub4.clear()
        self._acc_l=0.0; self._acc_r=0.0; self._acc_n=0
        self._M=-100.0; self._S=-100.0; self._S_fast=-100.0
        self._I=-100.0; self._LRA=0.0; self._TP=-100.0; self._PH=-100.0
        self._tp_tail_l=None; self._tp_tail_r=None
        self._lra_hist[:]=0; self._maxM=-100.0; self._maxS=-100.0

    def reset_peak(self):
        """표시 피크(peak-hold) 리셋.

        ⚠️ `_TP`는 지우지 않는다. PLR = TP − I 는 **프로그램 단위** 지표라 TP와 I의
        시간창이 같아야 한다. _TP만 리셋하면 창이 어긋나 PLR이 **음수**가 되는데,
        이는 물리적으로 불가능한 값이다(실측: 리셋 직후 −9.76 LU, 정상 복귀까지 31초,
        최악 −29.7 LU 오차). 화면의 TP 표시는 `_PH`를 쓰므로 UX 의도는 그대로 달성된다.
        TP·I 창을 함께 되돌리려면 start_integration()으로 적분 자체를 재시작할 것."""
        self._PH=-100.0

    @property
    def M(self): return self._M
    @property
    def S(self): return self._S
    @property
    def S_fast(self): return self._S_fast
    @property
    def I(self): return self._I
    @property
    def LRA(self): return self._LRA
    @property
    def TP(self): return self._TP
    @property
    def peak_hold(self): return self._PH
    @property
    def MaxM(self): return self._maxM
    @property
    def MaxS(self): return self._maxS
    @property
    def PLR(self):   # Peak-to-Loudness Ratio (TruePeak − Integrated)
        return (self._TP - self._I) if self._I > -100.0 else 0.0
    @property
    def PSR(self):   # Peak-to-Short-term Ratio (TruePeak − Short-term)
        return (self._TP - self._S) if self._S > -100.0 else 0.0
