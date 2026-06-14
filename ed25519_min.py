# ─────────────────────────────────────────────────────────────
# 순수 파이썬 Ed25519 (RFC 8032 참조 구현) — 외부 의존성 0
# 라이선스 서명/검증 공용. 앱은 verify+공개키만, 생성기는 sign+개인키.
# (느리지만 시작 시 1회 검증이라 무방: verify ~0.25s)
# ⚠️ 알고리즘은 공개. 보안은 '개인키(seed)를 배포 안 함'에서 나옴.
# ─────────────────────────────────────────────────────────────
import hashlib

_q = 2**255 - 19
_l = 2**252 + 27742317777372353535851937790883648493

def _sha512(s): return hashlib.sha512(s).digest()
def _inv(x): return pow(x, _q - 2, _q)
_d = -121665 * _inv(121666) % _q
_I = pow(2, (_q - 1) // 4, _q)

def _xrecover(y):
    xx = (y * y - 1) * _inv(_d * y * y + 1)
    x = pow(xx, (_q + 3) // 8, _q)
    if (x * x - xx) % _q != 0: x = (x * _I) % _q
    if x % 2 != 0: x = _q - x
    return x

_By = 4 * _inv(5) % _q
_Bx = _xrecover(_By)
_B = [_Bx % _q, _By % _q]

def _edwards(P, Q):
    x1, y1 = P; x2, y2 = Q
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + _d * x1 * x2 * y1 * y2)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - _d * x1 * x2 * y1 * y2)
    return [x3 % _q, y3 % _q]

def _scalarmult(P, e):
    if e == 0: return [0, 1]
    Q = _scalarmult(P, e // 2); Q = _edwards(Q, Q)
    if e & 1: Q = _edwards(Q, P)
    return Q

def _encodeint(y):
    b = [(y >> i) & 1 for i in range(256)]
    return bytes(sum(b[i * 8 + j] << j for j in range(8)) for i in range(32))

def _encodepoint(P):
    x, y = P
    b = [(y >> i) & 1 for i in range(255)] + [x & 1]
    return bytes(sum(b[i * 8 + j] << j for j in range(8)) for i in range(32))

def _bit(h, i): return (h[i // 8] >> (i % 8)) & 1

def public_key(seed):
    """32바이트 seed(개인키) → 32바이트 공개키."""
    h = _sha512(seed)
    a = 2**254 + sum(2**i * _bit(h, i) for i in range(3, 254))
    return _encodepoint(_scalarmult(_B, a))

def _Hint(m):
    h = _sha512(m); return sum(2**i * _bit(h, i) for i in range(512))

def sign(msg, seed, pub):
    """msg(bytes), seed(32B 개인키), pub(32B 공개키) → 64바이트 서명."""
    h = _sha512(seed)
    a = 2**254 + sum(2**i * _bit(h, i) for i in range(3, 254))
    r = _Hint(h[32:64] + msg)
    R = _scalarmult(_B, r)
    S = (r + _Hint(_encodepoint(R) + pub + msg) * a) % _l
    return _encodepoint(R) + _encodeint(S)

def _decodeint(s): return sum(2**i * _bit(s, i) for i in range(256))
def _isoncurve(P):
    x, y = P
    return (-x * x + y * y - 1 - _d * x * x * y * y) % _q == 0
def _decodepoint(s):
    y = sum(2**i * _bit(s, i) for i in range(255))
    x = _xrecover(y)
    if x & 1 != _bit(s, 255): x = _q - x
    P = [x, y]
    if not _isoncurve(P): raise Exception('decode point error')
    return P

def verify(sig, msg, pub):
    """서명 검증 → True/False. (예외 안 던짐)"""
    try:
        if len(sig) != 64 or len(pub) != 32: return False
        R = _decodepoint(sig[:32]); A = _decodepoint(pub); S = _decodeint(sig[32:64])
        return _scalarmult(_B, S) == _edwards(R, _scalarmult(A, _Hint(_encodepoint(R) + pub + msg)))
    except Exception:
        return False
