"""Loudness (ITU-R BS.1770-4) — 순수 DSP.

v2.0 분해: wayaudo2.py에서 _biquad/_KWeightFilter/LoudnessMeter 이동(동작 0 변경).
골든: tests/test_dsp_golden.py::test_loudness_1khz_tone / test_biquad_impulse / test_kweight_coefficients_48k.
"""
import math
import numpy as np
from collections import deque


def _biquad(x, b, a, z):
    """Transposed direct form II biquad — stateful via z[0..1]."""
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
    """ITU-R BS.1770-4 기반 LUFS / LRA / TruePeak 미터."""
    _BLK_MS=100  # 100ms 블록

    def __init__(self,sr):
        self.sr=sr
        self._kfl=_KWeightFilter(sr); self._kfr=_KWeightFilter(sr)
        self._blk=max(1,sr*self._BLK_MS//1000)
        self._sq_hist=deque(maxlen=30)   # 3초 = 30블록 (short-term)
        self._fast_hist=deque(maxlen=5)  # 0.5초 = 5블록 (레이더용)
        self._int_sq=[]; self._int_on=False
        self._acc_l=0.0; self._acc_r=0.0; self._acc_n=0
        self._M=-100.0; self._S=-100.0; self._S_fast=-100.0
        self._I=-100.0; self._LRA=0.0; self._TP=-100.0; self._PH=-100.0
        self._tp_tail_l=None; self._tp_tail_r=None   # True Peak 4× 오버샘플 연속성 테일
        self._lra_st=[]                # EBU 3342 LRA: 프로그램 전체 short-term(3s) 값 누적
        self._maxM=-100.0; self._maxS=-100.0   # Max Momentary / Max Short-term

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
                if self._int_on: self._int_sq.append(ms)
                # EBU 3342: full 3s short-term 값을 프로그램 전체에 누적 (블록당 1회)
                if self._int_on and len(self._sq_hist)>=30:
                    self._lra_st.append(self._lufs(float(np.mean(self._sq_hist))))
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
        # BS.1770-4 게이팅: 400ms 블록 · 75% 오버랩(100ms마다 한 블록). _int_sq는 100ms 부분블록의
        # 평균제곱 → 연속 4개(=400ms)를 평균하고 1개(100ms)씩 슬라이드해 규격 게이팅 블록을 만든다.
        # (예전엔 100ms 블록을 그대로 게이팅 → 변동이 커 상대게이트가 다른 블록집합을 남겨 ~0.5 LU 오차.)
        if len(self._int_sq)<4: return                    # 400ms(=게이팅 블록 1개) 미만이면 보류
        arr=np.asarray(self._int_sq, dtype=np.float64)
        csum=np.concatenate(([0.0], np.cumsum(arr)))
        gb=(csum[4:]-csum[:-4])/4.0                        # 각 400ms 게이팅 블록의 평균제곱(겹침 슬라이딩)
        abs_gate=10**((-70+0.691)/10)
        gated=gb[gb>abs_gate]                              # 절대 게이트 −70 LUFS
        if len(gated)==0: return
        ms_g=float(np.mean(gated))
        rel_gate=10**((self._lufs(ms_g)-10+0.691)/10)      # 상대 게이트 −10 LU
        g2=gb[gb>rel_gate]
        if len(g2)>0: self._I=self._lufs(float(np.mean(g2)))

    def _compute_LRA(self):
        """EBU Tech 3342: 프로그램 전체 short-term 분포 → 절대게이트(-70) +
        상대게이트(절대게이트 평균 -20 LU) → 10~95 백분위 차이."""
        if len(self._lra_st)<4: return
        arr=np.array(self._lra_st)
        arr=arr[arr>-70.0]                       # 절대 게이트
        if len(arr)<4: return
        ms=10**((arr+0.691)/10.0)                # LUFS→평균제곱 환산
        mean_lufs=self._lufs(float(np.mean(ms))) # 절대게이트 분포의 평균 라우드니스
        rel=mean_lufs-20.0                        # 상대 게이트(-20 LU)
        g=arr[arr>rel]
        if len(g)<2: return
        self._LRA=float(max(0.0,np.percentile(g,95)-np.percentile(g,10)))

    def start_integration(self):
        self._int_sq=[]; self._int_on=True; self._I=-100.0
        self._lra_st=[]; self._LRA=0.0; self._maxM=-100.0; self._maxS=-100.0
        self._TP=-100.0; self._PH=-100.0   # 새 프로그램 적분 → 트루피크도 리셋(PLR/PSR·표시 피크가 stale 안 되게)

    def stop_integration(self): self._int_on=False

    def reset(self):
        self._kfl.reset(); self._kfr.reset()
        self._sq_hist.clear(); self._fast_hist.clear(); self._int_sq=[]
        self._acc_l=0.0; self._acc_r=0.0; self._acc_n=0
        self._M=-100.0; self._S=-100.0; self._S_fast=-100.0
        self._I=-100.0; self._LRA=0.0; self._TP=-100.0; self._PH=-100.0
        self._tp_tail_l=None; self._tp_tail_r=None
        self._lra_st=[]; self._maxM=-100.0; self._maxS=-100.0

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
