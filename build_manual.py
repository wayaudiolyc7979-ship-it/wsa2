#!/usr/bin/env python3
"""WSA2 사용자 매뉴얼 PDF 생성 스크립트"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus.flowables import Flowable
import os

# ── 폰트 등록 ────────────────────────────────────────────────────────────────
FONT_PATH = '/System/Library/Fonts/Supplemental/AppleGothic.ttf'
pdfmetrics.registerFont(TTFont('KO', FONT_PATH))
pdfmetrics.registerFont(TTFont('KO-Bold', FONT_PATH))   # bold fallback

# ── 색상 팔레트 ──────────────────────────────────────────────────────────────
C_TEAL     = HexColor('#00d4aa')
C_ORANGE   = HexColor('#ff6b35')
C_BG_DARK  = HexColor('#0d1117')
C_BG_MID   = HexColor('#161b22')
C_BG_LIGHT = HexColor('#21262d')
C_TEXT     = HexColor('#e6edf3')
C_DIM      = HexColor('#8b949e')
C_WHITE    = white
C_RED      = HexColor('#ff4d4d')
C_YELLOW   = HexColor('#ffd700')
C_GREEN    = HexColor('#39d353')
C_BLUE     = HexColor('#58a6ff')
C_SECTION  = HexColor('#1a2332')
C_TIP_BG   = HexColor('#0d2818')
C_TIP_BD   = HexColor('#1a5c35')
C_WARN_BG  = HexColor('#2d1a00')
C_WARN_BD  = HexColor('#c65700')
C_NOTE_BG  = HexColor('#0c1f35')
C_NOTE_BD  = HexColor('#1a4a7a')

W, H = A4

# ── 스타일 정의 ──────────────────────────────────────────────────────────────
def make_styles():
    s = {}
    base = dict(fontName='KO', leading=16, spaceAfter=4)

    s['cover_title']   = ParagraphStyle('cover_title',   fontName='KO', fontSize=36,
                                         textColor=C_TEAL,   leading=44, spaceAfter=8,  alignment=TA_CENTER)
    s['cover_sub']     = ParagraphStyle('cover_sub',     fontName='KO', fontSize=18,
                                         textColor=C_TEXT,   leading=24, spaceAfter=6,  alignment=TA_CENTER)
    s['cover_ver']     = ParagraphStyle('cover_ver',     fontName='KO', fontSize=13,
                                         textColor=C_DIM,    leading=18, spaceAfter=4,  alignment=TA_CENTER)

    s['h1']  = ParagraphStyle('h1',  fontName='KO', fontSize=20, textColor=C_TEAL,
                                leading=26, spaceBefore=18, spaceAfter=8)
    s['h2']  = ParagraphStyle('h2',  fontName='KO', fontSize=15, textColor=C_WHITE,
                                leading=20, spaceBefore=14, spaceAfter=6)
    s['h3']  = ParagraphStyle('h3',  fontName='KO', fontSize=12, textColor=C_TEAL,
                                leading=16, spaceBefore=10, spaceAfter=4)

    s['body']  = ParagraphStyle('body',  fontName='KO', fontSize=10, textColor=C_TEXT,
                                  leading=17, spaceAfter=5, alignment=TA_JUSTIFY)
    s['body_b']= ParagraphStyle('body_b',fontName='KO', fontSize=10, textColor=C_WHITE,
                                  leading=17, spaceAfter=5)
    s['small'] = ParagraphStyle('small', fontName='KO', fontSize=9,  textColor=C_DIM,
                                  leading=14, spaceAfter=3)

    s['step']  = ParagraphStyle('step',  fontName='KO', fontSize=10, textColor=C_TEXT,
                                  leading=17, spaceAfter=4, leftIndent=16, firstLineIndent=-16)
    s['bullet']= ParagraphStyle('bullet',fontName='KO', fontSize=10, textColor=C_TEXT,
                                  leading=16, spaceAfter=3, leftIndent=14, firstLineIndent=-10)

    s['tip_title']  = ParagraphStyle('tip_title',  fontName='KO', fontSize=10,
                                      textColor=C_GREEN,   leading=15, spaceAfter=3)
    s['tip_body']   = ParagraphStyle('tip_body',   fontName='KO', fontSize=10,
                                      textColor=C_TEXT,    leading=15, spaceAfter=2)
    s['warn_title'] = ParagraphStyle('warn_title', fontName='KO', fontSize=10,
                                      textColor=C_ORANGE,  leading=15, spaceAfter=3)
    s['warn_body']  = ParagraphStyle('warn_body',  fontName='KO', fontSize=10,
                                      textColor=C_TEXT,    leading=15, spaceAfter=2)
    s['note_title'] = ParagraphStyle('note_title', fontName='KO', fontSize=10,
                                      textColor=C_BLUE,    leading=15, spaceAfter=3)
    s['note_body']  = ParagraphStyle('note_body',  fontName='KO', fontSize=10,
                                      textColor=C_TEXT,    leading=15, spaceAfter=2)

    s['toc_item']  = ParagraphStyle('toc_item',  fontName='KO', fontSize=10,
                                     textColor=C_TEXT,  leading=18, spaceAfter=2)
    s['toc_sub']   = ParagraphStyle('toc_sub',   fontName='KO', fontSize=9,
                                     textColor=C_DIM,   leading=15, spaceAfter=1, leftIndent=16)
    s['kbd']       = ParagraphStyle('kbd',       fontName='Courier', fontSize=9,
                                     textColor=C_TEAL,  leading=13)
    s['center']    = ParagraphStyle('center',    fontName='KO', fontSize=10,
                                     textColor=C_DIM,   leading=14, alignment=TA_CENTER)
    return s

S = make_styles()

# ── 헬퍼 위젯 ────────────────────────────────────────────────────────────────
def tip_box(title, *lines):
    rows = [[Paragraph(f'✅  {title}', S['tip_title'])]]
    for l in lines: rows.append([Paragraph(l, S['tip_body'])])
    t = Table(rows, colWidths=[150*mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), C_TIP_BG),
        ('BOX', (0,0), (-1,-1), 1, C_TIP_BD),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (0,0), 8),
        ('BOTTOMPADDING', (0,-1), (0,-1), 8),
        ('TOPPADDING', (0,1), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-2), 2),
        ('ROUNDEDCORNERS', [4,4,4,4]),
    ]))
    return t

def warn_box(title, *lines):
    rows = [[Paragraph(f'⚠️  {title}', S['warn_title'])]]
    for l in lines: rows.append([Paragraph(l, S['warn_body'])])
    t = Table(rows, colWidths=[150*mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), C_WARN_BG),
        ('BOX', (0,0), (-1,-1), 1, C_WARN_BD),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (0,0), 8),
        ('BOTTOMPADDING', (0,-1), (0,-1), 8),
        ('TOPPADDING', (0,1), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-2), 2),
    ]))
    return t

def note_box(title, *lines):
    rows = [[Paragraph(f'ℹ️  {title}', S['note_title'])]]
    for l in lines: rows.append([Paragraph(l, S['note_body'])])
    t = Table(rows, colWidths=[150*mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), C_NOTE_BG),
        ('BOX', (0,0), (-1,-1), 1, C_NOTE_BD),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (0,0), 8),
        ('BOTTOMPADDING', (0,-1), (0,-1), 8),
        ('TOPPADDING', (0,1), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-2), 2),
    ]))
    return t

def section_header(num, title):
    bar = Table([[Paragraph(f'{num}.  {title}', S['h1'])]],
                colWidths=[150*mm])
    bar.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), C_SECTION),
        ('LEFTPADDING', (0,0), (-1,-1), 12),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('BOX', (0,0), (-1,-1), 0, C_SECTION),
        ('LINEBELOW', (0,0), (-1,-1), 2, C_TEAL),
    ]))
    return bar

def kbd(*keys):
    return '  '.join(f'[{k}]' for k in keys)

def tbl(headers, rows, col_w=None):
    all_rows = [[Paragraph(h, ParagraphStyle('th', fontName='KO', fontSize=9,
                textColor=C_TEAL, leading=13)) for h in headers]] + \
               [[Paragraph(str(c), ParagraphStyle('td', fontName='KO', fontSize=9,
                textColor=C_TEXT, leading=14)) for c in row] for row in rows]
    if col_w is None:
        col_w = [150*mm / len(headers)] * len(headers)
    t = Table(all_rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_BG_LIGHT),
        ('BACKGROUND', (0,1), (-1,-1), C_BG_MID),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [C_BG_MID, HexColor('#1a1f27')]),
        ('BOX', (0,0), (-1,-1), 0.5, HexColor('#30363d')),
        ('LINEBELOW', (0,0), (-1,0), 1, C_TEAL),
        ('INNERGRID', (0,0), (-1,-1), 0.3, HexColor('#30363d')),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    return t

def hr(): return HRFlowable(width='100%', thickness=0.5, color=HexColor('#30363d'), spaceAfter=6)

def sp(h=4): return Spacer(1, h*mm)

def p(text, style='body'): return Paragraph(text, S[style])

def step(n, text): return Paragraph(f'<b>{n}.</b>  {text}', S['step'])

def bullet(text): return Paragraph(f'• {text}', S['bullet'])


# ── 페이지 배경/헤더/푸터 콜백 ────────────────────────────────────────────────
def page_background(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(C_BG_DARK)
    canvas.rect(0, 0, W, H, fill=1, stroke=0)

    # 헤더 바 (표지 제외)
    if doc.page > 1:
        canvas.setFillColor(C_BG_MID)
        canvas.rect(0, H - 18*mm, W, 18*mm, fill=1, stroke=0)
        canvas.setFillColor(C_TEAL)
        canvas.rect(0, H - 18*mm, W, 0.8*mm, fill=1, stroke=0)
        canvas.setFont('KO', 9)
        canvas.setFillColor(C_DIM)
        canvas.drawString(20*mm, H - 12*mm, 'WAYAUDIO Spectrum Analyzer 2  —  사용자 매뉴얼')
        canvas.drawRightString(W - 20*mm, H - 12*mm, f'v2.1')

    # 푸터 (표지 제외)
    if doc.page > 1:
        canvas.setFillColor(C_BG_MID)
        canvas.rect(0, 0, W, 12*mm, fill=1, stroke=0)
        canvas.setFillColor(C_TEAL)
        canvas.rect(0, 12*mm, W, 0.5*mm, fill=1, stroke=0)
        canvas.setFont('KO', 9)
        canvas.setFillColor(C_DIM)
        canvas.drawCentredString(W/2, 4*mm, f'{doc.page}')
        canvas.drawString(20*mm, 4*mm, '© WAYAUDIO')
        canvas.drawRightString(W - 20*mm, 4*mm, 'wayaudio.com')

    canvas.restoreState()

def cover_background(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(C_BG_DARK)
    canvas.rect(0, 0, W, H, fill=1, stroke=0)
    # 상단 장식 바
    canvas.setFillColor(C_TEAL)
    canvas.rect(0, H - 4*mm, W, 4*mm, fill=1, stroke=0)
    # 하단 장식 바
    canvas.setFillColor(HexColor('#0a3d30'))
    canvas.rect(0, 0, W, 30*mm, fill=1, stroke=0)
    canvas.setFillColor(C_TEAL)
    canvas.rect(0, 30*mm, W, 0.8*mm, fill=1, stroke=0)
    canvas.restoreState()


# ─────────────────────────────────────────────────────────────────────────────
#  콘텐츠 빌드
# ─────────────────────────────────────────────────────────────────────────────
def build_story():
    story = []

    # ══════════════════════════════════════════════════════
    #  표지
    # ══════════════════════════════════════════════════════
    story += [sp(30)]
    story += [p('WAYAUDIO', 'cover_title')]
    story += [p('Spectrum Analyzer 2', 'cover_sub')]
    story += [sp(4)]
    story += [p('사용자 매뉴얼  v2.1', 'cover_ver')]
    story += [sp(8)]
    story += [HRFlowable(width='60%', thickness=1, color=C_TEAL, hAlign='CENTER', spaceAfter=8)]
    story += [sp(8)]

    intro_tbl = Table([[
        Paragraph('음향 측정 · 스펙트럼 분석 · 전달함수 측정을 위한\n전문가용 소프트웨어',
                  ParagraphStyle('ci', fontName='KO', fontSize=13, textColor=C_DIM,
                                 leading=20, alignment=TA_CENTER))
    ]], colWidths=[140*mm])
    intro_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), HexColor('#0a1a14')),
        ('BOX', (0,0), (-1,-1), 1, HexColor('#1a5c35')),
        ('LEFTPADDING', (0,0), (-1,-1), 20),
        ('RIGHTPADDING', (0,0), (-1,-1), 20),
        ('TOPPADDING', (0,0), (-1,-1), 16),
        ('BOTTOMPADDING', (0,0), (-1,-1), 16),
    ]))
    story += [intro_tbl]
    story += [sp(60)]
    story += [p('이 매뉴얼을 처음 읽는 분도 처음부터 차례대로 따라하면\n누구나 WSA2를 바로 사용할 수 있습니다.',
               'center')]
    story += [PageBreak()]

    # ══════════════════════════════════════════════════════
    #  목차
    # ══════════════════════════════════════════════════════
    story += [sp(8)]
    story += [p('목  차', 'h1')]
    story += [hr()]
    story += [sp(4)]

    toc_data = [
        ('1', '시스템 요구사항', ''),
        ('2', '설치 방법', ''),
        ('', '2-1  Apple Silicon (M1~M5) Mac 설치', ''),
        ('', '2-2  Intel Mac 설치', ''),
        ('3', '라이선스 활성화', ''),
        ('4', '화면 구성 한눈에 보기', ''),
        ('5', '시작하기 — 기기 연결 & 첫 실행', ''),
        ('6', '인풋 레벨 모니터 (Input Levels)', ''),
        ('7', '시그널 제네레이터 (Signal Generator)', ''),
        ('', '7-1  핑크 노이즈 / 화이트 노이즈', ''),
        ('', '7-2  오디오 파일 재생', ''),
        ('8', '스펙트럼 분석 — FFT', ''),
        ('9', '스펙트럼 분석 — 옥타브 (Octave)', ''),
        ('10', '스펙트로그램 (Spectrogram)', ''),
        ('11', '캡처 기능', ''),
        ('12', '전달함수 측정 (Transfer Function)', ''),
        ('', '12-1  Magnitude (크기 응답)', ''),
        ('', '12-2  Phase (위상 응답)', ''),
        ('', '12-3  Impulse Response (임펄스 응답)', ''),
        ('', '12-4  딜레이 파인더 (Delay Finder)', ''),
        ('13', 'SPL 미터', ''),
        ('14', 'LEQ 시간 평균 측정', ''),
        ('15', '키보드 단축키 모음', ''),
        ('16', '문제 해결 (Troubleshooting)', ''),
        ('17', '로그 파일 & 버그 신고', ''),
    ]
    for num, title, _ in toc_data:
        if num:
            story += [p(f'<b>{num}.</b>  {title}', 'toc_item')]
        else:
            story += [p(f'     {title}', 'toc_sub')]
    story += [PageBreak()]

    # ══════════════════════════════════════════════════════
    #  1. 시스템 요구사항
    # ══════════════════════════════════════════════════════
    story += [section_header('1', '시스템 요구사항'), sp(4)]
    story += [tbl(
        ['항목', '최소 사양', '권장 사양'],
        [
            ['운영체제', 'macOS 12 Monterey', 'macOS 14 Sonoma 이상'],
            ['프로세서', 'Apple M1 / Intel Core i5', 'Apple M2 이상'],
            ['메모리', '4 GB RAM', '8 GB RAM 이상'],
            ['저장 공간', '300 MB 이상 여유', '500 MB 이상 여유'],
            ['오디오 인터페이스', 'Mac 내장 마이크 가능', 'USB 외장 오디오 인터페이스 권장'],
            ['화면 해상도', '1280 × 800', '1440 × 900 이상 (Retina 지원)'],
        ],
        col_w=[38*mm, 55*mm, 57*mm]
    ), sp(6)]
    story += [note_box('Apple Silicon 전용 버전 안내',
        'WSA2_AppleSilicon.dmg 는 M1 · M2 · M3 · M4 · M5 칩이 탑재된 Mac 전용입니다.',
        'Intel 프로세서 Mac은 반드시 WSA2_Intel.dmg 를 사용하세요.',
        '어떤 칩인지 모르면: 화면 왼쪽 위 Apple 메뉴 → 이 Mac에 관하여 → "칩" 항목 확인')]
    story += [sp(4)]

    # ══════════════════════════════════════════════════════
    #  2. 설치 방법
    # ══════════════════════════════════════════════════════
    story += [section_header('2', '설치 방법'), sp(4)]
    story += [p('2-1  Apple Silicon Mac (M1 ~ M5)', 'h2'), sp(2)]
    story += [step(1, 'WSA2_AppleSilicon.dmg 파일을 더블클릭합니다.')]
    story += [step(2, '창이 열리면 WSA2.app 아이콘을 오른쪽 Applications 폴더로 드래그합니다.')]
    story += [step(3, 'Finder에서 응용 프로그램 폴더를 열고 WSA2를 실행합니다.')]
    story += [step(4, '처음 실행 시 "알 수 없는 개발자" 경고가 나올 수 있습니다.\n'
                      '   → Control(⌃) + 클릭 → "열기" 선택 → 다시 "열기" 클릭')]
    story += [sp(3)]
    story += [tip_box('한 번만 허용하면 됩니다',
        '처음 한 번만 위 과정을 거치면, 이후에는 일반 앱처럼 바로 실행됩니다.',
        'Dock에 고정하거나 Spotlight(⌘+Space)에서 "WSA2"로 검색해도 됩니다.')]
    story += [sp(6)]

    story += [p('2-2  Intel Mac', 'h2'), sp(2)]
    story += [step(1, 'WSA2_Intel.dmg 파일을 더블클릭합니다.')]
    story += [step(2, 'WSA2_Intel.app 을 Applications 폴더로 드래그합니다.')]
    story += [step(3, 'Apple Silicon 과 동일하게 첫 실행 시 Control + 클릭 → "열기"')]
    story += [sp(3)]
    story += [warn_box('Intel 전용 파일 사용 주의',
        'Apple Silicon Mac에서 WSA2_Intel.dmg를 설치하면 Rosetta 변환 과정으로',
        '성능이 저하되고 오디오 레이턴시가 증가할 수 있습니다.',
        '반드시 본인 Mac에 맞는 버전을 사용하세요.')]
    story += [PageBreak()]

    # ══════════════════════════════════════════════════════
    #  3. 라이선스 활성화
    # ══════════════════════════════════════════════════════
    story += [section_header('3', '라이선스 활성화'), sp(4)]
    story += [p('WSA2는 첫 실행 시 라이선스 활성화가 필요합니다. 한 번 활성화하면 이후에는 자동으로 인식됩니다.', 'body')]
    story += [sp(4)]
    story += [p('활성화 순서', 'h2'), sp(2)]
    story += [step(1, '앱을 실행하면 아래와 같은 라이선스 창이 나타납니다.')]
    story += [sp(2)]

    lic_box = Table([[
        Table([
            [Paragraph('WAYAUDIO Spectrum Analyzer 2', ParagraphStyle('lt', fontName='KO', fontSize=11, textColor=C_TEAL, leading=16))],
            [Paragraph('이 컴퓨터의 머신 ID (개발자에게 전달):', ParagraphStyle('ls', fontName='KO', fontSize=9, textColor=C_DIM, leading=13))],
            [Paragraph('8BDFC136A562', ParagraphStyle('lm', fontName='Courier', fontSize=14, textColor=C_WHITE, leading=18))],
            [Paragraph('시리얼 키 입력:', ParagraphStyle('lk', fontName='KO', fontSize=9, textColor=C_DIM, leading=13))],
            [Paragraph('XXXXX-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX-XXXX', ParagraphStyle('li', fontName='Courier', fontSize=9, textColor=C_DIM, leading=13))],
        ], colWidths=[110*mm],
           style=[('BACKGROUND',(0,0),(-1,-1),C_BG_MID),
                  ('LEFTPADDING',(0,0),(-1,-1),10), ('TOPPADDING',(0,0),(-1,-1),4),
                  ('BOTTOMPADDING',(0,0),(-1,-1),4)])
    ]], colWidths=[116*mm])
    lic_box.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),C_BG_MID),
        ('BOX',(0,0),(-1,-1),1,HexColor('#30363d')),
        ('LEFTPADDING',(0,0),(-1,-1),6),
        ('RIGHTPADDING',(0,0),(-1,-1),6),
        ('TOPPADDING',(0,0),(-1,-1),6),
        ('BOTTOMPADDING',(0,0),(-1,-1),6),
    ]))
    story += [lic_box, sp(4)]

    story += [step(2, '"머신 ID 복사" 버튼을 클릭해서 ID를 복사합니다. (예: 8BDFC136A562)')]
    story += [step(3, '복사한 머신 ID를 개발자(소프트웨어 공급처)에게 전달합니다.\n'
                      '   (이메일, 카카오톡 등 어떤 방법이든 됩니다.)')]
    story += [step(4, '개발자가 보내준 시리얼 키를 "시리얼 키 입력" 필드에 붙여넣기 합니다.')]
    story += [step(5, '"활성화" 버튼을 누르면 "활성화 성공!" 메시지가 나타납니다.')]
    story += [step(6, '창이 자동으로 닫히고 프로그램이 정상 실행됩니다.')]
    story += [sp(4)]
    story += [note_box('라이선스는 이 Mac에만 유효합니다',
        '시리얼 키는 활성화한 컴퓨터에서만 작동합니다.',
        '다른 컴퓨터로 이전할 경우 새로운 시리얼 키가 필요합니다.',
        '라이선스 정보는 우측 패널 하단 "License" 버튼에서 확인할 수 있습니다.')]
    story += [PageBreak()]

    # ══════════════════════════════════════════════════════
    #  4. 화면 구성
    # ══════════════════════════════════════════════════════
    story += [section_header('4', '화면 구성 한눈에 보기'), sp(4)]
    story += [p('WSA2의 메인 화면은 크게 세 영역으로 나뉩니다.', 'body')]
    story += [sp(4)]

    layout_tbl = Table([
        [Paragraph('영역', ParagraphStyle('th2', fontName='KO', fontSize=10, textColor=C_TEAL, leading=14)),
         Paragraph('위치', ParagraphStyle('th2', fontName='KO', fontSize=10, textColor=C_TEAL, leading=14)),
         Paragraph('주요 기능', ParagraphStyle('th2', fontName='KO', fontSize=10, textColor=C_TEAL, leading=14))],
        [Paragraph('그래프 영역', S['body_b']),
         Paragraph('화면 중앙', S['body']),
         Paragraph('FFT / Octave / Spectrogram 분석 그래프 표시', S['body'])],
        [Paragraph('컨트롤 패널', S['body_b']),
         Paragraph('우측', S['body']),
         Paragraph('Signal Generator, 입력 장치 설정, 인풋 레벨 미터', S['body'])],
        [Paragraph('레벨 패널', S['body_b']),
         Paragraph('우측 상단', S['body']),
         Paragraph('dBFS, dBA, dBC, LAeq 실시간 표시', S['body'])],
        [Paragraph('캡처 드로어', S['body_b']),
         Paragraph('그래프 우측', S['body']),
         Paragraph('저장된 캡처 목록 / 색상 / 삭제', S['body'])],
    ], colWidths=[35*mm, 30*mm, 85*mm])
    layout_tbl.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0), C_BG_LIGHT),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[C_BG_MID, HexColor('#1a1f27')]),
        ('BOX',(0,0),(-1,-1),0.5,HexColor('#30363d')),
        ('LINEBELOW',(0,0),(-1,0),1,C_TEAL),
        ('INNERGRID',(0,0),(-1,-1),0.3,HexColor('#30363d')),
        ('LEFTPADDING',(0,0),(-1,-1),8), ('RIGHTPADDING',(0,0),(-1,-1),8),
        ('TOPPADDING',(0,0),(-1,-1),6),  ('BOTTOMPADDING',(0,0),(-1,-1),6),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
    ]))
    story += [layout_tbl, sp(6)]

    story += [p('화면 상단 탭 버튼', 'h2'), sp(2)]
    story += [tbl(
        ['버튼', '기능'],
        [
            ['FFT', '주파수별 실시간 스펙트럼 (선형 곡선)'],
            ['1/3 Oct', '1/3 옥타브 밴드 막대 그래프'],
            ['1/12 Oct', '1/12 옥타브 밴드 (더 세밀한 분해능)'],
            ['1/24 Oct', '1/24 옥타브 밴드 (가장 세밀)'],
            ['Spectro', '시간-주파수 스펙트로그램 (폭포수 그래프)'],
        ],
        col_w=[30*mm, 120*mm]
    ), sp(4)]
    story += [PageBreak()]

    # ══════════════════════════════════════════════════════
    #  5. 시작하기
    # ══════════════════════════════════════════════════════
    story += [section_header('5', '시작하기 — 기기 연결 & 첫 실행'), sp(4)]
    story += [p('처음 사용하는 분을 위한 가장 기본적인 설정 방법입니다.', 'body'), sp(4)]

    story += [p('기본 설정 순서', 'h2'), sp(2)]
    story += [step(1, 'USB 오디오 인터페이스나 마이크를 Mac에 연결합니다.')]
    story += [step(2, 'WSA2를 실행합니다.')]
    story += [step(3, '우측 패널 아래쪽 "Input Devices" 영역에서 기기를 선택합니다.')]
    story += [sp(2)]
    story += [tbl(
        ['설정 항목', '선택 방법', '설명'],
        [
            ['Reference', '드롭다운에서 장치 선택', '측정 기준 신호 입력 (스피커에서 오는 신호)\n⚡ Internal = 시그널 제네레이터 내부 루프백'],
            ['Measurement', '드롭다운에서 장치 선택', '측정하고 싶은 신호 입력 (마이크)'],
            ['Ch (채널)', 'Ch 1 / Ch 2 …', '다채널 인터페이스의 경우 사용할 채널 선택'],
        ],
        col_w=[28*mm, 38*mm, 84*mm]
    ), sp(4)]
    story += [step(4, '"Input Levels" 그룹 오른쪽 상단의 ⏻ 버튼을 클릭해서 레벨 모니터를 켭니다.')]
    story += [step(5, '소리를 내보면 레벨 미터가 움직이는 것을 확인합니다.')]
    story += [step(6, '"Start" 버튼을 눌러 실시간 분석을 시작합니다.')]
    story += [sp(4)]
    story += [tip_box('내장 마이크로 빠르게 시작하기',
        'Reference: ⚡ Internal (SigGen)  /  Measurement: MacBook Pro 마이크',
        'Signal Generator에서 ▶ Play로 핑크 노이즈를 켜고 Start를 누르면',
        '즉시 Transfer Function 측정을 시작할 수 있습니다.')]
    story += [PageBreak()]

    # ══════════════════════════════════════════════════════
    #  6. 인풋 레벨 모니터
    # ══════════════════════════════════════════════════════
    story += [section_header('6', '인풋 레벨 모니터 (Input Levels)'), sp(4)]
    story += [p('입력 장치의 레벨을 실시간으로 확인하는 기능입니다. 분석(Start)을 시작하지 않아도 독립적으로 작동합니다.', 'body')]
    story += [sp(4)]
    story += [tbl(
        ['요소', '설명'],
        [
            ['⏻ 버튼', '"Input Levels" 그룹 우측 상단. 클릭하면 레벨 모니터 ON/OFF'],
            ['Reference 미터 (왼쪽)', '기준 신호 입력 레벨 표시 (dBFS)'],
            ['Measurement 미터 (오른쪽)', '측정 신호 입력 레벨 표시 (dBFS)'],
            ['상단 그라데이션 바', '초록(낮음) → 노랑(-18dBFS 초과) → 빨강(-6dBFS 초과)'],
            ['숫자 (아래)', '현재 레벨 수치 표시 (dBFS). 피크 홀드 선도 표시됨.'],
        ],
        col_w=[45*mm, 105*mm]
    ), sp(4)]
    story += [tip_box('적정 레벨 확인',
        '소리가 입력될 때 미터가 -18 ~ -6 dBFS 구간(노란색)을 넘지 않는 것이 이상적입니다.',
        '빨간색(-6dBFS 이상)이 자주 켜지면 입력 게인을 낮추세요.',
        '미터가 전혀 움직이지 않으면: ① ⏻ 버튼이 켜져 있는지 확인 ② 장치 선택이 올바른지 확인')]
    story += [PageBreak()]

    # ══════════════════════════════════════════════════════
    #  7. 시그널 제네레이터
    # ══════════════════════════════════════════════════════
    story += [section_header('7', '시그널 제네레이터 (Signal Generator)'), sp(4)]
    story += [p('WSA2 내장 신호 발생기로, 스피커나 앰프를 통해 측정용 신호를 출력합니다.', 'body')]
    story += [sp(4)]
    story += [p('컨트롤 설명', 'h2'), sp(2)]
    story += [tbl(
        ['항목', '설명'],
        [
            ['Pink Noise (핑크 노이즈)', '가장 널리 쓰이는 측정용 신호. 음향 측정의 표준.'],
            ['White Noise (화이트 노이즈)', '모든 주파수 동일 에너지. 주로 전자 측정에 사용.'],
            ['File… (파일 재생)', '본인이 가진 WAV / AIFF 파일을 루프로 재생'],
            ['Level (레벨)', '출력 레벨 조정 (-60 ~ 0 dBFS). + / - 버튼으로 조절,\n직접 숫자를 입력 후 Enter로 즉시 적용'],
            ['Out (출력 장치)', '신호를 출력할 오디오 기기 선택'],
            ['Ch (채널)', '출력할 채널 선택 (다채널 인터페이스용)'],
            ['▶ Play  [G]', '신호 재생 시작/정지. 단축키: 키보드 G'],
        ],
        col_w=[42*mm, 108*mm]
    ), sp(4)]

    story += [p('7-1  핑크 노이즈 / 화이트 노이즈', 'h3'), sp(2)]
    story += [step(1, '"Pink Noise" 또는 "White Noise" 라디오 버튼을 선택합니다.')]
    story += [step(2, 'Level을 원하는 값으로 설정합니다. (처음에는 -20 dB 정도 권장)')]
    story += [step(3, 'Out에서 출력 기기를 선택합니다.')]
    story += [step(4, '▶ Play 버튼을 누르거나 키보드 G를 눌러 재생합니다.')]
    story += [sp(3)]

    story += [p('7-2  오디오 파일 재생', 'h3'), sp(2)]
    story += [step(1, '"File…" 버튼을 클릭해서 WAV 또는 AIFF 파일을 선택합니다.')]
    story += [step(2, '파일은 자동으로 루프(반복 재생)됩니다.')]
    story += [step(3, 'Start 버튼으로 분석을 시작하면 파일을 재생하면서 동시에 측정합니다.')]
    story += [sp(4)]
    story += [warn_box('레벨 설정 주의',
        '레벨 스핀박스에 숫자를 입력할 때는 반드시 Enter 키를 눌러야 적용됩니다.',
        '숫자를 입력하는 도중에는 실제 레벨이 변경되지 않습니다.')]
    story += [PageBreak()]

    # ══════════════════════════════════════════════════════
    #  8. 스펙트럼 분석 — FFT
    # ══════════════════════════════════════════════════════
    story += [section_header('8', '스펙트럼 분석 — FFT'), sp(4)]
    story += [p('실시간 주파수 스펙트럼을 연속된 곡선으로 표시합니다. 가로축: 주파수(Hz), 세로축: 레벨(dBFS)', 'body')]
    story += [sp(4)]
    story += [tbl(
        ['설정 항목', '위치', '설명'],
        [
            ['dB Range', '상단 버튼', '72 / 96 / 120 dB — 세로축 표시 범위'],
            ['Speed', '상단 버튼', 'Fastest ~ Slowest — 그래프 업데이트 속도 (Slow일수록 부드럽고 안정적)'],
            ['Peak Hold', '상단 버튼', '피크 값 유지 여부. On = 최대값을 점선으로 유지'],
            ['마우스 휠', '그래프 위', '위아래: 가로축 확대/축소\nCtrl+휠: 세로축 이동'],
            ['📷 캡처', '상단 버튼', '현재 스펙트럼 저장 (→ 11. 캡처 기능 참고)'],
        ],
        col_w=[30*mm, 30*mm, 90*mm]
    ), sp(4)]
    story += [note_box('FFT 크기와 해상도',
        '기본 FFT 크기는 16384 포인트, 48kHz 샘플레이트 기준 약 2.9 Hz 해상도입니다.',
        '우측 패널 하단 "INFO" 영역에서 현재 설정값을 확인할 수 있습니다.')]
    story += [PageBreak()]

    # ══════════════════════════════════════════════════════
    #  9. 옥타브
    # ══════════════════════════════════════════════════════
    story += [section_header('9', '스펙트럼 분석 — 옥타브 (Octave)'), sp(4)]
    story += [p('주파수를 옥타브 밴드로 나눈 막대 그래프입니다. 음향 설계나 보정에 적합합니다.', 'body')]
    story += [sp(4)]
    story += [tbl(
        ['보기 모드', '설명'],
        [
            ['1/3 Oct', '1/3 옥타브 밴드 (가장 일반적, ISO 표준)'],
            ['1/12 Oct', '1/12 옥타브 밴드 (더 세밀한 주파수 분석)'],
            ['1/24 Oct', '1/24 옥타브 밴드 (전문 측정용 고해상도)'],
        ],
        col_w=[35*mm, 115*mm]
    ), sp(4)]
    story += [tip_box('옥타브 vs FFT 선택 기준',
        '→ 공간 음향 특성 파악, EQ 보정 → 1/3 Oct 권장',
        '→ 정밀한 공진 주파수 찾기, 딜레이 분석 → FFT 권장')]
    story += [PageBreak()]

    # ══════════════════════════════════════════════════════
    #  10. 스펙트로그램
    # ══════════════════════════════════════════════════════
    story += [section_header('10', '스펙트로그램 (Spectrogram)'), sp(4)]
    story += [p('시간의 흐름에 따라 스펙트럼이 어떻게 변하는지 색상으로 표시합니다.\n밝을수록 레벨이 높고, 어두울수록 레벨이 낮습니다.', 'body')]
    story += [sp(4)]
    story += [tbl(
        ['요소', '설명'],
        [
            ['가로축', '시간 (왼쪽=과거, 오른쪽=현재)'],
            ['세로축', '주파수 (아래=저주파, 위=고주파)'],
            ['색상', '파랑 → 초록 → 노랑 → 빨강 순으로 레벨 증가'],
            ['마우스 커서', '커서를 올리면 해당 위치의 주파수와 레벨 표시'],
        ],
        col_w=[30*mm, 120*mm]
    ), sp(4)]
    story += [note_box('스펙트로그램 활용 예',
        '잔향(리버브) 특성 분석: 소리가 멈춘 후 고음이 얼마나 빠르게 사라지는지 시각화',
        '하울링 분석: 특정 주파수가 계속 밝게 표시되는 부분을 찾아 EQ로 차단')]
    story += [PageBreak()]

    # ══════════════════════════════════════════════════════
    #  11. 캡처 기능
    # ══════════════════════════════════════════════════════
    story += [section_header('11', '캡처 기능'), sp(4)]
    story += [p('현재 측정 중인 스펙트럼 또는 전달함수를 스냅샷으로 저장해서 비교할 수 있습니다.\n최대 여러 개의 캡처를 동시에 화면에 겹쳐서 볼 수 있습니다.', 'body')]
    story += [sp(4)]
    story += [p('사용 방법', 'h2'), sp(2)]
    story += [step(1, '분석이 실행 중인 상태에서 "📷 캡처" 버튼을 클릭합니다.')]
    story += [step(2, '현재 곡선이 저장되고 그래프 오른쪽에 캡처 목록이 나타납니다.')]
    story += [step(3, '캡처를 더 추가하려면 다시 "📷 캡처"를 클릭합니다.')]
    story += [step(4, '캡처 항목을 클릭하면 해당 캡처가 맨 앞으로 이동합니다.')]
    story += [step(5, '캡처 색상을 클릭하면 색상을 변경할 수 있습니다.')]
    story += [step(6, '"×" 버튼으로 캡처를 삭제합니다.')]
    story += [sp(4)]
    story += [p('라이브 트레이스 앞으로 가져오기', 'h3'), sp(2)]
    story += [p('인풋 레벨 미터를 클릭하면 실시간 라이브 트레이스가 모든 캡처 위로 올라옵니다.\n캡처를 클릭하면 다시 해당 캡처가 맨 앞으로 이동합니다.', 'body')]
    story += [sp(4)]
    story += [tip_box('EQ 보정 전/후 비교 예시',
        '① 보정 전 상태에서 캡처 → ② EQ를 조정한 후 다시 측정',
        '→ 두 곡선을 겹쳐 보면서 어떤 주파수가 얼마나 변했는지 바로 확인 가능')]
    story += [PageBreak()]

    # ══════════════════════════════════════════════════════
    #  12. 전달함수 측정
    # ══════════════════════════════════════════════════════
    story += [section_header('12', '전달함수 측정 (Transfer Function)'), sp(4)]
    story += [p('전달함수(Transfer Function)는 두 신호(기준/측정)의 관계를 분석하는 기능입니다.\n스피커의 주파수 응답, 위상 특성, 지연 시간을 한 번에 측정할 수 있습니다.', 'body')]
    story += [sp(4)]
    story += [p('전달함수 창 열기', 'h2'), sp(2)]
    story += [step(1, '메인 화면 상단에서 "TF" 버튼을 클릭합니다.')]
    story += [step(2, 'Reference와 Measurement 입력 장치를 설정합니다.')]
    story += [step(3, '"Start" 버튼을 눌러 측정을 시작합니다.')]
    story += [sp(6)]

    story += [p('12-1  Magnitude (크기 응답)', 'h2'), sp(2)]
    story += [p('스피커의 주파수별 출력 크기를 표시합니다. 이상적인 스피커는 모든 주파수에서 동일한 레벨을 출력합니다.', 'body')]
    story += [sp(2)]
    story += [tbl(
        ['표시 요소', '설명'],
        [
            ['녹색 곡선', '전달함수 Magnitude (크기 응답)'],
            ['회색 영역', '코히런스(Coherence) — 신뢰도 표시. 높을수록 측정값이 신뢰할 수 있음'],
            ['가로축', '주파수 (Hz), 로그 스케일 20Hz ~ 20kHz'],
            ['세로축', '레벨 (dB)'],
            ['마우스 커서', '현재 주파수와 레벨을 실시간으로 화면에 표시'],
        ],
        col_w=[35*mm, 115*mm]
    ), sp(6)]

    story += [p('12-2  Phase (위상 응답)', 'h2'), sp(2)]
    story += [p('주파수별 위상 변화를 표시합니다. 크로스오버 설계, 딜레이 정렬에 사용합니다.', 'body')]
    story += [sp(2)]
    story += [tbl(
        ['보기 모드', '설명'],
        [
            ['Wrapped', '위상을 -180° ~ +180° 범위에서 순환 표시 (기본값)'],
            ['Unwrapped', '위상을 펼쳐서 연속적으로 표시 (슬로프 확인 시 유용)'],
            ['Group Delay', '군 지연 시간 표시 (ms 단위)'],
        ],
        col_w=[35*mm, 115*mm]
    ), sp(2)]
    story += [p(f'키보드 ↑/↓ 로 위상 화면을 위아래로 스크롤할 수 있습니다.', 'small')]
    story += [sp(6)]

    story += [p('12-3  Impulse Response (임펄스 응답)', 'h2'), sp(2)]
    story += [p('신호가 입력된 후 시스템이 어떻게 반응하는지 시간 영역에서 표시합니다.\n딜레이 측정, 반사음 분석, 잔향 확인에 활용합니다.', 'body')]
    story += [sp(2)]
    story += [tbl(
        ['항목', '설명'],
        [
            ['표시 모드', 'Lin (선형) / ETC (에너지 감쇠 곡선) / Log (로그)'],
            ['가로축', '시간 (ms)'],
            ['주황색 점선', '딜레이 파인더로 측정된 딜레이 값 위치 표시'],
            ['← → 키', '화면 좌우 스크롤 (캔버스 클릭 후 사용)'],
            ['Cmd + / -', '확대 / 축소 (캔버스 클릭 후 사용)'],
            ['마우스 휠', '좌우 스크롤 / Ctrl+휠: 확대/축소'],
        ],
        col_w=[35*mm, 115*mm]
    ), sp(6)]

    story += [p('12-4  딜레이 파인더 (Delay Finder)', 'h2'), sp(2)]
    story += [p('스피커와 측정 마이크 사이의 지연 시간(딜레이)을 자동으로 측정합니다.', 'body')]
    story += [sp(2)]
    story += [step(1, '측정이 진행 중인 상태에서 "🔍 Find [L]" 버튼을 클릭하거나 키보드 L을 누릅니다.')]
    story += [step(2, '자동으로 임펄스 응답에서 피크 위치를 찾아 딜레이 값을 계산합니다.')]
    story += [step(3, '측정된 딜레이 값(ms)이 Delay 필드에 자동 입력됩니다.')]
    story += [step(4, '임펄스 응답 그래프에 주황색 점선으로 딜레이 위치가 표시됩니다.')]
    story += [sp(4)]
    story += [tip_box('딜레이 파인더 활용',
        '서브우퍼 딜레이 정렬: 메인 스피커와 서브우퍼의 딜레이 차이를 측정하고',
        '서브우퍼 딜레이 설정에 입력하면 위상 정렬이 됩니다.')]
    story += [PageBreak()]

    # ══════════════════════════════════════════════════════
    #  13. SPL 미터
    # ══════════════════════════════════════════════════════
    story += [section_header('13', 'SPL 미터'), sp(4)]
    story += [p('실시간 음압 레벨(Sound Pressure Level)을 크게 표시하는 별도 창입니다.\n공연장, 강의실 등에서 소음 레벨을 모니터링할 때 사용합니다.', 'body')]
    story += [sp(4)]
    story += [p('열기 방법: 우측 패널 "LEVEL" 섹션의 레벨 숫자를 클릭합니다.', 'body_b')]
    story += [sp(4)]
    story += [tbl(
        ['표시 항목', '설명'],
        [
            ['큰 숫자 (SPL)', '현재 순간 음압 레벨 (dBFS 또는 dB SPL)'],
            ['Peak Hold', '측정 이후 최대 레벨'],
            ['dBA', 'A 가중치 레벨 (인간의 청각 민감도 반영, 소음 규정 기준값)'],
            ['dBC', 'C 가중치 레벨 (저주파 포함, 저음이 강한 환경에 사용)'],
        ],
        col_w=[35*mm, 115*mm]
    ), sp(4)]
    story += [PageBreak()]

    # ══════════════════════════════════════════════════════
    #  14. LEQ 측정
    # ══════════════════════════════════════════════════════
    story += [section_header('14', 'LEQ 시간 평균 측정'), sp(4)]
    story += [p('LEQ(Equivalent Continuous Sound Level)는 일정 시간 동안의 평균 에너지 레벨입니다.\n소음 규정, 공연 후 청력 보호 기준 확인 등에 사용합니다.', 'body')]
    story += [sp(4)]
    story += [p('열기 방법: 메인 화면 우측 패널의 LEQ 또는 📊 버튼을 클릭합니다.', 'body_b')]
    story += [sp(4)]
    story += [p('사용 방법', 'h2'), sp(2)]
    story += [step(1, '"Duration" 에서 측정할 시간을 설정합니다. (5분 ~ 60분)')]
    story += [step(2, '"▶ Start" 버튼을 클릭합니다.')]
    story += [step(3, '진행률 표시줄이 채워지며 실시간으로 LEQ(A), LEQ(C) 값이 업데이트됩니다.')]
    story += [step(4, '설정한 시간이 지나면 자동으로 측정이 완료됩니다.')]
    story += [sp(4)]
    story += [tbl(
        ['표시 항목', '설명'],
        [
            ['LEQ(A)', '시간 평균 A 가중치 레벨 (소음 규정의 핵심 지표)'],
            ['LEQ(C)', '시간 평균 C 가중치 레벨 (저주파 포함)'],
            ['dBA (실시간)', '현재 순간 A 가중치 레벨'],
            ['dBC (실시간)', '현재 순간 C 가중치 레벨'],
            ['Elapsed / 진행률', '경과 시간과 전체 측정 시간 대비 퍼센트'],
        ],
        col_w=[35*mm, 115*mm]
    ), sp(4)]
    story += [note_box('EU 소음 규정 기준 (참고)',
        '8시간 작업 기준 LEQ(A) 80 dB 초과 시 청력 보호 조치 필요 (EU Directive 2003/10/EC)',
        '공연장 관객 기준: 15분 평균 107 dB(C) 초과 금지 (ISO 45001 권고사항)')]
    story += [PageBreak()]

    # ══════════════════════════════════════════════════════
    #  15. 키보드 단축키
    # ══════════════════════════════════════════════════════
    story += [section_header('15', '키보드 단축키 모음'), sp(4)]
    story += [tbl(
        ['단축키', '기능', '조건'],
        [
            ['G', '시그널 제네레이터 Play / Stop 토글', '메인 창 포커스'],
            ['L', '딜레이 파인더 실행', '전달함수 창 열린 상태'],
            ['← / →', 'IR 그래프 좌우 스크롤', 'IR 캔버스 클릭 후'],
            ['Cmd + =', 'IR 그래프 확대 (줌 인)', 'IR 캔버스 클릭 후'],
            ['Cmd + -', 'IR 그래프 축소 (줌 아웃)', 'IR 캔버스 클릭 후'],
            ['↑ / ↓', 'Phase 그래프 위아래 스크롤', 'Phase 캔버스 클릭 후'],
            ['마우스 휠', 'FFT / Oct 그래프 세로축 이동', '그래프 위에서'],
            ['Ctrl + 마우스 휠', 'FFT / Oct 그래프 세로축 크기 조절', '그래프 위에서'],
        ],
        col_w=[38*mm, 70*mm, 42*mm]
    ), sp(4)]
    story += [note_box('키보드 단축키 사용 전 준비',
        'IR, Phase 그래프는 먼저 해당 캔버스를 마우스로 클릭해야 키보드 입력이 활성화됩니다.',
        '다른 UI 요소(버튼, 스핀박스)가 포커스를 가지고 있으면 단축키가 작동하지 않을 수 있습니다.')]
    story += [PageBreak()]

    # ══════════════════════════════════════════════════════
    #  16. 문제 해결
    # ══════════════════════════════════════════════════════
    story += [section_header('16', '문제 해결 (Troubleshooting)'), sp(4)]

    issues = [
        ('앱이 실행되지 않아요 (보안 경고)',
         ['Finder에서 WSA2 아이콘을 Control + 클릭 → "열기" 선택',
          '만약 "손상됨" 경고가 뜨면: 터미널에서 다음 명령어 실행',
          '  xattr -cr /Applications/WSA2.app']),
        ('소리가 나지 않아요 (Signal Generator)',
         ['시스템 환경설정 → 사운드 → 출력 장치 확인',
          'Signal Generator의 Out 항목에서 올바른 기기가 선택됐는지 확인',
          '▶ Play 버튼이 눌린 상태(초록색)인지 확인',
          '볼륨이 0이 아닌지, Level이 너무 낮지 않은지 확인 (권장: -20 dB)']),
        ('레벨 미터가 움직이지 않아요',
         ['⏻ 버튼이 켜진 상태(초록)인지 확인',
          'Input Devices에서 올바른 장치와 채널이 선택됐는지 확인',
          'Mac 시스템 환경설정 → 개인 정보 보호 → 마이크 → WSA2 허용 확인']),
        ('그래프가 멈추거나 끊겨요',
         ['Speed를 "Slow" 또는 "Normal"로 낮춰보세요',
          '다른 응용 프로그램을 종료해서 CPU 부하를 줄이세요',
          'USB 허브 대신 Mac 직접 연결 포트에 오디오 인터페이스를 연결하세요']),
        ('Transfer Function이 노이즈가 많아요 (코히런스 낮음)',
         ['마이크가 스피커와 충분히 가깝게 위치해 있는지 확인',
          '주변 소음(에어컨, 환경음)을 최대한 줄이세요',
          'Signal Generator 레벨을 높여보세요 (단, 왜곡이 없는 범위에서)',
          '평균 횟수를 늘리면 코히런스가 개선됩니다 (Speed를 느리게 설정)']),
        ('딜레이 파인더 값이 이상해요',
         ['L 버튼을 누르기 전에 측정이 안정화될 때까지 충분히 기다리세요',
          '마이크 위치가 측정하려는 스피커를 직접 향하고 있는지 확인',
          '임펄스 응답 그래프에서 명확한 피크가 보이는지 확인']),
    ]
    for title, steps in issues:
        story += [KeepTogether([
            p(f'Q.  {title}', 'h3'),
            *[bullet(s) for s in steps],
            sp(3),
        ])]

    story += [PageBreak()]

    # ══════════════════════════════════════════════════════
    #  17. 로그 & 버그 신고
    # ══════════════════════════════════════════════════════
    story += [section_header('17', '로그 파일 & 버그 신고'), sp(4)]
    story += [p('WSA2는 실행할 때마다 자동으로 세션 로그를 기록합니다.\n문제가 발생했을 때 이 로그 파일을 개발자에게 보내면 빠른 분석이 가능합니다.', 'body')]
    story += [sp(4)]
    story += [p('로그 파일 위치', 'h2'), sp(2)]

    log_box = Table([[
        Paragraph('~/Library/Logs/WSA2/', ParagraphStyle('lp', fontName='Courier', fontSize=11,
                  textColor=C_TEAL, leading=16))
    ]], colWidths=[150*mm])
    log_box.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),C_BG_LIGHT),
        ('BOX',(0,0),(-1,-1),1,C_TEAL),
        ('LEFTPADDING',(0,0),(-1,-1),14),
        ('TOPPADDING',(0,0),(-1,-1),10),
        ('BOTTOMPADDING',(0,0),(-1,-1),10),
    ]))
    story += [log_box, sp(4)]

    story += [p('로그 폴더 빠르게 열기', 'h3'), sp(2)]
    story += [step(1, 'WSA2 메인 화면 우측 패널 맨 아래 "Log" 버튼을 클릭합니다.')]
    story += [step(2, 'Finder에서 로그 폴더가 자동으로 열립니다.')]
    story += [step(3, '가장 최근 날짜의 wsa2_YYYYMMDD_HHMMSS.log 파일을 첨부해서 보내주세요.')]
    story += [sp(4)]

    story += [p('로그 파일 내용', 'h3'), sp(2)]
    story += [tbl(
        ['기록 항목', '설명'],
        [
            ['세션 시작 정보', 'OS 버전, 하드웨어 종류, Python 버전, 앱 버전'],
            ['오디오 장치 동작', '스트림 열기/닫기, 에러, 레이턴시 값'],
            ['크래시 정보', '앱이 비정상 종료될 경우 전체 오류 내용 자동 기록'],
            ['라이선스 상태', '라이선스 확인 결과'],
        ],
        col_w=[45*mm, 105*mm]
    ), sp(4)]

    story += [warn_box('개인정보 안내',
        '로그 파일에는 음성 데이터나 개인 식별 정보가 포함되지 않습니다.',
        '오디오 장치 이름(예: Focusrite USB)과 측정 설정값만 기록됩니다.',
        '라이선스 키 전체는 기록되지 않으며, 머신 ID만 짧게 기록됩니다.')]
    story += [sp(6)]

    # 마지막 페이지
    story += [PageBreak(), sp(30)]
    story += [HRFlowable(width='80%', thickness=1, color=C_TEAL, hAlign='CENTER')]
    story += [sp(6)]
    story += [p('감사합니다', 'cover_sub')]
    story += [sp(4)]
    story += [p('WAYAUDIO Spectrum Analyzer 2를 사용해 주셔서 감사합니다.', 'center')]
    story += [sp(2)]
    story += [p('문의사항이나 버그 신고는 우측 패널 Log 버튼에서 로그 파일을 찾아 전달해 주세요.', 'center')]
    story += [sp(8)]
    story += [p('v2.1  |  © WAYAUDIO  |  2026', 'center')]

    return story


# ─────────────────────────────────────────────────────────────────────────────
#  빌드
# ─────────────────────────────────────────────────────────────────────────────
def build_pdf(output_path):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=24*mm,  bottomMargin=18*mm,
        title='WSA2 사용자 매뉴얼',
        author='WAYAUDIO',
        subject='WAYAUDIO Spectrum Analyzer 2 User Manual',
    )

    def _page_cb(canvas, doc):
        if doc.page == 1:
            cover_background(canvas, doc)
        else:
            page_background(canvas, doc)

    story = build_story()
    doc.build(story, onFirstPage=_page_cb, onLaterPages=_page_cb)
    print(f'PDF 생성 완료: {output_path}')


if __name__ == '__main__':
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'WSA2_Manual.pdf')
    build_pdf(out)
