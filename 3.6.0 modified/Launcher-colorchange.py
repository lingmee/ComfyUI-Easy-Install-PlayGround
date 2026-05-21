VERSION = '3.6.0'

import os
import sys
import subprocess
import ctypes
import ctypes.wintypes as wt
import threading
import re
import shlex

import time
SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
ROOT_DIR   = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', '..'))
EZI_PY     = os.path.join(SCRIPT_DIR, 'ComfyUI-EZi.py')

def root(name):
    return os.path.join(ROOT_DIR, name)

ADDONS_DIR = root('Add-ons')

HAS_DESK_SAGE  = os.path.exists(root('Start ComfyUI SageAttention.bat'))
HAS_DESK_FLASH = os.path.exists(root('Start ComfyUI FlashAttention.bat'))
HAS_BROW_SAGE  = os.path.exists(root('Start ComfyUI SageAttention.bat'))
HAS_BROW_FLASH = os.path.exists(root('Start ComfyUI FlashAttention.bat'))

HAS_UPD_COMFY      = os.path.exists(root('Update ComfyUI.bat'))
HAS_UPD_COMFY_NODE = os.path.exists(root('Update ComfyUI and Nodes.bat'))
HAS_UPD_EASY       = os.path.exists(root('Update Easy-Install.bat'))

INSTALL_SAGE_BAT  = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'SageAttention-Multi (v2.2.0 and v3).bat'))
INSTALL_FLASH_BAT = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'FlashAttention.bat'))

WS_POPUP         = 0x80000000
WS_VISIBLE       = 0x10000000
WS_CLIPCHILDREN  = 0x02000000
WS_EX_TOPMOST    = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_CHILD         = 0x40000000
BS_OWNERDRAW     = 0x0000000B
TTS_ALWAYSTIP    = 0x0001
TTS_NOPREFIX     = 0x0002
TTM_ADDTOOLW     = 0x0432
TTM_SETMAXTIPWIDTH = 0x0418
TTDT_AUTOPOP     = 2
TTM_SETDELAYTIME = 0x0403
WM_DESTROY       = 0x0002
WM_PAINT         = 0x000F
WM_ERASEBKGND    = 0x0014
WM_COMMAND       = 0x0111
WM_NCHITTEST     = 0x0084
WM_ACTIVATE      = 0x0006
WM_DRAWITEM      = 0x002B
WM_MOUSEMOVE     = 0x0200
WM_MOUSELEAVE    = 0x02A3
WM_CTLCOLORBTN   = 0x0135
WM_KILLFOCUS     = 0x0008
WM_LBUTTONDOWN   = 0x0201
HTCAPTION        = 2
IDC_ARROW        = 32512
CS_HREDRAW       = 0x0002
CS_VREDRAW       = 0x0001
SW_SHOW          = 5
PS_SOLID         = 0
PS_DASH          = 1
DT_LEFT          = 0x0000
DT_CENTER        = 0x0001
DT_VCENTER       = 0x0004
DT_SINGLELINE    = 0x0020
SRCCOPY          = 0x00CC0020
RDW_INVALIDATE   = 0x0001
RDW_UPDATENOW    = 0x0100
RDW_ALLCHILDREN  = 0x0080

# Pixaroma theme
C_BG            = 0x2E1E1E
C_TITLEBAR      = 0x382B31
C_BORDER        = 0x4A4048
C_FOOTER_BG     = 0x2E1E1E

C_ORANGE = 0xB38F28
C_GREEN  = 0x94E2D5
C_BLUE   = 0xCBA6F7

C_DP_BG         = 0x443F5A
C_DP_BORDER     = 0xCBA6F7
C_DP_TEXT       = 0xCBA6F7
C_DPH_BG        = 0x5A446F
C_DPH_BORDER    = 0xE0C6FF
C_DPH_TEXT      = 0xE0C6FF

C_DP_INST_BORDER = 0x8F73B8
C_DP_INST_TEXT   = 0x8F73B8

C_BP_BG         = 0x313C4A
C_BP_BORDER     = 0x94E2D5
C_BP_TEXT       = 0x94E2D5
C_BPH_BG        = 0x2E5A5C
C_BPH_BORDER    = 0xB5F5EC
C_BPH_TEXT      = 0xB5F5EC

C_BP_INST_BORDER = 0x5B8A83
C_BP_INST_TEXT   = 0x5B8A83

C_UP_BG         = 0x473A34
C_UP_BORDER     = 0xFAB387
C_UP_TEXT       = 0xFAB387
C_UPH_BG        = 0x6B4A3D
C_UPH_BORDER    = 0xFFD1B8
C_UPH_TEXT      = 0xFFD1B8

C_UP_DIM_BORDER = 0x8A6C5B
C_UP_DIM_TEXT   = 0x8A6C5B

C_FLD_BG        = 0x3B3347
C_FLD_BORDER    = 0x585B70
# C_FLD_TEXT      = 0x999999
C_FLD_TEXT      = C_DP_BORDER
C_FLDH_BG       = 0x443F5A
C_FLDH_BORDER   = 0x89B4FA
C_FLDH_TEXT     = 0x89B4FA

# Layout
WIN_W           = 520
SEP_X           = 180
SEP2_X          = 350
TITLE_H         = 36
STRIPE_H        = 2
SEC_TOP_PAD     = 12
SEC_LABEL_H     = 22
SEC_LABEL_PAD   = 0
CONTENT_TOP     = TITLE_H + STRIPE_H + SEC_TOP_PAD + SEC_LABEL_H + SEC_LABEL_PAD
BTN_H           = 36
BTN_GAP         = 6
FOOTER_H        = 44
FOOTER_BTN_H    = 28
BOT_PAD         = 8
ARROW_W         = 22
ARROW_GAP       = 2

WIN_H = CONTENT_TOP + (3 * BTN_H) + (2 * BTN_GAP) + BOT_PAD + FOOTER_H

user32   = ctypes.windll.user32
gdi32    = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

if sys.maxsize > 2**32:
    LRESULT = ctypes.c_int64
    WPARAM  = ctypes.c_uint64
    LPARAM  = ctypes.c_int64
else:
    LRESULT = ctypes.c_long
    WPARAM  = ctypes.c_uint
    LPARAM  = ctypes.c_long

WNDPROC       = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, WPARAM, LPARAM)
BTN_PROC_TYPE = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, WPARAM, LPARAM)

user32.DefWindowProcW.argtypes    = [wt.HWND, wt.UINT, WPARAM, LPARAM]
user32.DefWindowProcW.restype     = LRESULT
user32.CallWindowProcW.argtypes   = [WNDPROC, wt.HWND, wt.UINT, WPARAM, LPARAM]
user32.CallWindowProcW.restype    = LRESULT
user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype  = ctypes.c_void_p
user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_void_p]
user32.SetWindowLongPtrW.restype  = ctypes.c_void_p
user32.FillRect.argtypes          = [wt.HDC, ctypes.POINTER(wt.RECT), wt.HBRUSH]
user32.FillRect.restype           = ctypes.c_int
user32.GetDlgCtrlID.argtypes      = [wt.HWND]
user32.GetDlgCtrlID.restype       = ctypes.c_int
user32.SendMessageW.argtypes      = [wt.HWND, wt.UINT, WPARAM, LPARAM]
user32.SendMessageW.restype       = LRESULT
user32.GetDlgItem.argtypes        = [wt.HWND, ctypes.c_int]
user32.GetDlgItem.restype         = wt.HWND
user32.SetFocus.argtypes          = [wt.HWND]
user32.SetFocus.restype           = wt.HWND

class WNDCLASSEX(ctypes.Structure):
    _fields_ = [
        ('cbSize',        wt.UINT),
        ('style',         wt.UINT),
        ('lpfnWndProc',   WNDPROC),
        ('cbClsExtra',    ctypes.c_int),
        ('cbWndExtra',    ctypes.c_int),
        ('hInstance',     wt.HINSTANCE),
        ('hIcon',         wt.HICON),
        ('hCursor',       wt.HANDLE),
        ('hbrBackground', wt.HBRUSH),
        ('lpszMenuName',  wt.LPCWSTR),
        ('lpszClassName', wt.LPCWSTR),
        ('hIconSm',       wt.HICON),
    ]

class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ('hdc',         wt.HDC),
        ('fErase',      wt.BOOL),
        ('rcPaint',     wt.RECT),
        ('fRestore',    wt.BOOL),
        ('fIncUpdate',  wt.BOOL),
        ('rgbReserved', ctypes.c_byte * 32),
    ]

class LOGFONT(ctypes.Structure):
    _fields_ = [
        ('lfHeight',         ctypes.c_long),
        ('lfWidth',          ctypes.c_long),
        ('lfEscapement',     ctypes.c_long),
        ('lfOrientation',    ctypes.c_long),
        ('lfWeight',         ctypes.c_long),
        ('lfItalic',         ctypes.c_byte),
        ('lfUnderline',      ctypes.c_byte),
        ('lfStrikeOut',      ctypes.c_byte),
        ('lfCharSet',        ctypes.c_byte),
        ('lfOutPrecision',   ctypes.c_byte),
        ('lfClipPrecision',  ctypes.c_byte),
        ('lfQuality',        ctypes.c_byte),
        ('lfPitchAndFamily', ctypes.c_byte),
        ('lfFaceName',       ctypes.c_wchar * 32),
    ]

class DRAWITEMSTRUCT(ctypes.Structure):
    _fields_ = [
        ('CtlType',    wt.UINT),
        ('CtlID',      wt.UINT),
        ('itemID',     wt.UINT),
        ('itemAction', wt.UINT),
        ('itemState',  wt.UINT),
        ('_pad',       ctypes.c_uint),
        ('hwndItem',   wt.HWND),
        ('hDC',        wt.HDC),
        ('rcItem',     wt.RECT),
        ('itemData',   ctypes.c_size_t),
    ]

class TRACKMOUSEEVENT(ctypes.Structure):
    _pack_ = 8
    _fields_ = [
        ('cbSize',      wt.DWORD),
        ('dwFlags',     wt.DWORD),
        ('hwndTrack',   wt.HWND),
        ('dwHoverTime', wt.DWORD),
    ]

def make_font(size, weight=400, face='Segoe UI'):
    lf = LOGFONT()
    lf.lfHeight         = size
    lf.lfWeight         = weight
    lf.lfQuality        = 5
    lf.lfPitchAndFamily = 0x22
    lf.lfFaceName       = face
    return gdi32.CreateFontIndirectW(ctypes.byref(lf))

def make_solid_brush(c):
    return gdi32.CreateSolidBrush(c)

class POINT(ctypes.Structure):
    _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]

def calc_position():
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    x, y = pt.x + 16, pt.y + 16
    if x + WIN_W > sw: x = sw - WIN_W - 8
    if y + WIN_H > sh: y = sh - WIN_H - 8
    if x < 0: x = 8
    if y < 0: y = 8
    return x, y

ID_CLOSE      = 1
ID_EZI_DESK   = 10
ID_SAGE_DESK  = 11
ID_FLASH_DESK = 12
ID_EZI_BROW   = 20
ID_SAGE_BROW  = 21
ID_FLASH_BROW = 22

ID_UPD_COMFY      = 30
ID_UPD_COMFY_NODE = 31
ID_UPD_EASY       = 32

ID_FOLD_OUTPUT    = 41
ID_FOLD_INPUT     = 42
ID_FOLD_WORKFLOWS = 43
ID_FOLD_MODELS    = 44

ID_SC_EZI_DESK   = 110
ID_SC_SAGE_DESK  = 111
ID_SC_FLASH_DESK = 112
ID_SC_EZI_BROW   = 120
ID_SC_SAGE_BROW  = 121
ID_SC_FLASH_BROW = 122

SHORTCUT_META = {
    ID_SC_EZI_DESK:   (ID_EZI_DESK,   'ComfyUI-EZi-Desktop.ico', 'ComfyUI-EZi Desktop'),
    ID_SC_SAGE_DESK:  (ID_SAGE_DESK,  'ComfyUI-EZi-Desktop.ico', 'ComfyUI-EZi SA'),
    ID_SC_FLASH_DESK: (ID_FLASH_DESK, 'ComfyUI-EZi-Desktop.ico', 'ComfyUI-EZi FA'),
    ID_SC_EZI_BROW:   (ID_EZI_BROW,   'ComfyUI-EZi.ico',         'ComfyUI-EZi'),
    ID_SC_SAGE_BROW:  (ID_SAGE_BROW,  'ComfyUI-Sage.ico',        'ComfyUI-SA'),
    ID_SC_FLASH_BROW: (ID_FLASH_BROW, 'ComfyUI-Flash.ico',       'ComfyUI-FA'),
}

WM_APP_CLOSE = 0x8001

g_fonts          = {}
g_brushes        = {}
g_hover_btn      = None
g_gradient_memdc = None
g_gradient_bmp   = None
g_tooltip_hwnd   = None
g_creating_shortcut = False
g_hwnd           = None

class TOOLINFOW(ctypes.Structure):
    _fields_ = [
        ('cbSize',   wt.UINT),
        ('uFlags',   wt.UINT),
        ('hwnd',     wt.HWND),
        ('uId',      ctypes.c_size_t),
        ('rect',     wt.RECT),
        ('hinst',    wt.HINSTANCE),
        ('lpszText', wt.LPCWSTR),
        ('lParam',   ctypes.c_size_t),
        ('lpReserved', ctypes.c_void_p),
    ]

BTN_META = {
    ID_EZI_DESK:       ('ComfyUI EZi',     'desk'),
    ID_SAGE_DESK:      ('SageAttn',        'desk'),
    ID_FLASH_DESK:     ('FlashAttn',       'desk'),
    ID_EZI_BROW:       ('ComfyUI EZi',     'brow'),
    ID_SAGE_BROW:      ('SageAttn',        'brow'),
    ID_FLASH_BROW:     ('FlashAttn',       'brow'),
    ID_UPD_COMFY:      ('ComfyUI',         'upd'),
    ID_UPD_COMFY_NODE: ('ComfyUI + Nodes', 'upd'),
    ID_UPD_EASY:       ('Easy-Install',    'upd'),
    ID_CLOSE:          ('\u2715',          'close'),
    ID_FOLD_OUTPUT:    ('Output',          'fld'),
    ID_FOLD_INPUT:     ('Input',           'fld'),
    ID_FOLD_WORKFLOWS: ('Workflows',       'fld'),
    ID_FOLD_MODELS:    ('Models',          'fld'),
}

INSTALL_BTN_STATE = {
    ID_SAGE_DESK:  lambda: not HAS_DESK_SAGE,
    ID_FLASH_DESK: lambda: not HAS_DESK_FLASH,
    ID_SAGE_BROW:  lambda: not HAS_BROW_SAGE,
    ID_FLASH_BROW: lambda: not HAS_BROW_FLASH,
}

def is_install_state(btn_id):
    fn = INSTALL_BTN_STATE.get(btn_id)
    return fn() if fn else False

DIMMED_BTN_STATE = {
    ID_UPD_COMFY:      lambda: not HAS_UPD_COMFY,
    ID_UPD_COMFY_NODE: lambda: not HAS_UPD_COMFY_NODE,
    ID_UPD_EASY:       lambda: not HAS_UPD_EASY,
}

def is_dimmed_state(btn_id):
    fn = DIMMED_BTN_STATE.get(btn_id)
    return fn() if fn else False

def get_brush(c):
    if c not in g_brushes:
        g_brushes[c] = make_solid_brush(c)
    return g_brushes[c]


def _find_bat_comfy_line(bat_content):
    lines = bat_content.splitlines()
    logical_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        while line.rstrip('\r').rstrip().endswith('^') and i + 1 < len(lines):
            line = line.rstrip('\r').rstrip()[:-1] + ' ' + lines[i + 1].lstrip()
            i += 1
        logical_lines.append(line)
        i += 1
    for line in logical_lines:
        stripped = line.strip()
        if stripped.startswith('::') or re.match(r'(?i)^rem(\s|$)', stripped):
            continue
        if (re.search(r'python_embeded[/\\]python\.exe', stripped, re.IGNORECASE) and
                re.search(r'ComfyUI[/\\]main\.py', stripped, re.IGNORECASE)):
            return stripped
    return None


def _get_bat_file():
    bat_arg = sys.argv[1] if len(sys.argv) > 1 else 'Start ComfyUI.bat'
    return bat_arg if os.path.isabs(bat_arg) else os.path.join(ROOT_DIR, bat_arg)


def _get_comfy_user_dir():
    bat_file = _get_bat_file()
    user_dir = None
    if os.path.exists(bat_file):
        try:
            with open(bat_file, 'r', encoding='utf-8', errors='replace') as f:
                bat_content = f.read()
            m_env = re.search(r'(?i)set\s+"?COMFY_USER_DIR=([^"\n]+)"?', bat_content)
            if m_env:
                user_dir = m_env.group(1).strip().strip('"')
            else:
                comfy_line = _find_bat_comfy_line(bat_content)
                if comfy_line:
                    m = re.search(r'python_embeded[/\\]python\.exe["\'"]?\s+(.*)',
                                  comfy_line, re.IGNORECASE)
                    if m:
                        tokens = shlex.split(m.group(1).strip(), posix=False)
                        for i, tok in enumerate(tokens):
                            if tok == '--user-directory' and i + 1 < len(tokens):
                                user_dir = tokens[i + 1].strip('"\'')
                                break
        except Exception:
            pass
    if user_dir:
        if not os.path.isabs(user_dir):
            user_dir = os.path.normpath(os.path.join(ROOT_DIR, user_dir))
        return os.path.join(user_dir, 'default')
    return os.path.join(ROOT_DIR, 'ComfyUI', 'user', 'default')


def _resolve_output_dir():
    bat_file = _get_bat_file()
    output_dir = None
    try:
        if os.path.exists(bat_file):
            with open(bat_file, 'r', encoding='utf-8', errors='replace') as f:
                bat_content = f.read()
            m_env = re.search(r'(?i)set\s+"?COMFY_OUTPUT_DIR=([^"\n]+)"?', bat_content)
            if m_env:
                output_dir = m_env.group(1).strip().strip('"')
            m_arg = re.search(r'python_embeded[/\\]python\.exe["\'"]?\s+(.*)',
                              _find_bat_comfy_line(bat_content) or '', re.IGNORECASE)
            if m_arg:
                parsed = shlex.split(m_arg.group(1).strip(), posix=False)
                for idx, tok in enumerate(parsed):
                    if tok == '--output-directory' and idx + 1 < len(parsed):
                        output_dir = parsed[idx + 1].strip('"\'')
                        break
    except Exception:
        pass
    if not output_dir:
        output_dir = os.path.normpath(os.path.join(ROOT_DIR, 'ComfyUI', 'output'))
    output_dir = os.path.normpath(output_dir)
    return output_dir if os.path.isdir(output_dir) else None


def _resolve_input_dir():
    bat_file = _get_bat_file()
    try:
        if os.path.exists(bat_file):
            with open(bat_file, 'r', encoding='utf-8', errors='replace') as f:
                bat_content = f.read()
            m_env = re.search(r'(?i)set\s+"?COMFY_INPUT_DIR=([^"\n]+)"?', bat_content)
            if m_env:
                d = m_env.group(1).strip().strip('"')
                if not os.path.isabs(d):
                    d = os.path.normpath(os.path.join(ROOT_DIR, d))
                return d if os.path.isdir(d) else None
            comfy_line = _find_bat_comfy_line(bat_content)
            if comfy_line:
                m = re.search(r'python_embeded[/\\]python\.exe["\'"]?\s+(.*)',
                              comfy_line, re.IGNORECASE)
                if m:
                    tokens = shlex.split(m.group(1).strip(), posix=False)
                    for i, tok in enumerate(tokens):
                        if tok == '--input-directory' and i + 1 < len(tokens):
                            d = tokens[i + 1].strip('"\'')
                            if not os.path.isabs(d):
                                d = os.path.normpath(os.path.join(ROOT_DIR, d))
                            return d if os.path.isdir(d) else None
    except Exception:
        pass
    d = os.path.normpath(os.path.join(ROOT_DIR, 'ComfyUI', 'input'))
    return d if os.path.isdir(d) else None


def _resolve_workflows_dir():
    user_dir = _get_comfy_user_dir()
    d = os.path.join(user_dir, 'workflows')
    return d if os.path.isdir(d) else None


def _resolve_models_dir():
    yaml_path = os.path.normpath(
        os.path.join(ROOT_DIR, 'ComfyUI', 'extra_model_paths.yaml'))
    if os.path.exists(yaml_path):
        try:
            with open(yaml_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            base_path = None
            m_base = re.search(r'^\s+base_path\s*:\s*(.+)$', content, re.MULTILINE)
            if m_base:
                base_path = m_base.group(1).strip().strip('"\'').rstrip('/\\')
            if base_path:
                parent_votes = {}
                for line in content.splitlines():
                    stripped = line.strip()
                    if (not stripped or stripped.startswith('#')
                            or re.match(r'(?i)base_path\s*:', stripped)
                            or re.match(r'(?i)is_default\s*:', stripped)):
                        continue
                    m_kv = re.match(r'^(\s{2,})\S[^:]+:\s*(.+)$', line)
                    if not m_kv:
                        continue
                    raw_val = m_kv.group(2).strip().strip('"\'').rstrip('/\\')
                    if not raw_val:
                        continue
                    if os.path.isabs(raw_val):
                        parent = os.path.normpath(os.path.dirname(raw_val))
                    else:
                        first_component = raw_val.replace('/', '\\').split('\\')[0]
                        parent = os.path.normpath(
                            os.path.join(base_path, first_component))
                    if os.path.isdir(parent):
                        parent_votes[parent] = parent_votes.get(parent, 0) + 1
                if parent_votes:
                    return max(parent_votes, key=lambda p: parent_votes[p])
        except Exception:
            pass
    d = os.path.normpath(os.path.join(ROOT_DIR, 'ComfyUI', 'models'))
    return d if os.path.isdir(d) else None


def _load_custom_browser():
    settings_path = os.path.join(SCRIPT_DIR, 'ComfyUI-EZi.settings.json')
    try:
        if os.path.exists(settings_path):
            import json
            with open(settings_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            cb = data.get('custom_file_browser', '').strip()
            if cb and os.path.isfile(cb):
                return cb
    except Exception:
        pass
    return None


def _open_folder(path):
    if path and os.path.isdir(path):
        try:
            custom = _load_custom_browser()
            if custom:
                subprocess.Popen([custom, path])
            else:
                os.startfile(path)
        except Exception:
            pass


def open_folder_async(resolver):
    threading.Thread(target=lambda: _open_folder(resolver()), daemon=True).start()


def btn_default_bg(btn_id):
    if btn_id in (ID_EZI_DESK,  ID_SAGE_DESK,  ID_FLASH_DESK,
                  ID_SC_EZI_DESK, ID_SC_SAGE_DESK, ID_SC_FLASH_DESK):
        if btn_id in INSTALL_BTN_STATE and is_install_state(btn_id):
            return C_BG
        return C_DP_BG
    if btn_id in (ID_EZI_BROW,  ID_SAGE_BROW,  ID_FLASH_BROW,
                  ID_SC_EZI_BROW, ID_SC_SAGE_BROW, ID_SC_FLASH_BROW):
        if btn_id in INSTALL_BTN_STATE and is_install_state(btn_id):
            return C_BG
        return C_BP_BG
    if btn_id in (ID_UPD_COMFY, ID_UPD_COMFY_NODE, ID_UPD_EASY):
        return C_UP_BG
    if btn_id in (ID_FOLD_OUTPUT, ID_FOLD_INPUT, ID_FOLD_WORKFLOWS, ID_FOLD_MODELS):
        return C_FLD_BG
    return C_BG


def launch_ezi():
    pythonw = os.path.join(ROOT_DIR, 'python_embeded', 'pythonw.exe')
    if not os.path.exists(pythonw):
        pythonw = re.sub(r'(?i)python\.exe$', 'pythonw.exe', sys.executable)
    subprocess.Popen([pythonw, EZI_PY], cwd=SCRIPT_DIR, creationflags=0x8)
    user32.PostMessageW(g_hwnd, WM_APP_CLOSE, 0, 0)


def launch_bat(name):
    bat = root(name)
    if os.path.exists(bat):
        subprocess.Popen(['cmd', '/c', 'start', '', bat], cwd=ROOT_DIR, creationflags=0x8)
    user32.PostMessageW(g_hwnd, WM_APP_CLOSE, 0, 0)


def launch_ezi_with_bat(bat_name):
    pythonw = os.path.join(ROOT_DIR, 'python_embeded', 'pythonw.exe')
    subprocess.Popen([pythonw, EZI_PY, bat_name], cwd=SCRIPT_DIR, creationflags=0x8)
    user32.PostMessageW(g_hwnd, WM_APP_CLOSE, 0, 0)


def install_addon(bat_path):
    if os.path.exists(bat_path):
        bat_dir = os.path.dirname(bat_path)
        subprocess.Popen(['cmd', '/c', 'start', '', bat_path],
                         cwd=bat_dir, creationflags=0x8)
    user32.PostMessageW(g_hwnd, WM_APP_CLOSE, 0, 0)


ACTIONS = {
    ID_EZI_DESK:   lambda: launch_ezi(),
    ID_EZI_BROW:   lambda: launch_bat('Start ComfyUI.bat'),

    ID_SAGE_DESK:  (
        (lambda: launch_ezi_with_bat('Start ComfyUI SageAttention.bat'))
        if HAS_DESK_SAGE
        else (lambda: install_addon(INSTALL_SAGE_BAT))
    ),
    ID_FLASH_DESK: (
        (lambda: launch_ezi_with_bat('Start ComfyUI FlashAttention.bat'))
        if HAS_DESK_FLASH
        else (lambda: install_addon(INSTALL_FLASH_BAT))
    ),
    ID_SAGE_BROW:  (
        (lambda: launch_bat('Start ComfyUI SageAttention.bat'))
        if HAS_BROW_SAGE
        else (lambda: install_addon(INSTALL_SAGE_BAT))
    ),
    ID_FLASH_BROW: (
        (lambda: launch_bat('Start ComfyUI FlashAttention.bat'))
        if HAS_BROW_FLASH
        else (lambda: install_addon(INSTALL_FLASH_BAT))
    ),

    ID_UPD_COMFY:      lambda: launch_bat('Update ComfyUI.bat'),
    ID_UPD_COMFY_NODE: lambda: launch_bat('Update ComfyUI and Nodes.bat'),
    ID_UPD_EASY:       lambda: launch_bat('Update Easy-Install.bat'),

    ID_FOLD_OUTPUT:    lambda: open_folder_async(_resolve_output_dir),
    ID_FOLD_INPUT:     lambda: open_folder_async(_resolve_input_dir),
    ID_FOLD_WORKFLOWS: lambda: open_folder_async(_resolve_workflows_dir),
    ID_FOLD_MODELS:    lambda: open_folder_async(_resolve_models_dir),
}


def create_shortcut(sc_btn_id):
    meta = SHORTCUT_META.get(sc_btn_id)
    if not meta:
        return
    main_id, ico_name, label = meta

    if main_id == ID_EZI_DESK:
        target   = sys.executable
        args     = '"{}"'.format(EZI_PY)
        work_dir = SCRIPT_DIR
    elif main_id in (ID_SAGE_DESK, ID_FLASH_DESK):
        pythonw  = os.path.join(ROOT_DIR, 'python_embeded', 'pythonw.exe')
        bat_map_desk = {
            ID_SAGE_DESK:  'Start ComfyUI SageAttention.bat',
            ID_FLASH_DESK: 'Start ComfyUI FlashAttention.bat',
        }
        target   = pythonw
        args     = '"{}" "{}"'.format(EZI_PY, bat_map_desk[main_id])
        work_dir = SCRIPT_DIR
    else:
        bat_map = {
            ID_EZI_BROW:   'Start ComfyUI.bat',
            ID_SAGE_BROW:  'Start ComfyUI SageAttention.bat',
            ID_FLASH_BROW: 'Start ComfyUI FlashAttention.bat',
        }
        target   = os.path.join(ROOT_DIR, bat_map[main_id])
        args     = ''
        work_dir = ROOT_DIR

    ico_path = os.path.join(SCRIPT_DIR, ico_name)

    def ps(s):
        return s.replace("'", "''")

    windir = os.environ.get('windir', r'C:\Windows')
    ps_exe = os.path.join(windir, r'System32\WindowsPowerShell\v1.0\powershell.exe')

    ps_cmd = (
        "$desktop=[Environment]::GetFolderPath('Desktop');"
        "$p=New-Object -ComObject WScript.Shell;"
        "$s=$p.CreateShortcut($desktop+'\\{label}.lnk');"
        "$s.TargetPath='{target}';"
        "$s.Arguments='{args}';"
        "$s.WorkingDirectory='{work_dir}';"
        "$s.IconLocation='{ico_path},0';"
        "$s.WindowStyle=1;"
        "$s.Save()"
    ).format(
        label    = ps(label),
        target   = ps(target),
        args     = ps(args),
        work_dir = ps(work_dir),
        ico_path = ps(ico_path),
    )

    global g_creating_shortcut
    g_creating_shortcut = True
    si = subprocess.STARTUPINFO()
    si.dwFlags    = subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    proc = subprocess.Popen(
        [ps_exe, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
         '-WindowStyle', 'Hidden', '-Command', ps_cmd],
        startupinfo=si,
    )

    def _finish():
        proc.wait()
        global g_creating_shortcut
        g_creating_shortcut = False
        user32.PostMessageW(g_hwnd, WM_APP_CLOSE, 0, 0)

    threading.Thread(target=_finish, daemon=True).start()


def _rgb(c):
    return (c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF)


def _to_col(r, g, b):
    return (b << 16) | (g << 8) | r


def _lerp(a, b, s):
    return int(a + (b - a) * s)


def _lerp_col(c1, c2, s):
    r1, g1, b1 = _rgb(c1)
    r2, g2, b2 = _rgb(c2)
    return _to_col(_lerp(r1, r2, s), _lerp(g1, g2, s), _lerp(b1, b2, s))


def _gradient_col(t):
    sep1 = SEP_X  / float(WIN_W)
    sep2 = SEP2_X / float(WIN_W)
    fade = 0.05

    if t <= sep1 - fade:
        return C_DP_BORDER
    if t < sep1 + fade:
        s = (t - (sep1 - fade)) / (2 * fade)
        return _lerp_col(C_DP_BORDER, C_BP_BORDER, s)
    if t <= sep2 - fade:
        return C_BP_BORDER
    if t < sep2 + fade:
        s = (t - (sep2 - fade)) / (2 * fade)
        return _lerp_col(C_BP_BORDER, C_UP_BORDER, s)
    return C_UP_BORDER


def create_gradient_cache():
    global g_gradient_memdc, g_gradient_bmp
    hdc_screen       = user32.GetDC(0)

    g_gradient_memdc = gdi32.CreateCompatibleDC(hdc_screen)
    g_gradient_bmp   = gdi32.CreateCompatibleBitmap(hdc_screen, WIN_W, STRIPE_H)
    gdi32.SelectObject(g_gradient_memdc, g_gradient_bmp)
    for i in range(WIN_W):
        t   = i / (WIN_W - 1)
        col = _gradient_col(t)
        pen = gdi32.CreatePen(PS_SOLID, 1, col)
        old = gdi32.SelectObject(g_gradient_memdc, pen)
        gdi32.MoveToEx(g_gradient_memdc, i, 0, None)
        gdi32.LineTo(g_gradient_memdc, i, STRIPE_H)
        gdi32.SelectObject(g_gradient_memdc, old)
        gdi32.DeleteObject(pen)

    user32.ReleaseDC(0, hdc_screen)


def draw_arrow_button(hdc, hw, rc):
    sc_id  = user32.GetDlgCtrlID(hw)
    meta   = SHORTCUT_META.get(sc_id)
    if not meta:
        return
    main_id = meta[0]
    hovered = (hw == g_hover_btn)

    if main_id in (ID_EZI_DESK, ID_SAGE_DESK, ID_FLASH_DESK):
        bg       = C_DPH_BG     if hovered else C_DP_BG
        border   = C_DPH_BORDER if hovered else C_DP_BORDER
        text_col = C_DPH_TEXT   if hovered else C_DP_TEXT
    else:
        bg       = C_BPH_BG     if hovered else C_BP_BG
        border   = C_BPH_BORDER if hovered else C_BP_BORDER
        text_col = C_BPH_TEXT   if hovered else C_BP_TEXT

    if rc.right <= rc.left or rc.bottom <= rc.top:
        return

    user32.FillRect(hdc, ctypes.byref(rc), get_brush(bg))

    pen = gdi32.CreatePen(PS_SOLID, 1, border)
    op  = gdi32.SelectObject(hdc, pen)
    ob  = gdi32.SelectObject(hdc, gdi32.GetStockObject(5))
    gdi32.RoundRect(hdc, rc.left, rc.top, rc.right, rc.bottom, 7, 7)
    gdi32.SelectObject(hdc, op)
    gdi32.SelectObject(hdc, ob)
    gdi32.DeleteObject(pen)

    old_font = gdi32.SelectObject(hdc, g_fonts['arrow'])
    gdi32.SetBkMode(hdc, 1)
    gdi32.SetTextColor(hdc, text_col)
    user32.DrawTextW(hdc, '\u2197', -1, ctypes.byref(rc),
                     DT_CENTER | DT_VCENTER | DT_SINGLELINE)
    gdi32.SelectObject(hdc, old_font)


def draw_button(hdc, hw, rc):
    btn_id = user32.GetDlgCtrlID(hw)
    meta   = BTN_META.get(btn_id)
    if not meta:
        return
    label, btn_type = meta
    hovered = (hw == g_hover_btn)
    install = is_install_state(btn_id)
    pen_style = PS_SOLID
    font = g_fonts['btn_pri']

    if btn_type == 'close':
        bg       = 0x3A3246      if hovered else C_BG
        border   = 0x585B70      if hovered else 0x45475A
        text_col = 0x89B4FA      if hovered else 0xF4D6CD
        font     = g_fonts['close']
    elif btn_type == 'fld':
        bg       = C_FLDH_BG     if hovered else C_FLD_BG
        border   = C_FLDH_BORDER if hovered else C_FLD_BORDER
        text_col = C_FLDH_TEXT   if hovered else C_FLD_TEXT
        font     = g_fonts['footer']
    elif btn_type == 'upd':
        if is_dimmed_state(btn_id):
            bg       = C_UP_BG
            border   = C_UP_DIM_BORDER
            text_col = C_UP_DIM_TEXT
            font     = g_fonts['btn_pri']
        else:
            bg       = C_UPH_BG     if hovered else C_UP_BG
            border   = C_UPH_BORDER if hovered else C_UP_BORDER
            text_col = C_UPH_TEXT   if hovered else C_UP_TEXT
            font     = g_fonts['btn_pri']
    elif btn_type == 'desk':
        if install:
            label    = '+ install ' + label
            bg       = C_BG
            border   = C_DPH_BORDER  if hovered else C_DP_INST_BORDER
            text_col = C_DPH_TEXT    if hovered else C_DP_INST_TEXT
            font     = g_fonts['btn_install']
        else:
            bg       = C_DPH_BG     if hovered else C_DP_BG
            border   = C_DPH_BORDER if hovered else C_DP_BORDER
            text_col = C_DPH_TEXT   if hovered else C_DP_TEXT
            font     = g_fonts['btn_pri']
    elif btn_type == 'brow':
        if install:
            label    = '+ install ' + label
            bg       = C_BG
            border   = C_BPH_BORDER  if hovered else C_BP_INST_BORDER
            text_col = C_BPH_TEXT    if hovered else C_BP_INST_TEXT
            font     = g_fonts['btn_install']
        else:
            bg       = C_BPH_BG     if hovered else C_BP_BG
            border   = C_BPH_BORDER if hovered else C_BP_BORDER
            text_col = C_BPH_TEXT   if hovered else C_BP_TEXT
            font     = g_fonts['btn_pri']
    else:
        bg = C_BG
        border = 0x45475A
        text_col = 0xF4D6CD

    if rc.right <= rc.left or rc.bottom <= rc.top:
        return

    user32.FillRect(hdc, ctypes.byref(rc), get_brush(bg))

    pen = gdi32.CreatePen(pen_style, 1, border)
    op  = gdi32.SelectObject(hdc, pen)
    ob  = gdi32.SelectObject(hdc, gdi32.GetStockObject(5))
    gdi32.RoundRect(hdc, rc.left, rc.top, rc.right, rc.bottom, 7, 7)
    gdi32.SelectObject(hdc, op)
    gdi32.SelectObject(hdc, ob)
    gdi32.DeleteObject(pen)

    old_font = gdi32.SelectObject(hdc, font)
    gdi32.SetBkMode(hdc, 1)
    gdi32.SetTextColor(hdc, text_col)
    user32.DrawTextW(hdc, label, -1, ctypes.byref(rc),
                     DT_CENTER | DT_VCENTER | DT_SINGLELINE)
    gdi32.SelectObject(hdc, old_font)


_subclass_procs = []


def make_btn_subclass(hwnd_btn, is_arrow=False):
    orig = user32.GetWindowLongPtrW(hwnd_btn, -4)

    @BTN_PROC_TYPE
    def sub_proc(hw, msg, wp, lp):
        global g_hover_btn
        if msg == WM_PAINT:
            ps  = PAINTSTRUCT()
            hdc = user32.BeginPaint(hw, ctypes.byref(ps))
            rc  = wt.RECT()
            user32.GetClientRect(hw, ctypes.byref(rc))
            if is_arrow:
                draw_arrow_button(hdc, hw, rc)
            else:
                draw_button(hdc, hw, rc)
            user32.EndPaint(hw, ctypes.byref(ps))
            return 0

        if msg == WM_ERASEBKGND:
            return 1

        if msg == WM_MOUSEMOVE:
            if g_hover_btn != hw:
                prev        = g_hover_btn
                g_hover_btn = hw
                if prev:
                    user32.InvalidateRect(prev, None, False)
                user32.InvalidateRect(hw, None, False)
                tme = TRACKMOUSEEVENT(
                    ctypes.sizeof(TRACKMOUSEEVENT), 0x00000002, hw, 0)
                user32.TrackMouseEvent(ctypes.byref(tme))

        elif msg == WM_MOUSELEAVE:
            if g_hover_btn == hw:
                g_hover_btn = None
                user32.InvalidateRect(hw, None, False)

        orig_proc = ctypes.cast(orig, BTN_PROC_TYPE)
        return user32.CallWindowProcW(orig_proc, hw, msg, wp, lp)

    _subclass_procs.append((orig, sub_proc))
    user32.SetWindowLongPtrW(hwnd_btn, -4,
                             ctypes.cast(sub_proc, ctypes.c_void_p))


def create_tooltip_window(parent):
    global g_tooltip_hwnd
    hinstance = kernel32.GetModuleHandleW(None)
    g_tooltip_hwnd = user32.CreateWindowExW(
        WS_EX_TOPMOST,
        'tooltips_class32', None,
        TTS_ALWAYSTIP | TTS_NOPREFIX,
        0, 0, 0, 0,
        parent, None, hinstance, None,
    )
    user32.SendMessageW(g_tooltip_hwnd, TTM_SETDELAYTIME, TTDT_AUTOPOP, 5000)
    user32.SendMessageW(g_tooltip_hwnd, TTM_SETMAXTIPWIDTH, 0, 300)


def add_tooltip(hwnd_btn, text):
    if not g_tooltip_hwnd:
        return
    ti = TOOLINFOW()
    ti.cbSize   = ctypes.sizeof(TOOLINFOW)
    ti.uFlags   = 0x0011
    ti.hwnd     = hwnd_btn
    ti.uId      = hwnd_btn
    ti.lpszText = text

    SendMsg = ctypes.WINFUNCTYPE(
        ctypes.c_void_p,
        wt.HWND, wt.UINT, ctypes.c_void_p, ctypes.c_void_p
    )(ctypes.cast(user32.SendMessageW, ctypes.c_void_p).value)
    SendMsg(g_tooltip_hwnd, TTM_ADDTOOLW, None, ctypes.byref(ti))


ARROW_TIPS = {
    ID_SC_EZI_DESK:   'Create Desktop shortcut\nComfyUI-EZi Desktop',
    ID_SC_SAGE_DESK:  'Create Desktop shortcut\nComfyUI-EZi SA',
    ID_SC_FLASH_DESK: 'Create Desktop shortcut\nComfyUI-EZi FA',
    ID_SC_EZI_BROW:   'Create Desktop shortcut\nComfyUI-EZi',
    ID_SC_SAGE_BROW:  'Create Desktop shortcut\nComfyUI-SA',
    ID_SC_FLASH_BROW: 'Create Desktop shortcut\nComfyUI-FA',
}


def create_button(parent, btn_id, x, y, w, h, is_arrow=False):
    ex_style = WS_EX_NOACTIVATE if is_arrow else 0
    hwnd_btn = user32.CreateWindowExW(
        ex_style, 'BUTTON', '',
        WS_CHILD | WS_VISIBLE | BS_OWNERDRAW,
        x, y, w, h,
        parent, btn_id,
        kernel32.GetModuleHandleW(None), None,
    )
    make_btn_subclass(hwnd_btn, is_arrow=is_arrow)
    if is_arrow:
        tip = ARROW_TIPS.get(btn_id)
        if tip:
            add_tooltip(hwnd_btn, tip)
    return hwnd_btn


# Main Window
@WNDPROC
def wnd_proc(hwnd, msg, wp, lp):
    global g_hwnd, g_hover_btn

    if msg == WM_DESTROY:
        for br  in g_brushes.values(): gdi32.DeleteObject(br)
        for fnt in g_fonts.values():   gdi32.DeleteObject(fnt)
        if g_gradient_bmp:   gdi32.DeleteObject(g_gradient_bmp)
        if g_gradient_memdc: gdi32.DeleteDC(g_gradient_memdc)
        user32.PostQuitMessage(0)
        return 0

    if msg == WM_PAINT:
        ps  = PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))

        # 1. Main background
        user32.FillRect(hdc, ctypes.byref(wt.RECT(0, 0, WIN_W, WIN_H)),
                        get_brush(C_BG))
        # 2. Titlebar
        user32.FillRect(hdc, ctypes.byref(wt.RECT(0, 0, WIN_W, TITLE_H)),
                        get_brush(C_TITLEBAR))
        # 3. Title text (green, aligned with BROWSER column center below)
        old_font = gdi32.SelectObject(hdc, g_fonts['title'])
        gdi32.SetBkMode(hdc, 1)
        gdi32.SetTextColor(hdc, 0xF4D6CD)
        title_cx = (SEP_X + SEP2_X) // 2
        title_rc = wt.RECT(title_cx - WIN_W // 2, 0,
                           title_cx + WIN_W // 2, TITLE_H)
        user32.DrawTextW(hdc, 'ComfyUI EZi Launcher', -1,
                         ctypes.byref(title_rc),
                         DT_CENTER | DT_VCENTER | DT_SINGLELINE)
        gdi32.SelectObject(hdc, old_font)
        # 4. Gradient stripe
        if g_gradient_memdc:
            gdi32.BitBlt(hdc, 0, TITLE_H, WIN_W, STRIPE_H,
                         g_gradient_memdc, 0, 0, SRCCOPY)
        # 5. Section labels - exact match to button colors
        old_font = gdi32.SelectObject(hdc, g_fonts['sec_title'])
        gdi32.SetBkMode(hdc, 1)
        gdi32.SetTextColor(hdc, C_DP_BORDER)
        user32.DrawTextW(hdc, '-- DESKTOP --', -1,
                         ctypes.byref(wt.RECT(12, CONTENT_TOP - SEC_LABEL_H,
                                              175, CONTENT_TOP)),
                         DT_CENTER | DT_SINGLELINE)
        gdi32.SetTextColor(hdc, C_BP_BORDER)
        user32.DrawTextW(hdc, '-- BROWSER --', -1,
                         ctypes.byref(wt.RECT(188, CONTENT_TOP - SEC_LABEL_H,
                                              350, CONTENT_TOP)),
                         DT_CENTER | DT_SINGLELINE)
        gdi32.SetTextColor(hdc, C_UP_BORDER)
        user32.DrawTextW(hdc, '-- UPDATE --', -1,
                         ctypes.byref(wt.RECT(355, CONTENT_TOP - SEC_LABEL_H,
                                              WIN_W - 8, CONTENT_TOP)),
                         DT_CENTER | DT_SINGLELINE)
        gdi32.SelectObject(hdc, old_font)
        # 6. Footer background
        user32.FillRect(hdc,
                        ctypes.byref(wt.RECT(0, WIN_H - FOOTER_H, WIN_W, WIN_H)),
                        get_brush(C_FOOTER_BG))

        user32.EndPaint(hwnd, ctypes.byref(ps))
        return 0

    if msg == WM_ERASEBKGND:
        return 1

    if msg == WM_DRAWITEM:
        dis = ctypes.cast(ctypes.c_void_p(lp),
                          ctypes.POINTER(DRAWITEMSTRUCT)).contents
        if dis.CtlID in SHORTCUT_META:
            draw_arrow_button(dis.hDC, dis.hwndItem, dis.rcItem)
        else:
            draw_button(dis.hDC, dis.hwndItem, dis.rcItem)
        return 1

    if msg == WM_CTLCOLORBTN:
        hw     = ctypes.cast(ctypes.c_void_p(lp), wt.HWND)
        btn_id = user32.GetDlgCtrlID(hw)
        bg     = btn_default_bg(btn_id)
        gdi32.SetBkColor(wt.HDC(wp), bg)
        return ctypes.cast(get_brush(bg), ctypes.c_void_p).value

    if msg == WM_COMMAND:
        btn_id = wp & 0xFFFF
        if btn_id == ID_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if btn_id in SHORTCUT_META:
            main_id = SHORTCUT_META[btn_id][0]
            if main_id in INSTALL_BTN_STATE and is_install_state(main_id):
                return 0
            create_shortcut(btn_id)
            return 0
        action = ACTIONS.get(btn_id)
        if action:
            if is_dimmed_state(btn_id):
                return 0
            action()
            return 0

    if msg == WM_NCHITTEST:
        x  = ctypes.c_short(lp & 0xFFFF).value
        y  = ctypes.c_short((lp >> 16) & 0xFFFF).value
        rc = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rc))
        lx, ly = x - rc.left, y - rc.top
        if 0 <= ly < TITLE_H and 0 <= lx < WIN_W - 30:
            return HTCAPTION
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    if msg == WM_APP_CLOSE:
        user32.DestroyWindow(hwnd)
        return 0

    if msg == WM_ACTIVATE:
        if (wp & 0xFFFF) == 0:
            if g_creating_shortcut:
                return 0
            user32.DestroyWindow(hwnd)
        return 0

    return user32.DefWindowProcW(hwnd, msg, wp, lp)


# Main
def main():
    global g_hwnd

    if sys.platform != 'win32':
        sys.exit(1)

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    hinstance = kernel32.GetModuleHandleW(None)

    g_fonts['title']        = make_font(-15, 600)
    g_fonts['sec_title']    = make_font(-12, 700)
    g_fonts['btn_pri']      = make_font(-16, 700)
    g_fonts['btn_install']  = make_font(-13, 500)
    g_fonts['btn_sec']      = make_font(-14, 500)
    g_fonts['footer']       = make_font(-12, 500)
    g_fonts['close']        = make_font(-12, 600)
    g_fonts['arrow']        = make_font(-14, 600)

    CLASS_NAME = 'ComfyUI_EZi_Launcher'

    wc = WNDCLASSEX()
    wc.cbSize        = ctypes.sizeof(WNDCLASSEX)
    wc.style         = CS_HREDRAW | CS_VREDRAW
    wc.lpfnWndProc   = wnd_proc
    wc.hInstance     = hinstance
    wc.hCursor       = user32.LoadCursorW(None, IDC_ARROW)
    wc.hbrBackground = make_solid_brush(C_BG)
    wc.lpszClassName = CLASS_NAME

    if not user32.RegisterClassExW(ctypes.byref(wc)):
        raise ctypes.WinError()

    x, y = calc_position()

    g_hwnd = user32.CreateWindowExW(
        WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
        CLASS_NAME, 'ComfyUI EZi Launcher',
        WS_POPUP | WS_VISIBLE | WS_CLIPCHILDREN,
        x, y, WIN_W, WIN_H,
        None, None, hinstance, None,
    )
    if not g_hwnd:
        raise ctypes.WinError()

    rgn = gdi32.CreateRoundRectRgn(0, 0, WIN_W + 1, WIN_H + 1, 24, 24)
    user32.SetWindowRgn(g_hwnd, rgn, True)

    create_gradient_cache()
    create_tooltip_window(g_hwnd)

    SEP_X   = 180
    SEP2_X  = 350
    PAD     = 8
    BTN_W   = SEP_X - PAD * 2
    MAIN_W  = BTN_W - ARROW_W - ARROW_GAP

    bw      = SEP2_X - SEP_X - PAD * 2
    MAIN_BW = bw - ARROW_W - ARROW_GAP

    upd_w   = WIN_W - SEP2_X - PAD * 2

    create_button(g_hwnd, ID_CLOSE,
                  WIN_W - 28, (TITLE_H - 22) // 2, 22, 22)

    y_d = CONTENT_TOP

    create_button(g_hwnd, ID_EZI_DESK, PAD, y_d, MAIN_W, BTN_H)
    create_button(g_hwnd, ID_SC_EZI_DESK,
                  PAD + MAIN_W + ARROW_GAP, y_d, ARROW_W, BTN_H, is_arrow=True)
    y_d += BTN_H + BTN_GAP

    if HAS_DESK_SAGE:
        create_button(g_hwnd, ID_SAGE_DESK, PAD, y_d, MAIN_W, BTN_H)
        create_button(g_hwnd, ID_SC_SAGE_DESK,
                      PAD + MAIN_W + ARROW_GAP, y_d, ARROW_W, BTN_H, is_arrow=True)
    else:
        create_button(g_hwnd, ID_SAGE_DESK, PAD, y_d, BTN_W, BTN_H)
    y_d += BTN_H + BTN_GAP

    if HAS_DESK_FLASH:
        create_button(g_hwnd, ID_FLASH_DESK, PAD, y_d, MAIN_W, BTN_H)
        create_button(g_hwnd, ID_SC_FLASH_DESK,
                      PAD + MAIN_W + ARROW_GAP, y_d, ARROW_W, BTN_H, is_arrow=True)
    else:
        create_button(g_hwnd, ID_FLASH_DESK, PAD, y_d, BTN_W, BTN_H)

    y_b = CONTENT_TOP
    bx  = SEP_X + PAD

    create_button(g_hwnd, ID_EZI_BROW, bx, y_b, MAIN_BW, BTN_H)
    create_button(g_hwnd, ID_SC_EZI_BROW,
                  bx + MAIN_BW + ARROW_GAP, y_b, ARROW_W, BTN_H, is_arrow=True)
    y_b += BTN_H + BTN_GAP

    if HAS_BROW_SAGE:
        create_button(g_hwnd, ID_SAGE_BROW, bx, y_b, MAIN_BW, BTN_H)
        create_button(g_hwnd, ID_SC_SAGE_BROW,
                      bx + MAIN_BW + ARROW_GAP, y_b, ARROW_W, BTN_H, is_arrow=True)
    else:
        create_button(g_hwnd, ID_SAGE_BROW, bx, y_b, bw, BTN_H)
    y_b += BTN_H + BTN_GAP

    if HAS_BROW_FLASH:
        create_button(g_hwnd, ID_FLASH_BROW, bx, y_b, MAIN_BW, BTN_H)
        create_button(g_hwnd, ID_SC_FLASH_BROW,
                      bx + MAIN_BW + ARROW_GAP, y_b, ARROW_W, BTN_H, is_arrow=True)
    else:
        create_button(g_hwnd, ID_FLASH_BROW, bx, y_b, bw, BTN_H)

    y_u = CONTENT_TOP
    ux  = SEP2_X + PAD

    create_button(g_hwnd, ID_UPD_EASY,       ux, y_u, upd_w, BTN_H)
    y_u += BTN_H + BTN_GAP
    create_button(g_hwnd, ID_UPD_COMFY,      ux, y_u, upd_w, BTN_H)
    y_u += BTN_H + BTN_GAP
    create_button(g_hwnd, ID_UPD_COMFY_NODE, ux, y_u, upd_w, BTN_H)

    fld_pad   = 8
    fld_gap   = 4
    fld_total = WIN_W - fld_pad * 2
    fld_w     = (fld_total - 3 * fld_gap) // 4
    fld_y     = WIN_H - FOOTER_H + (FOOTER_H - FOOTER_BTN_H) // 2

    fx = fld_pad
    create_button(g_hwnd, ID_FOLD_OUTPUT,    fx, fld_y, fld_w, FOOTER_BTN_H)
    fx += fld_w + fld_gap
    create_button(g_hwnd, ID_FOLD_INPUT,     fx, fld_y, fld_w, FOOTER_BTN_H)
    fx += fld_w + fld_gap
    create_button(g_hwnd, ID_FOLD_WORKFLOWS, fx, fld_y, fld_w, FOOTER_BTN_H)
    fx += fld_w + fld_gap
    last_w = WIN_W - fld_pad - fx
    create_button(g_hwnd, ID_FOLD_MODELS,    fx, fld_y, last_w, FOOTER_BTN_H)

    user32.ShowWindow(g_hwnd, SW_SHOW)
    user32.UpdateWindow(g_hwnd)
    user32.SetForegroundWindow(g_hwnd)

    user32.RedrawWindow(g_hwnd, None, None,
                        RDW_INVALIDATE | RDW_UPDATENOW | RDW_ALLCHILDREN)

    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))

if __name__ == '__main__':
    main()
