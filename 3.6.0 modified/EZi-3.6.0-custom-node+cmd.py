APP_VERSION = "3.6.0"

import sys
import os
import ctypes

try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

def _check_webview2():
    try:
        import winreg
        keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        ]
        for hive, path in keys:
            try:
                winreg.OpenKey(hive, path)
                return True
            except OSError:
                pass
    except Exception:
        pass
    return False

if not _check_webview2():
    url = "https://developer.microsoft.com/en-us/microsoft-edge/webview2/"
    ctypes.windll.user32.MessageBoxW(
        0,
        "WebView2 Runtime was not found on this system.\n\n"
        "ComfyUI-EZi requires the Microsoft Edge WebView2 Runtime to run.\n\n"
        "Click OK to open the download page in your browser.",
        "ComfyUI-EZi - WebView2 Runtime Missing",
        0x10
    )
    os.startfile(url)
    sys.exit(1)

try:
    import webview
except ImportError:
    import sys, subprocess, os
    print("pywebview not found - attempting to install...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pywebview"])
    try:
        import webview
    except ImportError:
        print("ERROR: pywebview could not be installed. Please run:")
        print("  pip install pywebview")
        sys.exit(1)
import subprocess
import threading
import json
import re
import asyncio
import socket
import shlex
import base64
import time

try:
    from aiohttp import web, ClientSession, ClientTimeout, WSMsgType
except ImportError:
    print("aiohttp not found - install it or use ComfyUI's python_embeded")
    sys.exit(1)


CURRENT_SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
ROOT_DIR = os.path.normpath(os.path.join(CURRENT_SCRIPT_DIR, "..", "..", ".."))

ICO_PATH = os.path.join(CURRENT_SCRIPT_DIR, "ComfyUI-EZi-Desktop.ico")
SETTINGS_PATH = os.path.join(CURRENT_SCRIPT_DIR, "ComfyUI-EZi.settings.json")

EZI_UA_TAG = "ComfyUI-EZi-Desktop"
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    f"(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 {EZI_UA_TAG}/{APP_VERSION}"
)

_bat_arg = sys.argv[1] if len(sys.argv) > 1 else "Start ComfyUI.bat"
BAT_FILE = _bat_arg if os.path.isabs(_bat_arg) else os.path.join(ROOT_DIR, _bat_arg)
COMFY_PORT = 8188

COMFYUI_URL_RE = re.compile(
    r'To see the GUI go to:\s+https?://(?:127\.0\.0\.1|localhost|0\.0\.0\.0):(\d+)',
    re.IGNORECASE
)

def _setup_path():
    try:
        subprocess.run(['cmd', '/c', 'chcp', '65001'],
                       capture_output=True, creationflags=0x08000000)
    except Exception:
        pass
    windir = os.environ.get('windir', r'C:\Windows')
    localappdata = os.environ.get('LOCALAPPDATA', '')
    extra = []

    try:
        r = subprocess.run(
            ['cmd', '/c', 'where.exe', 'git.exe'],
            capture_output=True, timeout=5, creationflags=0x08000000
        )
        if r.returncode == 0:
            git_path = r.stdout.decode(errors='replace').strip().splitlines()[0]
            git_dir = os.path.dirname(git_path)
            if git_dir:
                extra.append(git_dir)
    except Exception:
        pass

    extra += [
        os.path.join(windir, 'System32'),
        os.path.join(windir, 'System32', 'WindowsPowerShell', 'v1.0'),
        os.path.join(localappdata, 'Microsoft', 'WindowsApps'),
    ]

    current = os.environ.get('PATH', '')
    additions = [p for p in extra if p and p.lower() not in current.lower()]
    if additions:
        os.environ['PATH'] = ';'.join(additions) + ';' + current

_setup_path()


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


def _get_hwnd(window):
    _vp = ctypes.c_void_p
    try:
        nh = window.native_handle
        if nh:
            return nh
    except Exception:
        pass
    try:
        user = ctypes.windll.user32
        current_pid = os.getpid()
        found = ctypes.c_void_p(0)

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, _vp, ctypes.POINTER(ctypes.c_long))

        def _enum_cb(hwnd, _lparam):
            pid = ctypes.c_ulong(0)
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == current_pid:
                if user.IsWindowVisible(hwnd) and user.GetParent(hwnd) == 0:
                    found.value = hwnd
                    return False
            return True

        user.EnumWindows(WNDENUMPROC(_enum_cb), 0)
        if found.value:
            return found.value
    except Exception:
        pass
    return None

def _set_window_icon(hwnd):
    if not hwnd or not os.path.exists(ICO_PATH):
        return
    try:
        ico = ctypes.windll.user32.LoadImageW(
            None, ICO_PATH, 1, 0, 0, 0x00000010 | 0x00000040
        )
        if ico:
            ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 0, ico)
            ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 1, ico)
    except Exception:
        pass

def _get_desktop():
    try:
        import ctypes.wintypes
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(0, 0x0000, 0, 0, buf)
        path = buf.value
        if path and os.path.isdir(path):
            return path
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Desktop")

def _get_comfy_user_dir():
    user_dir = None
    if os.path.exists(BAT_FILE):
        try:
            with open(BAT_FILE, 'r', encoding='utf-8', errors='replace') as f:
                bat_content = f.read()
            m_env = re.search(r'(?i)set\s+"?COMFY_USER_DIR=([^"\n]+)"?', bat_content)
            if m_env:
                user_dir = m_env.group(1).strip().strip('"')
            else:
                comfy_line = _find_bat_comfy_line(bat_content)
                if comfy_line:
                    m = re.search(r'python_embeded[/\\]python\.exe["\']?\s+(.*)',
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


def _get_comfy_current_theme():
    try:
        user_dir = _get_comfy_user_dir()
        settings_file = os.path.join(user_dir, 'comfy.settings.json')
        if os.path.exists(settings_file):
            with open(settings_file, 'r', encoding='utf-8', errors='replace') as f:
                data = json.load(f)
            palette_id = data.get('Comfy.ColorPalette', '')
            if not palette_id:
                palette_id = 'dark'
            return str(palette_id)
    except Exception:
        pass
    return ''


def _get_builtin_palettes_from_frontend():
    site_pkgs = os.path.join(ROOT_DIR, 'python_embeded', 'Lib', 'site-packages')
    if not os.path.isdir(site_pkgs):
        return {}

    pkg_dir = os.path.join(site_pkgs, 'comfyui_frontend_package')
    if not os.path.isdir(pkg_dir):
        import glob as _glob
        candidates = _glob.glob(os.path.join(site_pkgs, 'comfyui_frontend_package*'))
        pkg_dir = next((c for c in candidates if os.path.isdir(c) and 'dist-info' not in c), None)
        if not pkg_dir:
            return {}

    palettes_dir = os.path.join(pkg_dir, 'static', 'assets', 'palettes')
    if not os.path.isdir(palettes_dir):
        return {}

    palettes = {}
    try:
        for fname in os.listdir(palettes_dir):
            if not fname.endswith('.json'):
                continue
            fpath = os.path.join(palettes_dir, fname)
            try:
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                    data = json.load(f)
                pid = data.get('id')
                colors = data.get('colors', {})
                if pid and colors:
                    palettes[pid] = colors
            except Exception:
                continue
    except Exception:
        return {}

    return palettes


_BUILTIN_PALETTES_CACHE = None

_COMMON_NODE_SLOT = {
    'CLIP': '#FFD500', 'CLIP_VISION': '#A8DADC', 'CLIP_VISION_OUTPUT': '#ad7452',
    'CONDITIONING': '#FFA931', 'CONTROL_NET': '#6EE7B7', 'IMAGE': '#64B5F6',
    'LATENT': '#FF9CF9', 'MASK': '#81C784', 'MODEL': '#B39DDB',
    'STYLE_MODEL': '#C2FFAE', 'VAE': '#FF6E6E', 'NOISE': '#B0B0B0',
    'GUIDER': '#66FFFF', 'SAMPLER': '#ECB4B4', 'SIGMAS': '#CDFFCD', 'TAESD': '#DCC274',
}

_FALLBACK_PALETTES = {
    'dark': {
        'node_slot': _COMMON_NODE_SLOT,
        'litegraph_base': {
            'CLEAR_BACKGROUND_COLOR': '#141414', 'NODE_TITLE_COLOR': '#999',
            'NODE_SELECTED_TITLE_COLOR': '#FFF', 'NODE_TEXT_COLOR': '#AAA',
            'NODE_TEXT_HIGHLIGHT_COLOR': '#FFF', 'NODE_DEFAULT_COLOR': '#333',
            'NODE_DEFAULT_BGCOLOR': '#353535', 'NODE_DEFAULT_BOXCOLOR': '#666',
            'NODE_DEFAULT_SHAPE': 2, 'NODE_BOX_OUTLINE_COLOR': '#FFF',
            'NODE_BYPASS_BGCOLOR': '#FF00FF', 'NODE_ERROR_COLOUR': '#E00',
            'DEFAULT_SHADOW_COLOR': 'rgba(0,0,0,0.5)', 'WIDGET_BGCOLOR': '#222',
            'WIDGET_OUTLINE_COLOR': '#666', 'WIDGET_TEXT_COLOR': '#DDD',
            'WIDGET_SECONDARY_TEXT_COLOR': '#999', 'WIDGET_DISABLED_TEXT_COLOR': '#666',
            'LINK_COLOR': '#9A9', 'EVENT_LINK_COLOR': '#A86', 'CONNECTING_LINK_COLOR': '#AFA',
            'BADGE_FG_COLOR': '#FFF', 'BADGE_BG_COLOR': '#0F1F0F',
        },
        'comfy_base': {
            'fg-color': '#fff', 'bg-color': '#202020', 'comfy-menu-bg': '#171718',
            'comfy-menu-secondary-bg': '#303030', 'comfy-input-bg': '#222',
            'input-text': '#ddd', 'descrip-text': '#999', 'drag-text': '#ccc',
            'error-text': '#ff4444', 'border-color': '#4e4e4e',
            'tr-even-bg-color': '#222', 'tr-odd-bg-color': '#353535',
            'content-bg': '#4e4e4e', 'content-fg': '#fff',
            'content-hover-bg': '#222', 'content-hover-fg': '#fff',
            'bar-shadow': 'rgba(16, 16, 16, 0.5) 0 0 0.5rem',
        },
    },
    'light': {
        'node_slot': _COMMON_NODE_SLOT,
        'litegraph_base': {
            'CLEAR_BACKGROUND_COLOR': '#e0e0e0', 'NODE_TITLE_COLOR': '#222',
            'NODE_SELECTED_TITLE_COLOR': '#000', 'NODE_TEXT_COLOR': '#333',
            'NODE_TEXT_HIGHLIGHT_COLOR': '#000', 'NODE_DEFAULT_COLOR': '#ccc',
            'NODE_DEFAULT_BGCOLOR': '#f5f5f5', 'NODE_DEFAULT_BOXCOLOR': '#999',
            'NODE_DEFAULT_SHAPE': 2, 'NODE_BOX_OUTLINE_COLOR': '#000',
            'NODE_BYPASS_BGCOLOR': '#FF00FF', 'NODE_ERROR_COLOUR': '#E00',
            'DEFAULT_SHADOW_COLOR': 'rgba(0,0,0,0.1)', 'WIDGET_BGCOLOR': '#e0e0e0',
            'WIDGET_OUTLINE_COLOR': '#999', 'WIDGET_TEXT_COLOR': '#333',
            'WIDGET_SECONDARY_TEXT_COLOR': '#666', 'WIDGET_DISABLED_TEXT_COLOR': '#999',
            'LINK_COLOR': '#4CAF50', 'EVENT_LINK_COLOR': '#FF9800', 'CONNECTING_LINK_COLOR': '#2196F3',
            'BADGE_FG_COLOR': '#000', 'BADGE_BG_COLOR': '#e0f0e0',
        },
        'comfy_base': {
            'fg-color': '#222', 'bg-color': '#e9e9e9', 'comfy-menu-bg': '#f5f5f5',
            'comfy-menu-secondary-bg': '#e0e0e0', 'comfy-input-bg': '#d0d0d0',
            'input-text': '#222', 'descrip-text': '#666', 'drag-text': '#888',
            'error-text': '#cc0000', 'border-color': '#bbb',
            'tr-even-bg-color': '#e5e5e5', 'tr-odd-bg-color': '#f0f0f0',
            'content-bg': '#bbb', 'content-fg': '#222',
            'content-hover-bg': '#d0d0d0', 'content-hover-fg': '#000',
            'bar-shadow': 'rgba(0, 0, 0, 0.1) 0 0 0.5rem',
        },
    },
    'solarized': {
        'node_slot': _COMMON_NODE_SLOT,
        'litegraph_base': {
            'CLEAR_BACKGROUND_COLOR': '#002b36', 'NODE_TITLE_COLOR': '#93a1a1',
            'NODE_SELECTED_TITLE_COLOR': '#fdf6e3', 'NODE_TEXT_COLOR': '#839496',
            'NODE_TEXT_HIGHLIGHT_COLOR': '#fdf6e3', 'NODE_DEFAULT_COLOR': '#073642',
            'NODE_DEFAULT_BGCOLOR': '#073642', 'NODE_DEFAULT_BOXCOLOR': '#586e75',
            'NODE_DEFAULT_SHAPE': 2, 'NODE_BOX_OUTLINE_COLOR': '#268bd2',
            'NODE_BYPASS_BGCOLOR': '#FF00FF', 'NODE_ERROR_COLOUR': '#dc322f',
            'DEFAULT_SHADOW_COLOR': 'rgba(0,0,0,0.5)', 'WIDGET_BGCOLOR': '#003847',
            'WIDGET_OUTLINE_COLOR': '#586e75', 'WIDGET_TEXT_COLOR': '#839496',
            'WIDGET_SECONDARY_TEXT_COLOR': '#657b83', 'WIDGET_DISABLED_TEXT_COLOR': '#586e75',
            'LINK_COLOR': '#2aa198', 'EVENT_LINK_COLOR': '#cb4b16', 'CONNECTING_LINK_COLOR': '#859900',
            'BADGE_FG_COLOR': '#fdf6e3', 'BADGE_BG_COLOR': '#073642',
        },
        'comfy_base': {
            'fg-color': '#839496', 'bg-color': '#002b36', 'comfy-menu-bg': '#073642',
            'comfy-menu-secondary-bg': '#003847', 'comfy-input-bg': '#003847',
            'input-text': '#839496', 'descrip-text': '#657b83', 'drag-text': '#586e75',
            'error-text': '#dc322f', 'border-color': '#0d525e',
            'tr-even-bg-color': '#003847', 'tr-odd-bg-color': '#073642',
            'content-bg': '#0d525e', 'content-fg': '#839496',
            'content-hover-bg': '#003847', 'content-hover-fg': '#93a1a1',
            'bar-shadow': 'rgba(0, 0, 0, 0.5) 0 0 0.5rem',
        },
    },
    'arc': {
        'node_slot': _COMMON_NODE_SLOT,
        'litegraph_base': {
            'CLEAR_BACKGROUND_COLOR': '#2f343f', 'NODE_TITLE_COLOR': '#d3dae3',
            'NODE_SELECTED_TITLE_COLOR': '#fff', 'NODE_TEXT_COLOR': '#d3dae3',
            'NODE_TEXT_HIGHLIGHT_COLOR': '#fff', 'NODE_DEFAULT_COLOR': '#383c4a',
            'NODE_DEFAULT_BGCOLOR': '#383c4a', 'NODE_DEFAULT_BOXCOLOR': '#4b5162',
            'NODE_DEFAULT_SHAPE': 2, 'NODE_BOX_OUTLINE_COLOR': '#5294e2',
            'NODE_BYPASS_BGCOLOR': '#FF00FF', 'NODE_ERROR_COLOUR': '#E00',
            'DEFAULT_SHADOW_COLOR': 'rgba(0,0,0,0.5)', 'WIDGET_BGCOLOR': '#404552',
            'WIDGET_OUTLINE_COLOR': '#4b5162', 'WIDGET_TEXT_COLOR': '#d3dae3',
            'WIDGET_SECONDARY_TEXT_COLOR': '#9c9fa8', 'WIDGET_DISABLED_TEXT_COLOR': '#666',
            'LINK_COLOR': '#5294e2', 'EVENT_LINK_COLOR': '#cba6f7', 'CONNECTING_LINK_COLOR': '#5294e2',
            'BADGE_FG_COLOR': '#d3dae3', 'BADGE_BG_COLOR': '#2f343f',
        },
        'comfy_base': {
            'fg-color': '#d3dae3', 'bg-color': '#2f343f', 'comfy-menu-bg': '#383c4a',
            'comfy-menu-secondary-bg': '#404552', 'comfy-input-bg': '#404552',
            'input-text': '#d3dae3', 'descrip-text': '#9c9fa8', 'drag-text': '#9c9fa8',
            'error-text': '#ff4444', 'border-color': '#4b5162',
            'tr-even-bg-color': '#404552', 'tr-odd-bg-color': '#383c4a',
            'content-bg': '#4b5162', 'content-fg': '#d3dae3',
            'content-hover-bg': '#404552', 'content-hover-fg': '#fff',
            'bar-shadow': 'rgba(0, 0, 0, 0.5) 0 0 0.5rem',
        },
    },
    'nord': {
        'node_slot': _COMMON_NODE_SLOT,
        'litegraph_base': {
            'CLEAR_BACKGROUND_COLOR': '#2e3440', 'NODE_TITLE_COLOR': '#d8dee9',
            'NODE_SELECTED_TITLE_COLOR': '#eceff4', 'NODE_TEXT_COLOR': '#d8dee9',
            'NODE_TEXT_HIGHLIGHT_COLOR': '#eceff4', 'NODE_DEFAULT_COLOR': '#3b4252',
            'NODE_DEFAULT_BGCOLOR': '#3b4252', 'NODE_DEFAULT_BOXCOLOR': '#4c566a',
            'NODE_DEFAULT_SHAPE': 2, 'NODE_BOX_OUTLINE_COLOR': '#88c0d0',
            'NODE_BYPASS_BGCOLOR': '#FF00FF', 'NODE_ERROR_COLOUR': '#bf616a',
            'DEFAULT_SHADOW_COLOR': 'rgba(0,0,0,0.5)', 'WIDGET_BGCOLOR': '#434c5e',
            'WIDGET_OUTLINE_COLOR': '#4c566a', 'WIDGET_TEXT_COLOR': '#d8dee9',
            'WIDGET_SECONDARY_TEXT_COLOR': '#81a1c1', 'WIDGET_DISABLED_TEXT_COLOR': '#4c566a',
            'LINK_COLOR': '#88c0d0', 'EVENT_LINK_COLOR': '#d08770', 'CONNECTING_LINK_COLOR': '#a3be8c',
            'BADGE_FG_COLOR': '#eceff4', 'BADGE_BG_COLOR': '#2e3440',
        },
        'comfy_base': {
            'fg-color': '#d8dee9', 'bg-color': '#2e3440', 'comfy-menu-bg': '#3b4252',
            'comfy-menu-secondary-bg': '#434c5e', 'comfy-input-bg': '#434c5e',
            'input-text': '#d8dee9', 'descrip-text': '#81a1c1', 'drag-text': '#81a1c1',
            'error-text': '#bf616a', 'border-color': '#4c566a',
            'tr-even-bg-color': '#434c5e', 'tr-odd-bg-color': '#3b4252',
            'content-bg': '#4c566a', 'content-fg': '#d8dee9',
            'content-hover-bg': '#434c5e', 'content-hover-fg': '#eceff4',
            'bar-shadow': 'rgba(0, 0, 0, 0.5) 0 0 0.5rem',
        },
    },
    'github': {
        'node_slot': _COMMON_NODE_SLOT,
        'litegraph_base': {
            'CLEAR_BACKGROUND_COLOR': '#0d1117', 'NODE_TITLE_COLOR': '#c9d1d9',
            'NODE_SELECTED_TITLE_COLOR': '#f0f6fc', 'NODE_TEXT_COLOR': '#c9d1d9',
            'NODE_TEXT_HIGHLIGHT_COLOR': '#f0f6fc', 'NODE_DEFAULT_COLOR': '#161b22',
            'NODE_DEFAULT_BGCOLOR': '#161b22', 'NODE_DEFAULT_BOXCOLOR': '#30363d',
            'NODE_DEFAULT_SHAPE': 2, 'NODE_BOX_OUTLINE_COLOR': '#388bfd',
            'NODE_BYPASS_BGCOLOR': '#FF00FF', 'NODE_ERROR_COLOUR': '#f85149',
            'DEFAULT_SHADOW_COLOR': 'rgba(0,0,0,0.5)', 'WIDGET_BGCOLOR': '#21262d',
            'WIDGET_OUTLINE_COLOR': '#30363d', 'WIDGET_TEXT_COLOR': '#c9d1d9',
            'WIDGET_SECONDARY_TEXT_COLOR': '#8b949e', 'WIDGET_DISABLED_TEXT_COLOR': '#484f58',
            'LINK_COLOR': '#3fb950', 'EVENT_LINK_COLOR': '#d29922', 'CONNECTING_LINK_COLOR': '#388bfd',
            'BADGE_FG_COLOR': '#f0f6fc', 'BADGE_BG_COLOR': '#0d1117',
        },
        'comfy_base': {
            'fg-color': '#c9d1d9', 'bg-color': '#0d1117', 'comfy-menu-bg': '#161b22',
            'comfy-menu-secondary-bg': '#21262d', 'comfy-input-bg': '#21262d',
            'input-text': '#c9d1d9', 'descrip-text': '#8b949e', 'drag-text': '#8b949e',
            'error-text': '#f85149', 'border-color': '#30363d',
            'tr-even-bg-color': '#21262d', 'tr-odd-bg-color': '#161b22',
            'content-bg': '#30363d', 'content-fg': '#c9d1d9',
            'content-hover-bg': '#21262d', 'content-hover-fg': '#f0f6fc',
            'bar-shadow': 'rgba(0, 0, 0, 0.5) 0 0 0.5rem',
        },
    },
}


def _get_builtin_palettes():
    global _BUILTIN_PALETTES_CACHE
    if _BUILTIN_PALETTES_CACHE is not None:
        return _BUILTIN_PALETTES_CACHE
    from_frontend = _get_builtin_palettes_from_frontend()
    if from_frontend:
        _BUILTIN_PALETTES_CACHE = from_frontend
        return _BUILTIN_PALETTES_CACHE
    _BUILTIN_PALETTES_CACHE = _FALLBACK_PALETTES
    return _BUILTIN_PALETTES_CACHE


def _get_comfy_theme_css_vars():
    try:
        user_dir = _get_comfy_user_dir()
        settings_file = os.path.join(user_dir, 'comfy.settings.json')
        if not os.path.exists(settings_file):
            return {}
        with open(settings_file, 'r', encoding='utf-8', errors='replace') as f:
            data = json.load(f)

        custom_palettes = data.get('Comfy.CustomColorPalettes', {})
        palette_id = data.get('Comfy.ColorPalette', '') or 'dark'

        colors = {}
        if palette_id in custom_palettes:
            colors = custom_palettes[palette_id].get('colors', {})
        else:
            colors = _get_builtin_palettes().get(palette_id, {})

        cb = colors.get('comfy_base', {})
        lg = colors.get('litegraph_base', {})

        def c(key, fallback=''):
            return cb.get(key, fallback) or fallback

        def lg_c(key, fallback=''):
            return lg.get(key, fallback) or fallback

        bg        = c('bg-color', '#202020')
        menu_bg   = c('comfy-menu-bg', bg)
        menu_bg2  = c('comfy-menu-secondary-bg', menu_bg)
        input_bg  = c('comfy-input-bg', bg)
        fg        = c('fg-color', '#cccccc')
        border    = c('border-color', '#444444')
        lg_bg     = lg_c('CLEAR_BACKGROUND_COLOR', bg)
        node_bg   = lg_c('NODE_DEFAULT_BGCOLOR', menu_bg)
        widget_bg = lg_c('WIDGET_BGCOLOR', input_bg)
        node_title = lg_c('NODE_TITLE_COLOR', fg)

        accent = lg_c('NODE_BOX_OUTLINE_COLOR', c('border-color', '#388bfd'))

        def _hex_luminance(hex_color):
            try:
                h = hex_color.lstrip('#')
                if len(h) == 3:
                    h = h[0]*2 + h[1]*2 + h[2]*2
                r, g, b = int(h[0:2],16)/255, int(h[2:4],16)/255, int(h[4:6],16)/255
                def _lin(c): return c/12.92 if c <= 0.04045 else ((c+0.055)/1.055)**2.4
                return 0.2126*_lin(r) + 0.7152*_lin(g) + 0.0722*_lin(b)
            except Exception:
                return 0.5

        def _blend(hex1, hex2, t=0.35):
            try:
                h1, h2 = hex1.lstrip('#'), hex2.lstrip('#')
                if len(h1) == 3: h1 = h1[0]*2 + h1[1]*2 + h1[2]*2
                if len(h2) == 3: h2 = h2[0]*2 + h2[1]*2 + h2[2]*2
                r1,g1,b1 = int(h1[0:2],16), int(h1[2:4],16), int(h1[4:6],16)
                r2,g2,b2 = int(h2[0:2],16), int(h2[2:4],16), int(h2[4:6],16)
                r = int(r1*(1-t) + r2*t)
                g = int(g1*(1-t) + g2*t)
                b = int(b1*(1-t) + b2*t)
                return '#{:02x}{:02x}{:02x}'.format(r,g,b)
            except Exception:
                return hex1

        accent_lum = _hex_luminance(accent)
        if accent_lum > 0.80 or accent_lum < 0.05:
            link_color = lg_c('LINK_COLOR', '')
            if link_color:
                link_lum = _hex_luminance(link_color)
                if 0.05 <= link_lum <= 0.80:
                    accent = link_color
                    accent_lum = link_lum

        if accent_lum >= 0.18:
            accent_bg       = _blend(accent, '#000000', 0.60)
            accent_bg_hover = _blend(accent, '#000000', 0.45)
        else:
            accent_bg       = _blend(accent, '#ffffff', 0.60)
            accent_bg_hover = _blend(accent, '#ffffff', 0.45)

        acc_bg_lum = _hex_luminance(accent_bg)
        text_on_accent = '#ffffff' if acc_bg_lum < 0.35 else '#111111'
        accent_hover   = _blend(accent, '#ffffff', 0.30)

        return {
            '--bg':               lg_bg,
            '--bar-bg':           menu_bg,
            '--border':           border,
            '--border2':          border,
            '--border3':          border,
            '--btn-bg':           node_bg,
            '--btn-bg2':          node_bg,
            '--input-bg':         input_bg,
            '--modal-bg':         menu_bg,
            '--hover-row':        lg_bg,
            '--text':             fg,
            '--text2':            node_title,
            '--text3':            fg,
            '--accent':           accent,
            '--accent-hover':     accent_hover,
            '--accent-bg':        accent_bg,
            '--accent-bg-hover':  accent_bg_hover,
            '--text-on-accent':   text_on_accent,
        }
    except Exception:
        return {}


def _load_settings():
    defaults = {
        "last_save_dir": _get_desktop(),
        "window_maximized": False,
        "window_placement": None,
        "hide_deprecation_warnings": True,
        "console_detached": False,
        "console_placement": None,
        "rec_fps": 30,
        "console_bg_image": "",
        "console_bg_fit": "fit",
        "console_bg_opacity": 0.12,
    }
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("_dpi_aware_version", 0) < 1:
                data["window_placement"] = None
                data["console_placement"] = None
                data["_dpi_aware_version"] = 1
                try:
                    tmp = SETTINGS_PATH + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    os.replace(tmp, SETTINGS_PATH)
                except Exception:
                    pass
            defaults.update(data)
    except Exception:
        pass
    return defaults

def _save_settings(settings):
    try:
        if not settings or not isinstance(settings, dict):
            return
        ALLOWED = ("last_save_dir", "window_maximized", "comfy_storage", "hide_deprecation_warnings", "window_placement", "custom_file_browser", "theme", "console_detached", "console_placement", "_dpi_aware_version", "rec_fps", "console_bg_image", "console_bg_fit", "console_bg_opacity", "cached_comfy_stable_version")
        existing = {}
        try:
            if os.path.exists(SETTINGS_PATH):
                with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if not isinstance(existing, dict):
                    existing = {}
        except Exception:
            pass
        merged = {}
        for k in ALLOWED:
            if k in settings:
                merged[k] = settings[k]
            elif k in existing:
                merged[k] = existing[k]
        if not merged:
            return
        tmp = SETTINGS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
        os.replace(tmp, SETTINGS_PATH)
    except Exception:
        pass

def _get_save_dialog_type():
    try:
        return webview.FileDialog.SAVE
    except AttributeError:
        return webview.SAVE_DIALOG

def save_comfy_storage(self, storage_json):
    try:
        data = json.loads(storage_json)
        if not data or (isinstance(data.get("ls"), dict) and not data["ls"] and isinstance(data.get("ss"), dict) and not data["ss"]):
            return
        self._settings["comfy_storage"] = data
        self._storage_holder[0] = data
        _save_settings(self._settings)
    except Exception:
        pass

SAVE_DIALOG_TYPE = _get_save_dialog_type()

SHELL_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>ComfyUI Launcher</title>
<script>
!function(e,t){if("function"==typeof define&&define.amd)define(["exports"],t);else if("object"==typeof exports&&"string"!=typeof exports.nodeName)t(exports);else{var n={};t(n),e.AnsiUp=n.default}}(this,(function(e){"use strict";var t,n=this&&this.__makeTemplateObject||function(e,t){return Object.defineProperty?Object.defineProperty(e,"raw",{value:t}):e.raw=t,e};!function(e){e[e.EOS=0]="EOS",e[e.Text=1]="Text",e[e.Incomplete=2]="Incomplete",e[e.ESC=3]="ESC",e[e.Unknown=4]="Unknown",e[e.SGR=5]="SGR",e[e.OSCURL=6]="OSCURL"}(t||(t={}));var i=function(){function e(){this.VERSION="5.2.1",this.setup_palettes(),this._use_classes=!1,this.bold=!1,this.italic=!1,this.underline=!1,this.fg=this.bg=null,this._buffer="",this._url_whitelist={http:1,https:1},this._escape_html=!0}return Object.defineProperty(e.prototype,"use_classes",{get:function(){return this._use_classes},set:function(e){this._use_classes=e},enumerable:!1,configurable:!0}),Object.defineProperty(e.prototype,"url_whitelist",{get:function(){return this._url_whitelist},set:function(e){this._url_whitelist=e},enumerable:!1,configurable:!0}),Object.defineProperty(e.prototype,"escape_html",{get:function(){return this._escape_html},set:function(e){this._escape_html=e},enumerable:!1,configurable:!0}),e.prototype.setup_palettes=function(){var e=this;this.ansi_colors=[[{rgb:[0,0,0],class_name:"ansi-black"},{rgb:[187,0,0],class_name:"ansi-red"},{rgb:[0,187,0],class_name:"ansi-green"},{rgb:[187,187,0],class_name:"ansi-yellow"},{rgb:[0,0,187],class_name:"ansi-blue"},{rgb:[187,0,187],class_name:"ansi-magenta"},{rgb:[0,187,187],class_name:"ansi-cyan"},{rgb:[255,255,255],class_name:"ansi-white"}],[{rgb:[85,85,85],class_name:"ansi-bright-black"},{rgb:[255,85,85],class_name:"ansi-bright-red"},{rgb:[0,255,0],class_name:"ansi-bright-green"},{rgb:[255,255,85],class_name:"ansi-bright-yellow"},{rgb:[85,85,255],class_name:"ansi-bright-blue"},{rgb:[255,85,255],class_name:"ansi-bright-magenta"},{rgb:[85,255,255],class_name:"ansi-bright-cyan"},{rgb:[255,255,255],class_name:"ansi-bright-white"}]],this.palette_256=[],this.ansi_colors.forEach((function(t){t.forEach((function(t){e.palette_256.push(t)}))}));for(var t=[0,95,135,175,215,255],n=0;n<6;++n)for(var i=0;i<6;++i)for(var s=0;s<6;++s){var r={rgb:[t[n],t[i],t[s]],class_name:"truecolor"};this.palette_256.push(r)}for(var a=8,l=0;l<24;++l,a+=10){var f={rgb:[a,a,a],class_name:"truecolor"};this.palette_256.push(f)}},e.prototype.escape_txt_for_html=function(e){return this._escape_html?e.replace(/[&<>"']/gm,(function(e){return"&"===e?"&amp;":"<"===e?"&lt;":">"===e?"&gt;":'"'===e?"&quot;":"'"===e?"&#x27;":void 0})):e},e.prototype.append_buffer=function(e){var t=this._buffer+e;this._buffer=t},e.prototype.get_next_packet=function(){var e={kind:t.EOS,text:"",url:""},i=this._buffer.length;if(0==i)return e;var r=this._buffer.indexOf("\x1b");if(-1==r)return e.kind=t.Text,e.text=this._buffer,this._buffer="",e;if(r>0)return e.kind=t.Text,e.text=this._buffer.slice(0,r),this._buffer=this._buffer.slice(r),e;if(0==r){if(i<3)return e.kind=t.Incomplete,e;var a=this._buffer.charAt(1);if("["!=a&&"]"!=a&&"("!=a)return e.kind=t.ESC,e.text=this._buffer.slice(0,1),this._buffer=this._buffer.slice(1),e;if("["==a){if(this._csi_regex||(this._csi_regex=s(n(["\n                        ^                           # beginning of line\n                                                    #\n                                                    # First attempt\n                        (?:                         # legal sequence\n                          \x1b[                      # CSI\n                          ([<-?]?)              # private-mode char\n                          ([d;]*)                    # any digits or semicolons\n                          ([ -/]?               # an intermediate modifier\n                          [@-~])                # the command\n                        )\n                        |                           # alternate (second attempt)\n                        (?:                         # illegal sequence\n                          \x1b[                      # CSI\n                          [ -~]*                # anything legal\n                          ([\0-\x1f:])              # anything illegal\n                        )\n                    "],["\n                        ^                           # beginning of line\n                                                    #\n                                                    # First attempt\n                        (?:                         # legal sequence\n                          \\x1b\\[                      # CSI\n                          ([\\x3c-\\x3f]?)              # private-mode char\n                          ([\\d;]*)                    # any digits or semicolons\n                          ([\\x20-\\x2f]?               # an intermediate modifier\n                          [\\x40-\\x7e])                # the command\n                        )\n                        |                           # alternate (second attempt)\n                        (?:                         # illegal sequence\n                          \\x1b\\[                      # CSI\n                          [\\x20-\\x7e]*                # anything legal\n                          ([\\x00-\\x1f:])              # anything illegal\n                        )\n                    "]))),null===(h=this._buffer.match(this._csi_regex)))return e.kind=t.Incomplete,e;if(h[4])return e.kind=t.ESC,e.text=this._buffer.slice(0,1),this._buffer=this._buffer.slice(1),e;""!=h[1]||"m"!=h[3]?e.kind=t.Unknown:e.kind=t.SGR,e.text=h[2];var l=h[0].length;return this._buffer=this._buffer.slice(l),e}if("]"==a){if(i<4)return e.kind=t.Incomplete,e;if("8"!=this._buffer.charAt(2)||";"!=this._buffer.charAt(3))return e.kind=t.ESC,e.text=this._buffer.slice(0,1),this._buffer=this._buffer.slice(1),e;this._osc_st||(this._osc_st=function(e){for(var t=[],n=1;n<arguments.length;n++)t[n-1]=arguments[n];var i=e.raw[0],s=/^\s+|\s+\n|\s*#[\s\S]*?\n|\n/gm,r=i.replace(s,"");return new RegExp(r,"g")}(n(["\n                        (?:                         # legal sequence\n                          (\x1b\\)                    # ESC \\\n                          |                           # alternate\n                          (\x07)                      # BEL (what xterm did)\n                        )\n                        |                           # alternate (second attempt)\n                        (                           # illegal sequence\n                          [\0-\x06]                 # anything illegal\n                          |                           # alternate\n                          [\b-\x1a]                 # anything illegal\n                          |                           # alternate\n                          [\x1c-\x1f]                 # anything illegal\n                        )\n                    "],["\n                        (?:                         # legal sequence\n                          (\\x1b\\\\)                    # ESC \\\\\n                          |                           # alternate\n                          (\\x07)                      # BEL (what xterm did)\n                        )\n                        |                           # alternate (second attempt)\n                        (                           # illegal sequence\n                          [\\x00-\\x06]                 # anything illegal\n                          |                           # alternate\n                          [\\x08-\\x1a]                 # anything illegal\n                          |                           # alternate\n                          [\\x1c-\\x1f]                 # anything illegal\n                        )\n                    "]))),this._osc_st.lastIndex=0;var f=this._osc_st.exec(this._buffer);if(null===f)return e.kind=t.Incomplete,e;if(f[3])return e.kind=t.ESC,e.text=this._buffer.slice(0,1),this._buffer=this._buffer.slice(1),e;var h,o=this._osc_st.exec(this._buffer);if(null===o)return e.kind=t.Incomplete,e;if(o[3])return e.kind=t.ESC,e.text=this._buffer.slice(0,1),this._buffer=this._buffer.slice(1),e;if(this._osc_regex||(this._osc_regex=s(n(["\n                        ^                           # beginning of line\n                                                    #\n                        \x1b]8;                    # OSC Hyperlink\n                        [ -:<-~]*       # params (excluding ;)\n                        ;                           # end of params\n                        ([!-~]{0,512})        # URL capture\n                        (?:                         # ST\n                          (?:\x1b\\)                  # ESC \\\n                          |                           # alternate\n                          (?:\x07)                    # BEL (what xterm did)\n                        )\n                        ([ -~]+)              # TEXT capture\n                        \x1b]8;;                   # OSC Hyperlink End\n                        (?:                         # ST\n                          (?:\x1b\\)                  # ESC \\\n                          |                           # alternate\n                          (?:\x07)                    # BEL (what xterm did)\n                        )\n                    "],["\n                        ^                           # beginning of line\n                                                    #\n                        \\x1b\\]8;                    # OSC Hyperlink\n                        [\\x20-\\x3a\\x3c-\\x7e]*       # params (excluding ;)\n                        ;                           # end of params\n                        ([\\x21-\\x7e]{0,512})        # URL capture\n                        (?:                         # ST\n                          (?:\\x1b\\\\)                  # ESC \\\\\n                          |                           # alternate\n                          (?:\\x07)                    # BEL (what xterm did)\n                        )\n                        ([\\x20-\\x7e]+)              # TEXT capture\n                        \\x1b\\]8;;                   # OSC Hyperlink End\n                        (?:                         # ST\n                          (?:\\x1b\\\\)                  # ESC \\\\\n                          |                           # alternate\n                          (?:\\x07)                    # BEL (what xterm did)\n                        )\n                    "]))),null===(h=this._buffer.match(this._osc_regex)))return e.kind=t.ESC,e.text=this._buffer.slice(0,1),this._buffer=this._buffer.slice(1),e;e.kind=t.OSCURL,e.url=h[1],e.text=h[2];l=h[0].length;return this._buffer=this._buffer.slice(l),e}if("("==a)return e.kind=t.Unknown,this._buffer=this._buffer.slice(3),e}},e.prototype.ansi_to_html=function(e){this.append_buffer(e);for(var n=[];;){var i=this.get_next_packet();if(i.kind==t.EOS||i.kind==t.Incomplete)break;i.kind!=t.ESC&&i.kind!=t.Unknown&&(i.kind==t.Text?n.push(this.transform_to_html(this.with_state(i))):i.kind==t.SGR?this.process_ansi(i):i.kind==t.OSCURL&&n.push(this.process_hyperlink(i)))}return n.join("")},e.prototype.with_state=function(e){return{bold:this.bold,italic:this.italic,underline:this.underline,fg:this.fg,bg:this.bg,text:e.text}},e.prototype.process_ansi=function(e){for(var t=e.text.split(";");t.length>0;){var n=t.shift(),i=parseInt(n,10);if(isNaN(i)||0===i)this.fg=this.bg=null,this.bold=!1,this.italic=!1,this.underline=!1;else if(1===i)this.bold=!0;else if(3===i)this.italic=!0;else if(4===i)this.underline=!0;else if(22===i)this.bold=!1;else if(23===i)this.italic=!1;else if(24===i)this.underline=!1;else if(39===i)this.fg=null;else if(49===i)this.bg=null;else if(i>=30&&i<38)this.fg=this.ansi_colors[0][i-30];else if(i>=40&&i<48)this.bg=this.ansi_colors[0][i-40];else if(i>=90&&i<98)this.fg=this.ansi_colors[1][i-90];else if(i>=100&&i<108)this.bg=this.ansi_colors[1][i-100];else if((38===i||48===i)&&t.length>0){var s=38===i,r=t.shift();if("5"===r&&t.length>0){var a=parseInt(t.shift(),10);a>=0&&a<=255&&(s?this.fg=this.palette_256[a]:this.bg=this.palette_256[a])}if("2"===r&&t.length>2){var l=parseInt(t.shift(),10),f=parseInt(t.shift(),10),h=parseInt(t.shift(),10);if(l>=0&&l<=255&&f>=0&&f<=255&&h>=0&&h<=255){var o={rgb:[l,f,h],class_name:"truecolor"};s?this.fg=o:this.bg=o}}}}},e.prototype.transform_to_html=function(e){var t=e.text;if(0===t.length)return t;if(t=this.escape_txt_for_html(t),!e.bold&&!e.italic&&!e.underline&&null===e.fg&&null===e.bg)return t;var n=[],i=[],s=e.fg,r=e.bg;e.bold&&n.push("font-weight:bold"),e.italic&&n.push("font-style:italic"),e.underline&&n.push("text-decoration:underline"),this._use_classes?(s&&("truecolor"!==s.class_name?i.push(s.class_name+"-fg"):n.push("color:rgb("+s.rgb.join(",")+")")),r&&("truecolor"!==r.class_name?i.push(r.class_name+"-bg"):n.push("background-color:rgb("+r.rgb.join(",")+")"))):(s&&n.push("color:rgb("+s.rgb.join(",")+")"),r&&n.push("background-color:rgb("+r.rgb+")"));var a="",l="";return i.length&&(a=' class="'+i.join(" ")+'"'),n.length&&(l=' style="'+n.join(";")+'"'),"<span"+l+a+">"+t+"</span>"},e.prototype.process_hyperlink=function(e){var t=e.url.split(":");return t.length<1?"":this._url_whitelist[t[0]]?'<a href="'+this.escape_txt_for_html(e.url)+'">'+this.escape_txt_for_html(e.text)+"</a>":""},e}();function s(e){for(var t=[],n=1;n<arguments.length;n++)t[n-1]=arguments[n];var i=e.raw[0].replace(/^\s+|\s+\n|\s*#[\s\S]*?\n|\n/gm,"");return new RegExp(i)}Object.defineProperty(e,"__esModule",{value:!0}),e.default=i}));
</script>
<style>
  :root {
    --bg:        #0c0e12;
    --bar-bg:    #161b22;
    --border:    #21262d;
    --border2:   #30363d;
    --border3:   #484f58;
    --btn-bg:    #21262d;
    --btn-bg2:   #2d333b;
    --input-bg:  #0d1117;
    --modal-bg:  #161b22;
    --hover-row: #1c2128;
    --text:      #cccccc;
    --text2:     #8b949e;
    --text3:     #e6edf3;
    --accent:         #388bfd;
    --accent-hover:   #58a6ff;
    --accent-bg:      #0d419d;
    --accent-bg-hover:#1158c7;
  }

  :root.theme-pixaroma {
    --bg:        #111111;
    --bar-bg:    #1a1a1a;
    --border:    #252525;
    --border2:   #2e2e2e;
    --border3:   #444444;
    --btn-bg:    #222222;
    --btn-bg2:   #2a2a2a;
    --input-bg:  #0d0d0d;
    --modal-bg:  #1a1a1a;
    --hover-row: #1f1f1f;
    --text:      #cccccc;
    --text2:     #888888;
    --text3:     #e0e0e0;
    --accent:         #e8530a;
    --accent-hover:   #ff7040;
    --accent-bg:      #6e2200;
    --accent-bg-hover:#8a3000;
  }

  :root.theme-light {
    --bg:        #f0f2f5;
    --bar-bg:    #dde1e7;
    --border:    #c8cdd5;
    --border2:   #b0b7c0;
    --border3:   #8a9199;
    --btn-bg:    #e2e6eb;
    --btn-bg2:   #d0d5dc;
    --input-bg:  #ffffff;
    --modal-bg:  #ffffff;
    --hover-row: #d8dce3;
    --text:      #24292f;
    --text2:     #57606a;
    --text3:     #1c2026;
    --accent:         #0969da;
    --accent-hover:   #0550ae;
    --accent-bg:      #0969da;
    --accent-bg-hover:#0550ae;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg); font-family: 'Consolas', 'Courier New', 'Segoe UI Symbol', monospace;
    font-size: 12px; color: var(--text); height: 100vh; display: flex;
    flex-direction: column; overflow: hidden;
  }
  #bar {
    display: flex; align-items: center; background: var(--bar-bg);
    border-bottom: 1px solid var(--border); padding: 0 10px; height: 32px;
    flex-shrink: 0; user-select: none; gap: 8px; z-index: 100000;
    position: relative;
  }
  #dot { width: 8px; height: 8px; border-radius: 50%; background: #f1fa8c; animation: pulse 1.5s infinite; }
  #dot.ready { background: #50fa7b; animation: none; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.25} }
  #status { color: var(--text2); font-size: 11px; }
  #btn {
    display: inline-flex; align-items: center;
    padding: 0 14px; font-family: inherit; font-size: 11px; font-weight: bold;
    border: 1px solid var(--border2); border-radius: 4px; background: var(--btn-bg); color: var(--text2);
    cursor: default; transition: all .2s; order: -1; margin-right: 4px;
    line-height: 1; pointer-events: none; box-sizing: border-box; height: 22px;
  }
  #btn.active {
    border-color: var(--accent); background: var(--accent-bg); color: #fff;
    cursor: pointer; pointer-events: auto;
  }
  #btn.active:hover { background: var(--accent-bg-hover); border-color: var(--accent-hover); }
  #update-btn {
    padding: 3px 12px; font-family: inherit; font-size: 11px; font-weight: bold;
    border: 1px solid #f1fa8c; border-radius: 4px; background: #5a4a00; color: #f1fa8c;
    cursor: pointer; transition: all .2s; line-height: 1; letter-spacing: 0.5px;
  }
  #update-btn:hover { background:#7a6500; border-color:#fff; color:#fff; }
  #scr-btn-wrap { display: inline-flex; align-items: stretch; position: relative; align-self: center; }
  #scr-btn {
    display: inline-flex; align-items: center; gap: 5px;
    padding: 0 8px 0 10px; font-family: inherit; font-size: 11px; font-weight: bold;
    border: 1px solid var(--accent); border-radius: 4px; background: var(--btn-bg); color: var(--accent);
    cursor: pointer; transition: background .15s, border-color .15s, color .15s; line-height: 1; letter-spacing: 0.5px;
    box-sizing: border-box; height: 22px;
  }
  #scr-btn:hover { background: var(--accent-bg); border-color: var(--accent-hover); color: var(--accent-hover); }
  #scr-dropdown {
    display: none; position: absolute; top: calc(100% + 4px); right: 0;
    background: var(--modal-bg); border: 1px solid var(--border2); border-radius: 4px;
    z-index: 200000; min-width: 170px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.4);
  }
  #scr-dropdown.open { display: block; }
  .scr-drop-item {
    display: flex; align-items: center; gap: 8px;
    padding: 7px 12px; font-size: 11px; color: var(--text); cursor: pointer;
    transition: background .1s, color .1s; white-space: nowrap; border-radius: 0;
  }
  .scr-drop-item:hover { background: var(--accent-bg); color: var(--accent-hover); }
  .scr-drop-item:first-child { border-radius: 4px 4px 0 0; }
  .scr-drop-item:last-child  { border-radius: 0 0 4px 4px; }
  #rec-indicator { display: none; }
  #rec-btn {
    padding: 3px 10px; font-family: inherit; font-size: 11px; font-weight: bold;
    border: 1px solid var(--accent); border-radius: 4px; background: var(--btn-bg); color: var(--accent);
    cursor: pointer; transition: all .2s; line-height: 1; letter-spacing: 0.5px;
  }
  #rec-btn:hover { background: var(--accent-bg); border-color: var(--accent-hover); color: var(--accent-hover); }
  #rec-btn.recording {
    border-color: #ff4444; background: #6e2020; color: #ff8888;
    animation: rec-blink 1s ease-in-out infinite;
  }
  #rec-btn.recording:hover { background: #8a2020; border-color: #ff6666; }
  @keyframes rec-blink { 0%,100%{opacity:1} 50%{opacity:0.6} }

  #update-notice {
    position: absolute; left: 50%; transform: translateX(-50%);
    display: none; align-items: center; gap: 8px;
  }
  #out-btn-wrap { display: none; position: relative; align-self: center; }
  #out-btn-wrap.visible { display: inline-flex; align-items: stretch; }
  #out-btn {
    display: inline-flex; align-items: center; gap: 5px;
    padding: 0 8px 0 10px; font-family: inherit; font-size: 11px; font-weight: bold;
    border: 1px solid var(--accent); border-radius: 4px; background: var(--btn-bg); color: var(--accent);
    cursor: pointer; transition: background .15s, border-color .15s, color .15s; line-height: 1; letter-spacing: 0.5px;
    box-sizing: border-box; height: 22px;
  }
  #out-btn:hover { background: var(--accent-bg); border-color: var(--accent-hover); color: var(--accent-hover); }
  #out-btn .out-chevron, #scr-btn .out-chevron { font-size: 16px; opacity: 0.75; }
  .btn-icon { width: 14px; height: 14px; vertical-align: middle; display: inline-block; flex-shrink: 0; }
  #out-dropdown {
    display: none; position: absolute; top: calc(100% + 4px); right: 0;
    background: var(--modal-bg); border: 1px solid var(--border2); border-radius: 4px;
    z-index: 200000; min-width: 165px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.4);
  }
  #out-dropdown.open { display: block; }
  .out-drop-item {
    display: flex; align-items: center; gap: 8px;
    padding: 7px 12px; font-size: 11px; color: var(--text); cursor: pointer;
    transition: background .1s, color .1s;
    white-space: nowrap; border-radius: 0;
  }
  .out-drop-item:hover { background: var(--accent-bg); color: var(--accent-hover); }
  .out-drop-item:first-child { border-radius: 4px 4px 0 0; }
  .out-drop-item:last-child  { border-radius: 0 0 4px 4px; }
  #rec-outline {
    display: none; position: fixed; z-index: 2000000; pointer-events: none;
    box-sizing: border-box;
    outline: 3px dashed #ff4444;
    outline-offset: 0px;
    border-radius: 2px;
    overflow: visible;
  }
  #rec-stop-btn {
    position: absolute; top: -26px; left: 0px;
    background: #ff4444; color: #fff;
    font-size: 10px; font-weight: bold; font-family: Consolas, monospace;
    padding: 2px 9px; border-radius: 3px 3px 0 0;
    letter-spacing: 1px; border: none; cursor: pointer;
    animation: rec-blink 1s ease-in-out infinite;
    pointer-events: auto;
    white-space: nowrap;
  }
  #rec-stop-btn:hover { background: #cc2222; }
  #settings-btn {
    display: inline-flex; align-items: center;
    padding: 0 8px; font-family: inherit; font-size: 11px; font-weight: bold;
    border: 1px solid var(--accent); border-radius: 4px; background: var(--btn-bg); color: var(--accent);
    cursor: pointer; transition: all .2s; line-height: 1; box-sizing: border-box; height: 22px;
  }
  #settings-btn:hover { background: var(--accent-bg); border-color: var(--accent-hover); color: var(--accent-hover); }
  #reload-btn {
    display: inline-flex; align-items: center;
    padding: 0 8px; font-family: inherit; font-size: 14px; font-weight: bold;
    border: 1px solid var(--accent); border-radius: 4px; background: var(--btn-bg); color: var(--accent);
    cursor: pointer; transition: all .2s; line-height: 1; box-sizing: border-box; height: 22px;
  }
  #reload-btn:hover { background: var(--accent-bg); border-color: var(--accent-hover); color: var(--accent-hover); }
  #reload-btn:hover span { display: inline-block; transition: transform 0.3s ease; transform: rotate(90deg); }
  #reload-btn span { display: inline-block; transition: transform 0.3s ease; }
  #reload-btn.spinning span { animation: reloadSpin 0.5s ease; }
  @keyframes reloadSpin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
  .settings-row {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 0; border-bottom: 1px solid var(--border);
  }
  .settings-row:last-child { border-bottom: none; }
  .settings-row label { flex: 1; font-size: 12px; color: var(--text); cursor: pointer; user-select: none; }
  .settings-row input[type=checkbox] { width: 15px; height: 15px; cursor: pointer; accent-color: var(--accent); flex-shrink: 0; }
  .settings-row select {
    background: var(--input-bg); color: var(--text); border: 1px solid var(--border2); border-radius: 4px;
    font-family: inherit; font-size: 11px; padding: 3px 6px; cursor: pointer;
    flex-shrink: 0; max-width: 220px;
  }
  .settings-row select:focus { outline: none; border-color: var(--accent); }
  .settings-row select:disabled { opacity: 0.5; cursor: default; }
  #crop-overlay {
    display: none; position: fixed; inset: 0; z-index: 100001;
    cursor: crosshair; top: 32px;
  }
  #crop-overlay.active { display: block; }
  #crop-shade-t, #crop-shade-b, #crop-shade-l, #crop-shade-r {
    position: absolute; background: rgba(0,0,0,0.55); pointer-events: none;
  }
  #crop-sel {
    position: absolute; border: 1px solid var(--accent-hover);
    box-shadow: 0 0 0 1px rgba(88,166,255,0.3);
    pointer-events: none;
  }
  #crop-hint {
    position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
    background: rgba(0,0,0,0.75); color: #f1fa8c; font-size: 11px;
    padding: 4px 12px; border-radius: 4px; pointer-events: none;
    font-family: Consolas, monospace; white-space: nowrap;
    display: flex; align-items: center;
  }
  #panels { flex: 1; position: relative; overflow: hidden; background: var(--bg); }
  #term-panel, #ui-panel {
    position: absolute; inset: 0;
    transition: transform 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease;
    background: var(--bg);
  }
  #term-panel {
    z-index: 5; overflow-y: auto; padding: 10px 14px;
    user-select: text !important; transform: translateX(0); opacity: 1;
    white-space: pre-wrap; word-break: break-all;
  }
  #ico-bg {
    pointer-events: none; position: absolute;
    {ICO_POS}
    background-image: {ICO_BG};
    background-repeat: {ICO_REPEAT}; background-size: {ICO_SIZE};
    background-position: center;
    opacity: {ICO_OPACITY}; z-index: 6;
  }
  #ui-panel { z-index: 1; opacity: 0; transform: translateX(100vw); pointer-events: none; }
  #ui-frame { width:100%; height:100%; border:none; }
  .ansi-red-fg { color:#ff5555 } .ansi-green-fg { color:#50fa7b } .ansi-yellow-fg { color:#f1fa8c }
  #modal-overlay {
    display: none; position: fixed; inset: 0; z-index: 99999;
    background: rgba(0,0,0,0.6); backdrop-filter: blur(2px);
    align-items: center; justify-content: center;
  }
  #modal-overlay.active { display: flex; }
  #modal-box {
    background: var(--modal-bg); border: 1px solid var(--border2); border-radius: 10px;
    padding: 22px 24px 18px; min-width: 320px; max-width: 508px;
    max-height: 90vh; overflow-y: auto;
    box-shadow: 0 8px 32px rgba(0,0,0,0.6); display: flex; flex-direction: column; gap: 12px;
    animation: modal-in 0.15s ease;
  }
  @keyframes modal-in { from { opacity:0; transform:scale(0.93) translateY(-8px); } to { opacity:1; transform:none; } }
  #modal-icon { font-size: 28px; line-height: 1; }
  #modal-icon:empty { display: none; }
  #modal-title { font-size: 14px; font-weight: bold; color: var(--text3); }
  #modal-title:empty { display: none; }
  #modal-msg { font-size: 12px; color: var(--text2); line-height: 1.6; user-select: text; }
  #modal-btns { display: flex; gap: 10px; justify-content: flex-end; margin-top: 4px; }
  .modal-btn {
    padding: 5px 18px; font-family: inherit; font-size: 11px; font-weight: bold;
    border-radius: 6px; border: 1px solid var(--accent); background: var(--btn-bg); color: var(--accent);
    cursor: pointer; transition: all .15s; line-height: 1.4;
  }
  .modal-btn:hover { background: var(--accent-bg); color: var(--text-on-accent, var(--accent-hover)); border-color: var(--accent-hover); }
  .modal-btn.primary { background: var(--accent-bg); border-color: var(--accent); color: var(--text-on-accent, #fff); }
  .modal-btn.primary:hover { background: var(--accent-bg-hover); border-color: var(--accent-hover); color: var(--text-on-accent, #fff); }
  .modal-btn.danger { background: var(--btn-bg); border-color: #ff5555; color: #ff5555; }
  .modal-btn.danger:hover { background: #6e2020; border-color: #ff7070; color: #fff; }
  .btn-danger {
    border: 1px solid #ff5555 !important; background: var(--btn-bg) !important; color: #ff5555 !important;
    transition: all .2s;
  }
  .btn-danger:hover { background: #6e2020 !important; border-color: #ff7070 !important; color: #fff !important; }
  .stab-btn {
    padding: 4px 8px; font-family: inherit; font-size: 11px; font-weight: bold;
    border: 1px solid var(--accent); border-radius: 4px; background: var(--btn-bg); color: var(--accent);
    cursor: pointer; transition: all .15s; line-height: 1.4; white-space: nowrap;
  }
  .stab-btn:hover { background: var(--accent-bg); color: var(--text-on-accent, var(--accent-hover)); border-color: var(--accent-hover); }
  .stab-btn.active { background: var(--accent-bg); border-color: var(--accent); color: var(--text-on-accent, #fff); }
  .bat-section-title { font-size: 11px; font-weight: bold; color: var(--text2); margin-bottom:4px; }
  .bat-section-title--accent { color: var(--accent-hover); text-transform: uppercase; letter-spacing: 0.6px; font-size: 10px; border-bottom: 1px solid var(--border); padding-bottom: 3px; }
  .bat-row {
    display: flex; align-items: center; gap: 8px;
    padding: 5px 0; border-bottom: 1px solid var(--border);
  }
  .bat-row:last-child { border-bottom: none; }
  .bat-info { flex: 1; display: flex; flex-direction: column; gap: 1px; }
  .bat-label { font-size: 11px; color: var(--accent); font-weight: bold; }
  .bat-desc  { font-size: 10px; color: var(--text2); }
  .bat-run-btn { flex-shrink: 0; padding: 3px 12px; font-size: 11px; }
  .bat-clickable {
    display: flex; align-items: center; gap: 8px;
    padding: 7px 12px; font-size: 11px; color: var(--accent); cursor: pointer;
    transition: background .15s, border-color .15s, color .15s; white-space: nowrap;
    border: 1px solid var(--accent); border-radius: 4px;
    background: var(--btn-bg); margin-bottom: 4px;
    font-family: inherit; font-weight: bold; box-sizing: border-box;
  }
  .bat-clickable:last-child { margin-bottom: 0; }
  .bat-clickable:hover { background: var(--accent-bg); color: var(--accent-hover); border-color: var(--accent-hover); }
  .bat-clickable:hover .bat-label { color: var(--accent-hover); }
  .modal-btn:disabled {
    opacity: 0.4;
    cursor: default !important;
    background: var(--btn-bg) !important;
    border-color: var(--accent) !important;
    color: var(--accent) !important;
  }
</style>
</head>
<body>
<div id="bar"><div id="dot"></div><span id="status">Starting...</span><div id="update-notice" style="display:none;align-items:center;gap:16px;"><div id="ezi-update-notice" style="display:none;align-items:center;gap:8px;"><span id="ezi-update-msg" style="color:#bd93f9;font-size:11px;font-weight:bold;">&#x2B06; EZi update available</span><button onclick="doEziUpdate()" style="padding:3px 12px;font-family:inherit;font-size:11px;font-weight:bold;border:1px solid #bd93f9;border-radius:4px;background:#3a1a6e;color:#bd93f9;cursor:pointer;transition:all .2s;line-height:1;letter-spacing:0.5px;" onmouseover="this.style.background='#5a2a9e'" onmouseout="this.style.background='#3a1a6e'">Update Easy-Install</button></div><div id="comfy-update-notice" style="display:none;align-items:center;gap:8px;"><span id="update-msg" style="color:#f1fa8c;font-size:11px;font-weight:bold;">&#x2B06; ComfyUI update available</span><button id="update-btn" onclick="doUpdate()">Update ComfyUI</button></div></div><button id="btn" onclick="toggle()">ComfyUI ▶</button><button id="reload-btn" title="Reload ComfyUI" style="display:none" onclick="(function(b){ b.classList.add('spinning'); document.getElementById('ui-frame').contentWindow.location.reload(); setTimeout(function(){ b.classList.remove('spinning'); }, 500); })(this)"><span>⟳</span></button><div id="right-btns" style="margin-left:auto;display:flex;align-items:center;gap:8px;"><div id="out-btn-wrap"><button id="out-btn" onclick="toggleOutDropdown(event)" title="Folders"><img class="btn-icon" src="https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/svg/1f4c2.svg"> Folders <span class="out-chevron">&#x25BE;</span></button><div id="out-dropdown"><div class="out-drop-item" onclick="closeAllDropdowns();pywebview.api.open_output_folder()"><img class="btn-icon" src="https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/svg/1f4c2.svg"> Output</div><div class="out-drop-item" onclick="openSubFolder('input')"><img class="btn-icon" src="https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/svg/1f4e5.svg"> Input</div><div class="out-drop-item" onclick="handleCustomNodesClick(event)"><img class="btn-icon" src="https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/svg/1f9e9.svg"> Custom Nodes</div><div class="out-drop-item" onclick="openSubFolder('workflows')"><img class="btn-icon" src="https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/svg/1f5c2.svg"> Workflows</div><div class="out-drop-item" onclick="openSubFolder('models')"><img class="btn-icon" src="https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/svg/1f9e0.svg"> Models</div></div></div><div id="scr-btn-wrap"><button id="scr-btn" onclick="toggleScrDropdown(event)" title="Capture"><img class="btn-icon" src="https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/svg/1f4f7.svg"> Capture <span class="out-chevron">&#x25BE;</span></button><div id="scr-dropdown"><div class="scr-drop-item" onclick="closeAllDropdowns();startCrop('screenshot')"><img class="btn-icon" src="https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/svg/1f4f7.svg"> Screenshot</div><div class="scr-drop-item" onclick="closeAllDropdowns();startCrop('video')"><img class="btn-icon" src="https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/svg/1f3a5.svg"> Record Video</div></div></div><div id="rec-indicator" style="display:none"></div><button id="settings-btn" title="Easy menu">&#x2630;</button></div></div>
<div id="crop-overlay"><div id="crop-shade-t"></div><div id="crop-shade-b"></div><div id="crop-shade-l"></div><div id="crop-shade-r"></div><div id="crop-sel"></div><div id="crop-hint">Click for full window &nbsp;|&nbsp; Drag to select area &nbsp;<button id="crop-cancel-btn" class="btn-danger" style="margin-left:8px;padding:0 10px;height:22px;font-family:inherit;font-size:11px;font-weight:bold;border-radius:4px;cursor:pointer;pointer-events:auto;display:inline-flex;align-items:center;gap:4px;box-sizing:border-box;">✕ Cancel</button></div></div>
<div id="rec-outline"><button id="rec-stop-btn" onclick="stopRecording()">&#x23F9; Stop REC</button></div>
<div id="panels">
  <div id="term-panel"></div>
  <div id="ico-bg"></div>
  <div id="ui-panel"><iframe id="ui-frame" src="about:blank"></iframe></div>
</div>
<div id="modal-overlay">
  <div id="modal-box">
    <div id="modal-icon"></div>
    <div id="modal-title"></div>
    <div id="modal-msg"></div>
    <div id="modal-btns"></div>
  </div>
</div>
<script>
const ansi = new AnsiUp();
const term = document.getElementById('term-panel');
const dot = document.getElementById('dot');
const statusEl = document.getElementById('status');
const btn = document.getElementById('btn');
const uiPanel = document.getElementById('ui-panel');
const termPanel = document.getElementById('term-panel');
const frame = document.getElementById('ui-frame');
const icoBg = document.getElementById('ico-bg');
let lastCR = null, uiLoaded = false, showingUI = false, _toggling = false;

const settingsDefaults = { hideDeprecationWarnings: true, customFileBrowser: '', theme: 'dark' };
let eziSettings = Object.assign({}, settingsDefaults);
function saveEziSettings() {
  try { pywebview.api.save_ui_settings(JSON.stringify(eziSettings)); } catch(e) {}
}
function applyTheme(theme) {
  document.documentElement.classList.remove('theme-pixaroma', 'theme-light', 'theme-comfyui');
  if (theme === 'pixaroma') document.documentElement.classList.add('theme-pixaroma');
  else if (theme === 'light') document.documentElement.classList.add('theme-light');
  else if (theme === 'comfyui') {
    var vars = (eziSettings.comfyThemeVars && typeof eziSettings.comfyThemeVars === 'object')
      ? eziSettings.comfyThemeVars : {};
    var cssBody = Object.entries(vars).map(function(kv){ return kv[0]+':'+kv[1]; }).join(';');
    var styleId = 'ezi-comfyui-theme-style';
    var el = document.getElementById(styleId);
    if (!el) { el = document.createElement('style'); el.id = styleId; document.head.appendChild(el); }
    el.textContent = ':root.theme-comfyui{' + cssBody + '}';
    document.documentElement.classList.add('theme-comfyui');
  }
}

let _settingsOpenId = 0;
function show_settings() {
  const _myId = ++_settingsOpenId;
  function _stale() { return _myId !== _settingsOpenId; }

  try {
    pywebview.api.get_ui_settings().then(function(s) {
      if (_stale() || !s) return;
      try {
        var fresh = JSON.parse(s);
        eziSettings.comfyTheme     = fresh.comfyTheme;
        eziSettings.comfyThemeVars = fresh.comfyThemeVars;
        if ((eziSettings.theme || 'dark') === 'comfyui') {
          applyTheme('comfyui');
        }
        var hasVars = fresh.comfyThemeVars && Object.keys(fresh.comfyThemeVars).length > 0;
        var varsChanged = JSON.stringify(fresh.comfyThemeVars) !== JSON.stringify(eziSettings.comfyThemeVars);
        if (varsChanged && (eziSettings.theme || 'dark') === 'comfyui') {
          applyTheme('comfyui');
        }
        var opt = document.querySelector('#set-theme option[value="comfyui"]');
        if (opt) {
          opt.textContent = 'ComfyUI' + (fresh.comfyTheme ? ' (' + fresh.comfyTheme + ')' : '');
          opt.disabled = !(fresh.comfyTheme && hasVars);
        }
        var span = document.getElementById('comfy-theme-value');
        if (span) {
          span.innerHTML = (fresh.comfyTheme && fresh.comfyTheme.trim())
            ? fresh.comfyTheme.trim()
            : '<span style="color:var(--text3,#666);font-style:italic">not found</span>';
        }
        var pathSpan = document.getElementById('comfy-settings-path');
        if (pathSpan && fresh.comfySettingsPath) {
          pathSpan.textContent = fresh.comfySettingsPath;
          pathSpan.title       = fresh.comfySettingsPath;
        }
      } catch(e) {}
    }).catch(function(){});
  } catch(e) {}

  function _sysRow(label, value, color) {
    return `<tr><td style="color:#8b949e;padding:2px 10px 2px 0;white-space:nowrap">${label}</td>` +
           `<td style="color:${color||'#f1fa8c'};font-weight:bold">${value}</td></tr>`;
  }
  function _sysRowColor(label, value, color) { return _sysRow(label, value, color); }

  const _tabDisplay = {advanced:'flex'};
  function _showTab(name) {
    ['general','addons','torch','tools','advanced'].forEach(t => {
      document.getElementById('stab-'+t).style.display = (t===name)?(_tabDisplay[t]||'block'):'none';
      document.getElementById('stabtn-'+t).classList.toggle('active', t===name);
    });
  }

  const tabBar = `<div style="margin-bottom:14px;border-bottom:1px solid var(--border);padding-bottom:8px">
    <div style="display:flex;gap:4px;margin-bottom:6px;align-items:center;">
      <button id="stabtn-general"  class="stab-btn active">System Info</button>
      <button id="stabtn-addons"   class="stab-btn">Add-ons</button>
      <button id="stabtn-torch"    class="stab-btn">Torch Pack</button>
      <button id="stabtn-tools"    class="stab-btn">Tools</button>
      <button id="stabtn-advanced" class="stab-btn">Advanced</button>
      <button onclick="pywebview.api.open_url('https://github.com/Tavris1/ComfyUI-Easy-Install')"
              title="https://github.com/Tavris1/ComfyUI-Easy-Install"
              style="padding:4px 14px;font-family:inherit;font-size:11px;font-weight:bold;border:1px solid var(--accent);border-radius:4px;background:var(--btn-bg);color:var(--accent);cursor:pointer;transition:all .15s;line-height:1.4;white-space:nowrap;"
              onmouseover="this.style.background='var(--accent-bg)';this.style.borderColor='var(--accent-hover)';this.style.color='var(--accent-hover)';"
              onmouseout="this.style.background='var(--btn-bg)';this.style.borderColor='var(--accent)';this.style.color='var(--accent)';">
         🏠 Home page
      </button>
    </div>
  </div>`;

  const tabGeneral = `<div id="stab-general">
    <div style="margin-bottom:10px">
      <span id="sysinfo-loading" style="font-size:11px;font-weight:bold;color:#f1fa8c;animation:sysinfo-pulse 0.9s ease-in-out infinite">Loading...</span>
      <style>@keyframes sysinfo-pulse{0%,100%{opacity:1;text-shadow:0 0 8px #f1fa8c}50%{opacity:0.25;text-shadow:none}}</style>
      <div id="sysinfo-table"></div>
    </div>
    <div style="margin-top:14px;border:1px solid var(--accent);border-radius:6px;overflow:hidden">
      <div style="font-size:10px;font-weight:bold;text-transform:uppercase;letter-spacing:.06em;color:var(--text2);background:var(--section-bg,var(--input-bg));padding:4px 10px;border-bottom:1px solid var(--border2)">Package Cache</div>
      <div style="padding:8px 10px;display:flex;flex-direction:column;gap:6px">
        <div id="cache-warning" style="display:none;align-items:center;gap:6px;padding:5px 8px;border-radius:4px;background:rgba(255,184,0,0.08);border:1px solid rgba(255,184,0,0.30)">
          <span style="font-size:13px;line-height:1">⚠️</span>
          <span style="font-size:10px;color:#f1c14a;line-height:1.4">Clearing cache will force full package re-download on next install.<br>Only clear if you need to free up disk space.</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px;font-size:11px">
          <span style="color:var(--text2);flex:none;width:28px;font-weight:bold">pip</span>
          <span id="pip-cache-size" style="color:var(--text);min-width:60px">
            <span style="color:var(--text2);font-style:italic">measuring…</span>
          </span>
          <button id="pip-cache-clear-btn" disabled
            style="padding:3px 12px;font-family:inherit;font-size:11px;font-weight:bold;border:1px solid var(--border);border-radius:4px;background:var(--btn-bg);color:var(--text2);cursor:default;transition:all .15s;line-height:1.4;flex:none;opacity:0.35">Clear</button>
        </div>
        <div style="display:flex;align-items:center;gap:8px;font-size:11px">
          <span style="color:var(--text2);flex:none;width:28px;font-weight:bold">uv</span>
          <span id="uv-cache-size" style="color:var(--text);min-width:60px">
            <span style="color:var(--text2);font-style:italic">measuring…</span>
          </span>
          <button id="uv-cache-clear-btn" disabled
            style="padding:3px 12px;font-family:inherit;font-size:11px;font-weight:bold;border:1px solid var(--border);border-radius:4px;background:var(--btn-bg);color:var(--text2);cursor:default;transition:all .15s;line-height:1.4;flex:none;opacity:0.35">Clear</button>
        </div>
      </div>
    </div>
  </div>`;

  function _batBtn(label, path, desc) {
    return `<div class="bat-clickable" data-bat="${path.replace(/"/g,'&quot;')}" title="${desc.replace(/"/g,'&quot;')}">
      <span class="bat-label">${label}</span>
    </div>`;
  }
  const tabAddons = `<div id="stab-addons" style="display:none">
    ${_batBtn('Easy-Models-Linker', '.\\\\Add-Ons\\\\1. Easy-Models-Linker.bat', 'Link existing MODELS folder via extra_model_paths.yaml')}
    ${_batBtn('FlashAttention v2.8.3', '.\\\\Add-Ons\\\\FlashAttention.bat', 'Installs FlashAttention v2.8.3')}
    ${_batBtn('InsightFace', '.\\\\Add-Ons\\\\Insightface.bat', 'Installs InsightFace')}
    ${_batBtn('Nunchaku', '.\\\\Add-Ons\\\\Nunchaku.bat', 'Installs Nunchaku')}
    ${_batBtn('SageAttention v2.2.0 + v3', '.\\\\Add-Ons\\\\SageAttention-Multi (v2.2.0 and v3).bat', 'Installs both SageAttention v2.2.0 and v3')}
    ${_batBtn('Trellis 2.0', '.\\\\Add-Ons\\\\Trellis2 (requires Torch 2.8.0+cu128).bat', 'Installs Trellis 2.0 + model (requires Torch 2.8.0+cu128)')}
  </div>`;

  const tabTorch = `<div id="stab-torch" style="display:none">
    ${_batBtn('Torch 2.7.1+cu128', '.\\\\Add-Ons\\\\Torch-Pack\\\\Torch 2.7.1+cu128.bat', 'Switch to Torch 2.7.1+cu128')}
    ${_batBtn('Torch 2.8.0+cu128', '.\\\\Add-Ons\\\\Torch-Pack\\\\Torch 2.8.0+cu128.bat', 'Switch to Torch 2.8.0+cu128')}
    ${_batBtn('Torch 2.9.1+cu130', '.\\\\Add-Ons\\\\Torch-Pack\\\\Torch 2.9.1+cu130 (default).bat', 'Switch to Torch 2.9.1+cu130 (default)')}
  </div>`;

  const tabTools = `<div id="stab-tools" style="display:none">
    ${_batBtn('Easy-model2GGUF', '.\\\\Add-Ons\\\\Tools\\\\Easy-model2GGUF.bat', 'Convert & quantize models to GGUF (Q2_K - Q8_0)')}
    ${_batBtn('Long Paths Enabler', '.\\\\Add-Ons\\\\Tools\\\\Long-Paths-Enabler.bat', 'Enables Long Paths in Windows 10/11')}
    ${_batBtn('Toggle DynamicVRAM', '.\\\\Add-Ons\\\\Tools\\\\Toggle-DynamicVRAM.bat', 'Toggles --disable-dynamic-vram in startup files')}
  </div>`;

  const _comfyThemeDisplay = (eziSettings.comfyTheme && eziSettings.comfyTheme.trim())
    ? eziSettings.comfyTheme.trim()
    : '<span style="color:var(--text3,#666);font-style:italic">not found</span>';

  let _cp = Object.assign({input:'', output:'', user:''}, eziSettings.customPaths || {});

  function _cpAutoDetect(inp, out, usr) {
    if (!inp && !out && !usr) return null;
    const dirs = [inp, out, usr].filter(Boolean);
    if (!dirs.length) return null;
    const parents = dirs.map(d => {
      const norm = d.replace(/\\\\/g,'\\');
      const parts = norm.replace(/[/\\]+$/, '').split(/[/\\]/);
      parts.pop();
      return parts.join('\\');
    });
    const first = parents[0];
    if (parents.every(p => p.toLowerCase() === first.toLowerCase())) return first;
    return null;
  }

  let _cpDetectedBase = _cpAutoDetect(_cp.input, _cp.output, _cp.user);
  let _cpDetectedBase_live = _cpDetectedBase;
  const _cpUseBase = !!_cpDetectedBase;

  function _cpBrowseBtn(id) {
    return `<button id="${id}" title="Browse"
      style="flex-shrink:0;padding:3px 10px;font-family:inherit;font-size:11px;font-weight:bold;border:1px solid var(--accent);border-radius:4px;background:var(--btn-bg);color:var(--accent);cursor:pointer;transition:all .15s;line-height:1.4;white-space:nowrap;"
      onmouseover="this.style.background='var(--accent-bg)';this.style.borderColor='var(--accent-hover)';this.style.color='var(--accent-hover)';"
      onmouseout="this.style.background='var(--btn-bg)';this.style.borderColor='var(--accent)';this.style.color='var(--accent)';">Browse</button>`;
  }

  function _cpClearBtn(id) {
    return `<button id="${id}" title="Clear (use ComfyUI default)"
      style="flex-shrink:0;padding:3px 7px;font-family:inherit;font-size:12px;font-weight:bold;border:1px solid var(--border3);border-radius:4px;background:var(--btn-bg);color:var(--text2);cursor:pointer;transition:all .15s;line-height:1.4;"
      onmouseover="this.style.borderColor='#ff5555';this.style.color='#ff5555';"
      onmouseout="this.style.borderColor='var(--border3)';this.style.color='var(--text2)';">&#x2715;</button>`;
  }

  function _cpInput(id, val, placeholder) {
    return `<input type="text" id="${id}" value="${(val||'').replace(/"/g,'&quot;')}"
      placeholder="${placeholder}"
      style="flex:1;min-width:0;background:var(--input-bg);color:var(--text);border:1px solid var(--border2);border-radius:4px;font-family:inherit;font-size:11px;padding:3px 6px;outline:none;"
      onfocus="this.style.borderColor='var(--accent)'" onblur="this.style.borderColor='var(--border2)'">`;
  }

  const tabAdvanced = `<div id="stab-advanced" style="display:none;flex-direction:column;gap:8px">

    <!-- ── Interface ── -->
    <div style="border:1px solid var(--accent);border-radius:6px;overflow:hidden">
      <div style="font-size:10px;font-weight:bold;text-transform:uppercase;letter-spacing:.06em;color:var(--text2);background:var(--section-bg,var(--input-bg));padding:4px 10px;border-bottom:1px solid var(--border2)">Interface</div>
      <div style="padding:6px 10px;display:flex;flex-direction:column;gap:2px">
        <div class="settings-row">
          <label for="set-theme" style="cursor:default">Theme</label>
          <select id="set-theme" style="max-width:180px">
            <option value="dark"     ${(eziSettings.theme||'dark')==='dark'     ?'selected':''}>EZi Dark</option>
            <option value="pixaroma" ${(eziSettings.theme||'dark')==='pixaroma' ?'selected':''}>Pixaroma</option>
            <option value="light"    ${(eziSettings.theme||'dark')==='light'    ?'selected':''}>EZi Light</option>
            <option value="comfyui"  ${(eziSettings.theme||'dark')==='comfyui'  ?'selected':''}${(!eziSettings.comfyTheme||!eziSettings.comfyThemeVars||!Object.keys(eziSettings.comfyThemeVars||{}).length)?'disabled':''}>ComfyUI${eziSettings.comfyTheme?' ('+eziSettings.comfyTheme+')':''}</option>
          </select>
        </div>
        <div class="settings-row">
          <input type="checkbox" id="set-hide-deprecation" ${eziSettings.hideDeprecationWarnings ? 'checked' : ''}>
          <label for="set-hide-deprecation">Hide deprecation warnings in console</label>
        </div>
        <div class="settings-row" style="gap:6px">
          <label style="cursor:default;flex:none;white-space:nowrap">Output folder browser</label>
          ${_cpInput('set-file-browser', eziSettings.customFileBrowser||'', 'Windows Explorer (default)')}
          ${_cpClearBtn('set-file-browser-clear')}
          ${_cpBrowseBtn('set-file-browser-btn')}
        </div>
        <div class="settings-row">
          <input type="checkbox" id="set-detach-console" ${eziSettings.consoleDetached ? 'checked' : ''}>
          <label for="set-detach-console">Detach console to standalone cmd window</label>
        </div>
        <div class="settings-row" style="gap:6px;align-items:center">
          <label style="cursor:default;flex:none;white-space:nowrap">Console BG</label>
          ${_cpInput('set-con-bg', eziSettings.consoleBgImage||'', 'None (use icon)')}
          ${_cpClearBtn('set-con-bg-clear')}
          ${_cpBrowseBtn('set-con-bg-btn')}
          <select id="set-con-bg-fit" style="flex-shrink:0;width:76px;background:var(--input-bg);color:var(--text);border:1px solid var(--border2);border-radius:4px;font-family:inherit;font-size:11px;padding:2px 4px;cursor:pointer" onfocus="this.style.borderColor='var(--accent)'" onblur="this.style.borderColor='var(--border2)'">
            <option value="fit"     ${(eziSettings.consoleBgFit||'fit')==='fit'     ?'selected':''}>Fit</option>
            <option value="stretch" ${(eziSettings.consoleBgFit||'fit')==='stretch' ?'selected':''}>Stretch</option>
            <option value="tile"    ${(eziSettings.consoleBgFit||'fit')==='tile'    ?'selected':''}>Tile</option>
            <option value="center"  ${(eziSettings.consoleBgFit||'fit')==='center'  ?'selected':''}>Center</option>
          </select>
          <input type="range" id="set-con-bg-opacity"
            min="3" max="50" step="1"
            value="${Math.round((+(eziSettings.consoleBgOpacity||0.12))*100)}"
            style="flex-shrink:0;width:68px;accent-color:var(--accent);cursor:pointer"
            title="Opacity">
          <span id="set-con-bg-opacity-val" style="flex-shrink:0;font-size:10px;color:var(--text2);min-width:28px;text-align:right">${Math.round((+(eziSettings.consoleBgOpacity||0.12))*100)}%</span>
        </div>
      </div>
    </div>

    <!-- ── Custom Input, Output & User Folders ── -->
    <div style="border:1px solid var(--accent);border-radius:6px;overflow:hidden">
      <div style="font-size:10px;font-weight:bold;text-transform:uppercase;letter-spacing:.06em;color:var(--text2);background:var(--section-bg,var(--input-bg));padding:4px 10px;border-bottom:1px solid var(--border2)">Custom Input, Output & User Folders</div>
      <div style="padding:6px 10px;display:flex;flex-direction:column;gap:2px">
        <div class="settings-row" style="gap:6px;margin-bottom:2px">
          <input type="checkbox" id="set-cp-base-mode" ${_cpUseBase?'checked':''}>
          <label for="set-cp-base-mode" style="cursor:pointer;white-space:nowrap;flex:none">Same base folder for all</label>
        </div>
        <!-- BASE MODE -->
        <div id="cp-base-wrap" style="display:${_cpUseBase?'flex':'none'};flex-direction:column;gap:2px">
          <div class="settings-row" style="gap:6px">
            <label style="cursor:default;flex:none;white-space:nowrap;min-width:52px">Base</label>
            ${_cpInput('set-cp-base', _cpDetectedBase||'', 'e.g. C:\\AI')}
            ${_cpClearBtn('set-cp-base-clear')}
            ${_cpBrowseBtn('set-cp-base-btn')}
          </div>
          <div id="cp-base-preview" style="font-size:10px;color:var(--text2);padding:2px 0 2px 58px;line-height:1.7"></div>
        </div>
        <!-- CUSTOM MODE -->
        <div id="cp-custom-wrap" style="display:${_cpUseBase?'none':'flex'};flex-direction:column;gap:2px">
          <div class="settings-row" style="gap:6px">
            <label style="cursor:default;flex:none;white-space:nowrap;min-width:52px">Input</label>
            ${_cpInput('set-cp-input', _cp.input||'', 'Default (ComfyUI/input)')}
            ${_cpClearBtn('set-cp-input-clear')}
            ${_cpBrowseBtn('set-cp-input-btn')}
          </div>
          <div class="settings-row" style="gap:6px">
            <label style="cursor:default;flex:none;white-space:nowrap;min-width:52px">Output</label>
            ${_cpInput('set-cp-output', _cp.output||'', 'Default (ComfyUI/output)')}
            ${_cpClearBtn('set-cp-output-clear')}
            ${_cpBrowseBtn('set-cp-output-btn')}
          </div>
          <div class="settings-row" style="gap:6px">
            <label style="cursor:default;flex:none;white-space:nowrap;min-width:52px">User</label>
            ${_cpInput('set-cp-user', _cp.user||'', 'Default (ComfyUI/user)')}
            ${_cpClearBtn('set-cp-user-clear')}
            ${_cpBrowseBtn('set-cp-user-btn')}
          </div>
        </div>
      </div>
    </div>

    <!-- ── Versions ── -->
    <div style="border:1px solid var(--accent);border-radius:6px;overflow:hidden">
      <div style="font-size:10px;font-weight:bold;text-transform:uppercase;letter-spacing:.06em;color:var(--text2);background:var(--section-bg,var(--input-bg));padding:4px 10px;border-bottom:1px solid var(--border2)">Versions</div>
      <div style="padding:6px 10px;display:flex;flex-direction:column;gap:2px">
        <div class="settings-row">
          <label for="set-comfy-ver" style="cursor:default">ComfyUI version</label>
          <select id="set-comfy-ver" disabled><option>Loading...</option></select>
        </div>
        <div id="comfy-fe-hint" style="display:none;padding:2px 0 4px 0;font-size:11px;color:#8b949e">
          &#x2139; Requires frontend: <span id="comfy-fe-hint-ver" style="color:#f1fa8c;font-weight:bold"></span>
          <br><span style="color:#555">(your selected frontend version is older than required)</span>
        </div>
        <div class="settings-row">
          <label for="set-frontend-ver" style="cursor:default">ComfyUI Frontend version</label>
          <select id="set-frontend-ver" disabled><option>Loading...</option></select>
        </div>
        <div id="fe-comfy-hint" style="display:none;padding:2px 0 4px 0;font-size:11px;color:#8b949e">
          &#x2139; Selected ComfyUI requires: <span id="fe-comfy-hint-ver" style="color:#f1fa8c;font-weight:bold"></span>
          <br><span style="color:#555">(your selected frontend version is older than required)</span>
        </div>
      </div>
    </div>

  </div>`;

  let _initialHideDeprecation = eziSettings.hideDeprecationWarnings;
  let _initialFileBrowser = eziSettings.customFileBrowser || '';
  let _initialTheme = eziSettings.theme || 'dark';
  let _initialDetachConsole = !!eziSettings.consoleDetached;
  let _initialCpInput  = _cp.input  || '';
  let _initialCpOutput = _cp.output || '';
  let _initialCpUser   = _cp.user   || '';
  let _initialConBgImage   = eziSettings.consoleBgImage   || '';
  let _initialConBgFit     = eziSettings.consoleBgFit     || 'fit';
  let _initialConBgOpacity = Math.round((+(eziSettings.consoleBgOpacity||0.12))*100);

  function browseForFileBrowser() {
    pywebview.api.browse_for_exe().then(function(path) {
      if (path) {
        document.getElementById('set-file-browser').value = path;
        _checkChanges();
      }
    }).catch(function(){});
  }

  function _cpGetSubfolderName(fullPath, base) {
    if (!fullPath || !base) return '';
    const n = fullPath.replace(/\//g, '\\');
    const b = base.replace(/\//g, '\\').replace(/\\+$/, '');
    if (n.toLowerCase().startsWith(b.toLowerCase() + '\\')) {
      return n.slice(b.length + 1);
    }
    return fullPath;
  }

  function _cpUpdatePreview() {
    const base = (document.getElementById('set-cp-base') || {}).value || '';
    const prev = document.getElementById('cp-base-preview');
    if (!prev) return;
    if (!base.trim()) {
      prev.innerHTML = '<span style="color:var(--text2)">input → &lt;base&gt;\\input &nbsp; output → &lt;base&gt;\\output &nbsp; user → &lt;base&gt;\\user</span>';
      return;
    }
    const b = base.trim().replace(/\\+$/, '');
    const inSub  = _cpGetSubfolderName(_cp.input,  _cpDetectedBase_live) || 'input';
    const outSub = _cpGetSubfolderName(_cp.output, _cpDetectedBase_live) || 'output';
    const usrSub = _cpGetSubfolderName(_cp.user,   _cpDetectedBase_live) || 'user';
    prev.innerHTML =
      '<span style="color:var(--text2)">' +
      'input → <b style="color:var(--text)">' + b + '\\' + inSub  + '</b>' +
      ' &nbsp; output → <b style="color:var(--text)">' + b + '\\' + outSub + '</b>' +
      ' &nbsp; user → <b style="color:var(--text)">'   + b + '\\' + usrSub  + '</b>' +
      '</span>';
  }

  function _cpGetEffectivePaths() {
    const baseModeChk = document.getElementById('set-cp-base-mode');
    if (baseModeChk && baseModeChk.checked) {
      const base = (document.getElementById('set-cp-base') || {}).value || '';
      const b = base.trim().replace(/\\+$/, '');
      if (!b) return {input:'', output:'', user:''};
      const inSub  = _cpGetSubfolderName(_cp.input,  _cpDetectedBase_live) || 'input';
      const outSub = _cpGetSubfolderName(_cp.output, _cpDetectedBase_live) || 'output';
      const usrSub = _cpGetSubfolderName(_cp.user,   _cpDetectedBase_live) || 'user';
      return {
        input:  b + '\\' + inSub,
        output: b + '\\' + outSub,
        user:   b + '\\' + usrSub,
      };
    }
    return {
      input:  (document.getElementById('set-cp-input')  || {}).value || '',
      output: (document.getElementById('set-cp-output') || {}).value || '',
      user:   (document.getElementById('set-cp-user')   || {}).value || '',
    };
  }

  function _cpPathsChanged() {
    const ep = _cpGetEffectivePaths();
    return ep.input.trim()  !== _initialCpInput  ||
           ep.output.trim() !== _initialCpOutput ||
           ep.user.trim()   !== _initialCpUser;
  }

  function browseForFolder(targetInputId) {
    pywebview.api.browse_for_folder().then(function(path) {
      if (path) {
        const el = document.getElementById(targetInputId);
        if (el) { el.value = path; el.dispatchEvent(new Event('input')); }
        if (targetInputId === 'set-cp-base') _cpUpdatePreview();
        _checkChanges();
      }
    }).catch(function(){});
  }

  function _updateVersionHints() {
    const selComfy = document.getElementById('set-comfy-ver');
    const selFe    = document.getElementById('set-frontend-ver');
    const comfyHint    = document.getElementById('comfy-fe-hint');
    const comfyHintVer = document.getElementById('comfy-fe-hint-ver');
    const feHint    = document.getElementById('fe-comfy-hint');
    const feHintVer = document.getElementById('fe-comfy-hint-ver');

    if (!selComfy || selComfy.disabled) return;
    if (!selFe    || selFe.disabled)    return;

    if (comfyHint)    { comfyHint.style.display = 'none'; }
    if (comfyHintVer) { comfyHintVer.textContent = ''; }
    if (feHint)       { feHint.style.display = 'none'; }
    if (feHintVer)    { feHintVer.textContent = ''; }

    const comfyTag  = selComfy.value;
    const feChosen  = selFe.value;
    const feIsNightly = selFe.dataset.isNightly === 'true';
    if (!comfyTag) return;

    if (feIsNightly) {
      if (comfyHint && comfyHintVer) {
        comfyHintVer.innerHTML = '<span style="color:#ff9944">NIGHTLY build — version compatibility unknown</span>';
        comfyHint.style.display = '';
      }
      if (feHint) feHint.style.display = 'none';
      return;
    }

    if (comfyTag === 'NIGHTLY') {
      if (comfyHint && comfyHintVer) {
        comfyHintVer.innerHTML = '<span style="color:#ff9944">NIGHTLY build — version compatibility unknown</span>';
        comfyHint.style.display = '';
      }
      if (feHint) feHint.style.display = 'none';
      return;
    }

    pywebview.api.get_comfyui_required_frontend(comfyTag).then(function(fe) {
      if (!fe) {
        if (comfyHint && comfyHintVer) {
          comfyHintVer.innerHTML = '<span style="color:#ff9944">unknown (no data)</span>';
          comfyHint.style.display = '';
        }
        if (feHint) feHint.style.display = 'none';
        return;
      }

      function verTuple(v) {
        return (v || '').replace(/\.post\d+/, '').split('.')
          .map(function(x) { return parseInt(x, 10) || 0; });
      }
      function verLess(a, b) {
        var ta = verTuple(a), tb = verTuple(b);
        var len = Math.max(ta.length, tb.length);
        for (var i = 0; i < len; i++) {
          var ai = ta[i] || 0, bi = tb[i] || 0;
          if (ai < bi) return true;
          if (ai > bi) return false;
        }
        return false;
      }
      const mismatch = verLess(feChosen, fe);

      if (comfyHint && comfyHintVer) {
        if (mismatch) {
          comfyHintVer.textContent = fe;
          comfyHint.style.display = '';
        } else {
          comfyHint.style.display = 'none';
        }
      }

      if (feHint && feHintVer) {
        if (mismatch) {
          feHintVer.textContent = fe;
          feHint.style.display = '';
        } else {
          feHint.style.display = 'none';
        }
      }
    }).catch(function() {});
  }

  function _checkChanges() {
    const hideDepChanged = document.getElementById('set-hide-deprecation').checked !== _initialHideDeprecation;
    const fbInput = document.getElementById('set-file-browser');
    const fbChanged = fbInput && (fbInput.value.trim() !== _initialFileBrowser);
    const selTheme = document.getElementById('set-theme');
    const themeChanged = selTheme && selTheme.value !== _initialTheme;
    const selComfy = document.getElementById('set-comfy-ver');
    const comfyChanged = selComfy && !selComfy.disabled && selComfy.dataset.current !== selComfy.value;
    const selFe = document.getElementById('set-frontend-ver');
    const feChanged = selFe && !selFe.disabled && selFe.dataset.current !== selFe.value;
    const detachChk = document.getElementById('set-detach-console');
    const detachChanged = detachChk && (detachChk.checked !== _initialDetachConsole);
    const cpChanged = _cpPathsChanged();
    const conBgImgEl  = document.getElementById('set-con-bg');
    const conBgFitEl  = document.getElementById('set-con-bg-fit');
    const conBgOpaEl  = document.getElementById('set-con-bg-opacity');
    const conBgChanged = (conBgImgEl  && conBgImgEl.value.trim()    !== _initialConBgImage)  ||
                         (conBgFitEl  && conBgFitEl.value            !== _initialConBgFit)    ||
                         (conBgOpaEl  && parseInt(conBgOpaEl.value)  !== _initialConBgOpacity);

    const applyBtn = Array.from(document.querySelectorAll('#modal-btns .modal-btn')).find(b => b.textContent.trim() === 'Apply');
    if (applyBtn) {
      const hasChanges = hideDepChanged || fbChanged || themeChanged || comfyChanged || feChanged || detachChanged || cpChanged || conBgChanged;
      applyBtn.disabled = !hasChanges;
      if (hasChanges) {
        applyBtn.classList.add('primary');
      } else {
        applyBtn.classList.remove('primary');
      }
    }
  }

  function _applySettings() {
    const hideDepChanged = document.getElementById('set-hide-deprecation').checked !== _initialHideDeprecation;
    eziSettings.hideDeprecationWarnings = document.getElementById('set-hide-deprecation').checked;
    const fbInput = document.getElementById('set-file-browser');
    const fbVal = fbInput ? fbInput.value.trim() : '';
    const fbChanged = fbVal !== _initialFileBrowser;
    eziSettings.customFileBrowser = fbVal;
    const selTheme = document.getElementById('set-theme');
    const themeChanged = selTheme && selTheme.value !== _initialTheme;
    if (themeChanged) { eziSettings.theme = selTheme.value; applyTheme(selTheme.value); }
    const detachChk = document.getElementById('set-detach-console');
    const detachChanged = detachChk && (detachChk.checked !== _initialDetachConsole);
    const cpChanged = _cpPathsChanged();
    const conBgImgEl  = document.getElementById('set-con-bg');
    const conBgFitEl  = document.getElementById('set-con-bg-fit');
    const conBgOpaEl  = document.getElementById('set-con-bg-opacity');
    const conBgImgVal  = conBgImgEl  ? conBgImgEl.value.trim()   : _initialConBgImage;
    const conBgFitVal  = conBgFitEl  ? conBgFitEl.value           : _initialConBgFit;
    const conBgOpaVal  = conBgOpaEl  ? parseInt(conBgOpaEl.value) : _initialConBgOpacity;
    const conBgChanged = conBgImgVal !== _initialConBgImage ||
                         conBgFitVal !== _initialConBgFit   ||
                         conBgOpaVal !== _initialConBgOpacity;
    if (conBgChanged) {
      eziSettings.consoleBgImage   = conBgImgVal;
      eziSettings.consoleBgFit     = conBgFitVal;
      eziSettings.consoleBgOpacity = conBgOpaVal / 100;
      _initialConBgImage   = conBgImgVal;
      _initialConBgFit     = conBgFitVal;
      _initialConBgOpacity = conBgOpaVal;
    }

    if (cpChanged) {
      const ep = _cpGetEffectivePaths();
      _initialCpInput  = ep.input.trim();
      _initialCpOutput = ep.output.trim();
      _initialCpUser   = ep.user.trim();
      pywebview.api.set_custom_paths(ep.input.trim(), ep.output.trim(), ep.user.trim());
      document.getElementById('modal-overlay').classList.remove('active');
      var notice = document.createElement('div');
      notice.id = 'cp-restart-notice';
      notice.style.cssText = 'position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:#1c3a1c;border:1px solid #50fa7b;color:#50fa7b;padding:8px 20px;border-radius:6px;font-size:12px;font-family:inherit;z-index:999999;pointer-events:none;';
      notice.textContent = '⟳ Folder paths updated — ComfyUI is restarting...';
      document.body.appendChild(notice);
      setTimeout(function() { var n = document.getElementById('cp-restart-notice'); if (n) n.remove(); }, 5000);
      return;
    }

    saveEziSettings();
    if (conBgChanged) {
      try { pywebview.api.apply_console_bg(); } catch(e) {}
    }
    const selComfy = document.getElementById('set-comfy-ver');
    const comfyChanged = selComfy && !selComfy.disabled && selComfy.dataset.current !== selComfy.value;
    const selFe = document.getElementById('set-frontend-ver');
    const feChanged = selFe && !selFe.disabled && selFe.dataset.current !== selFe.value;

    if (comfyChanged && feChanged) {
      pywebview.api.set_comfyui_version_then_frontend(selComfy.value, selFe.value);
    } else if (comfyChanged) {
      pywebview.api.set_comfyui_version(selComfy.value);
    } else if (feChanged) {
      pywebview.api.set_frontend_version(selFe.value);
    }

    if (detachChanged) {
      if (detachChk.checked) {
        pywebview.api.detach_console().then(function(ok) {
          if (ok) {
            eziSettings.consoleDetached = true;
            _initialDetachConsole = true;
            var toggleBtn = document.getElementById('btn');
            if (toggleBtn) toggleBtn.style.display = 'none';
            var reloadBtn = document.getElementById('reload-btn');
            if (reloadBtn) reloadBtn.style.display = 'none';
            statusEl.textContent = 'Console detached';
            if (!showingUI && uiLoaded) toggle();
          } else {
            detachChk.checked = false;
            eziSettings.consoleDetached = false;
            _initialDetachConsole = false;
            alert('Could not detach console. AllocConsole failed.');
          }
        }).catch(function() {
          detachChk.checked = false;
          eziSettings.consoleDetached = false;
          _initialDetachConsole = false;
        });
      } else {
        pywebview.api.reattach_console().then(function() {
          eziSettings.consoleDetached = false;
          _initialDetachConsole = false;
          var toggleBtn = document.getElementById('btn');
          if (toggleBtn) toggleBtn.style.display = '';
          var reloadBtn = document.getElementById('reload-btn');
          if (reloadBtn) reloadBtn.style.display = showingUI ? 'inline-flex' : 'none';
          statusEl.textContent = uiLoaded ? 'ComfyUI is running' : dot.classList.contains('ready') ? 'ComfyUI is starting' : 'Starting...';
        }).catch(function() {});
      }
    }

    if (hideDepChanged || fbChanged || themeChanged || comfyChanged || feChanged || detachChanged || cpChanged || conBgChanged) {
      document.getElementById('modal-overlay').classList.remove('active');
    }
  }

  showModal('', '',
    `<div style="min-width:448px">${tabBar}${tabGeneral}${tabAddons}${tabTorch}${tabTools}${tabAdvanced}</div>`,
    [
      { label: 'Apply', cls: 'primary', noClose: true, action: _applySettings },
      { label: 'Close', cls: '', action: () => {} },
    ]
  );

  ['general','addons','torch','tools','advanced'].forEach(t => {
    const btn = document.getElementById('stabtn-'+t);
    if (btn) btn.addEventListener('click', () => {
      _showTab(t);
      _updateModalBtns(t);
      if (t === 'advanced') _cpRefreshFromBat();
    });
  });

  function _cpRefreshFromBat() {
    pywebview.api.get_custom_paths().then(function(json) {
      let fresh;
      try { fresh = JSON.parse(json); } catch(e) { return; }

      _initialCpInput  = fresh.input  || '';
      _initialCpOutput = fresh.output || '';
      _initialCpUser   = fresh.user   || '';

      const newBase = _cpAutoDetect(fresh.input, fresh.output, fresh.user);
      const useBase = !!newBase;

      const chk = document.getElementById('set-cp-base-mode');
      if (chk) chk.checked = useBase;

      const baseWrap   = document.getElementById('cp-base-wrap');
      const customWrap = document.getElementById('cp-custom-wrap');
      if (baseWrap)   baseWrap.style.display   = useBase ? 'block' : 'none';
      if (customWrap) customWrap.style.display = useBase ? 'none'  : 'block';

      if (useBase) {
        const baseInp = document.getElementById('set-cp-base');
        if (baseInp) baseInp.value = newBase;
        Object.assign(_cp, fresh);
        _cpDetectedBase_live = newBase;
        _cpUpdatePreview();
      } else {
        const inp = document.getElementById('set-cp-input');
        const out = document.getElementById('set-cp-output');
        const usr = document.getElementById('set-cp-user');
        if (inp) inp.value = fresh.input  || '';
        if (out) out.value = fresh.output || '';
        if (usr) usr.value = fresh.user   || '';
        Object.assign(_cp, fresh);
      }

      _checkChanges();
    }).catch(function(){});
  }

  function _updateModalBtns(tabName) {
    const applyBtn = Array.from(document.querySelectorAll('#modal-btns .modal-btn')).find(b => b.textContent.trim() === 'Apply');
    const copyBtn  = Array.from(document.querySelectorAll('#modal-btns .modal-btn')).find(b => b.textContent.includes('Copy SysInfo') || b.textContent.includes('Copied') || b.textContent.includes('Failed'));
    if (applyBtn) applyBtn.style.display = (tabName === 'advanced') ? '' : 'none';
    if (copyBtn)  copyBtn.style.display  = (tabName === 'general')  ? '' : 'none';
    if (tabName === 'advanced') _checkChanges();
  }

  setTimeout(() => _updateModalBtns('general'), 0);

  ['stab-addons','stab-torch','stab-tools'].forEach(function(tabId) {
    document.getElementById(tabId).addEventListener('click', function(e) {
      const row = e.target.closest('.bat-clickable');
      if (!row || !row.dataset.bat) return;
      document.getElementById('modal-overlay').classList.remove('active');
      switchToConsole();
      pywebview.api.run_bat(row.dataset.bat);
    });
  });

  setTimeout(() => {
    const depCheck = document.getElementById('set-hide-deprecation');
    if (depCheck) depCheck.addEventListener('change', _checkChanges);
    const themeSel = document.getElementById('set-theme');
    if (themeSel) themeSel.addEventListener('change', function() { applyTheme(this.value); _checkChanges(); });
    const comfySel = document.getElementById('set-comfy-ver');
    if (comfySel) comfySel.addEventListener('change', _checkChanges);
    const feSel = document.getElementById('set-frontend-ver');
    if (feSel) feSel.addEventListener('change', _checkChanges);
    const fbInput = document.getElementById('set-file-browser');
    if (fbInput) fbInput.addEventListener('input', _checkChanges);
    const fbBtn = document.getElementById('set-file-browser-btn');
    if (fbBtn) fbBtn.addEventListener('click', browseForFileBrowser);
    const fbClear = document.getElementById('set-file-browser-clear');
    if (fbClear) fbClear.addEventListener('click', function() {
      const el = document.getElementById('set-file-browser');
      if (el) { el.value = ''; _checkChanges(); }
    });
    const detachChk2 = document.getElementById('set-detach-console');
    if (detachChk2) detachChk2.addEventListener('change', _checkChanges);

    const conBgInput = document.getElementById('set-con-bg');
    if (conBgInput) conBgInput.addEventListener('input', _checkChanges);
    const conBgBtn = document.getElementById('set-con-bg-btn');
    if (conBgBtn) conBgBtn.addEventListener('click', function() {
      pywebview.api.browse_for_image().then(function(path) {
        if (path) {
          document.getElementById('set-con-bg').value = path;
          _checkChanges();
        }
      }).catch(function(){});
    });
    const conBgClear = document.getElementById('set-con-bg-clear');
    if (conBgClear) conBgClear.addEventListener('click', function() {
      const el = document.getElementById('set-con-bg');
      if (el) { el.value = ''; _checkChanges(); }
    });
    const conBgFitSel = document.getElementById('set-con-bg-fit');
    if (conBgFitSel) conBgFitSel.addEventListener('change', _checkChanges);
    const conBgOpacity = document.getElementById('set-con-bg-opacity');
    if (conBgOpacity) conBgOpacity.addEventListener('input', function() {
      const valEl = document.getElementById('set-con-bg-opacity-val');
      if (valEl) valEl.textContent = this.value + '%';
      _checkChanges();
    });

    const cpBaseModeChk = document.getElementById('set-cp-base-mode');
    if (cpBaseModeChk) cpBaseModeChk.addEventListener('change', function() {
      const useBase = this.checked;
      document.getElementById('cp-base-wrap').style.display   = useBase ? 'block' : 'none';
      document.getElementById('cp-custom-wrap').style.display = useBase ? 'none'  : 'block';
      if (useBase) _cpUpdatePreview();
      _checkChanges();
    });
    const cpBaseInput = document.getElementById('set-cp-base');
    if (cpBaseInput) cpBaseInput.addEventListener('input', function() { _cpUpdatePreview(); _checkChanges(); });
    const cpBaseBtn = document.getElementById('set-cp-base-btn');
    if (cpBaseBtn) cpBaseBtn.addEventListener('click', function() { browseForFolder('set-cp-base'); });
    const cpBaseClear = document.getElementById('set-cp-base-clear');
    if (cpBaseClear) cpBaseClear.addEventListener('click', function() {
      const el = document.getElementById('set-cp-base');
      if (el) { el.value = ''; _cpUpdatePreview(); _checkChanges(); }
    });
    ['input','output','user'].forEach(function(key) {
      const inp = document.getElementById('set-cp-' + key);
      if (inp) inp.addEventListener('input', _checkChanges);
      const btn = document.getElementById('set-cp-' + key + '-btn');
      if (btn) btn.addEventListener('click', function() { browseForFolder('set-cp-' + key); });
      const clr = document.getElementById('set-cp-' + key + '-clear');
      if (clr) clr.addEventListener('click', function() {
        const el = document.getElementById('set-cp-' + key);
        if (el) { el.value = ''; _checkChanges(); }
      });
    });
    if (_cpUseBase) _cpUpdatePreview();

    _checkChanges();
  }, 50);

  let _dots = 0;
  const _loadingEl = document.getElementById('sysinfo-loading');
  const _pulse = setInterval(() => {
    if (!_loadingEl || !_loadingEl.isConnected) { clearInterval(_pulse); return; }
    _dots = (_dots + 1) % 4;
    _loadingEl.textContent = 'Loading' + '.'.repeat(_dots);
  }, 400);

  pywebview.api.get_system_info().then(function(s) {
    clearInterval(_pulse);
    if (_stale()) return;
    const loadEl = document.getElementById('sysinfo-loading');
    if (loadEl) loadEl.style.display = 'none';
    const driverMajor = s.driver ? parseInt(s.driver.split('.')[0], 10) : NaN;
    const driverColor = isNaN(driverMajor) ? '#f1fa8c' : (driverMajor >= 580 ? '#50fa7b' : '#ff5555');
    const rows = [
      _sysRow('EZi',        'v{EZI_VERSION}', '#bd93f9'),
      _sysRow('ComfyUI',    s.comfyui   || 'N/A', '#58a6ff'),
      _sysRow('Frontend',   s.frontend  || 'N/A', '#58a6ff'),
      _sysRow('Python',     s.python    || 'N/A'),
      _sysRow('PyTorch',    s.torch     || 'N/A'),
      _sysRow('CUDA Core',  s.cuda      || 'N/A'),
      _sysRowColor('NVIDIA drv', s.driver || 'N/A', driverColor),
      _sysRow('GPU Model',  s.gpu       || 'N/A'),
      _sysRow('Video VRAM', s.vram      || 'N/A'),
      _sysRow('System RAM', s.ram       || 'N/A'),
      _sysRow('Page File',  s.pagefile  || 'N/A'),
      _sysRow('Long Paths',
        s.long_paths ? '<span style="color:#50fa7b">Enabled</span>' : '<span style="color:#ff5555">Disabled</span>'),
    ];
    const tableEl = document.getElementById('sysinfo-table');
    if (tableEl) tableEl.innerHTML = '<table style="border-collapse:collapse;font-size:11px;width:100%;margin-top:6px">' + rows.join('') + '</table>';
    const btns = document.getElementById('modal-btns');
    if (!btns || !btns.isConnected) return;
    if (btns.querySelector('.copy-sysinfo-btn')) return;
    const copyBtn = document.createElement('button');
    copyBtn.className = 'modal-btn copy-sysinfo-btn';
    copyBtn.textContent = '\uD83D\uDCCB Copy SysInfo';
    copyBtn.onclick = () => {
      const text = [
        `EZi       : v{EZI_VERSION}`,
        `ComfyUI   : ${s.comfyui  || 'N/A'}`,
        `Frontend  : ${s.frontend || 'N/A'}`,
        `Python    : ${s.python   || 'N/A'}`,
        `PyTorch   : ${s.torch    || 'N/A'}`,
        `CUDA Core : ${s.cuda     || 'N/A'}`,
        `NVIDIA drv: ${s.driver   || 'N/A'}`,
        `GPU Model : ${s.gpu      || 'N/A'}`,
        `Video VRAM: ${s.vram     || 'N/A'}`,
        `System RAM: ${s.ram      || 'N/A'}`,
        `Page File : ${s.pagefile || 'N/A'}`,
        `Long Paths: ${s.long_paths ? 'Enabled' : 'Disabled'}`,
      ].join('\n');
      navigator.clipboard.writeText(text).then(() => {
        copyBtn.textContent = '\u2714 Copied!';
        setTimeout(() => { copyBtn.textContent = '\uD83D\uDCCB Copy SysInfo'; }, 2000);
      }).catch(() => {
        copyBtn.textContent = '\u2718 Failed';
        setTimeout(() => { copyBtn.textContent = '\uD83D\uDCCB Copy SysInfo'; }, 2000);
      });
    };
    btns.insertBefore(copyBtn, btns.firstChild);
    const activeTab = ['general','addons','advanced'].find(t => {
      const el = document.getElementById('stab-'+t);
      return el && el.style.display !== 'none';
    }) || 'general';
    _updateModalBtns(activeTab);
  }).catch(function() {
    clearInterval(_pulse);
    if (_stale()) return;
    const loadEl = document.getElementById('sysinfo-loading');
    if (loadEl) loadEl.textContent = 'N/A';
  });

  function _setCacheSize(elId, val) {
    const el = document.getElementById(elId);
    if (!el) return;
    el.innerHTML = val
      ? '<span style="color:var(--text);font-weight:bold">' + val + '</span>'
      : '<span style="color:var(--text2);font-style:italic">N/A</span>';
    const type = elId.replace('-cache-size', '');
    const btn = document.getElementById(type + '-cache-clear-btn');
    if (!btn) return;
    const isEmpty = !val || parseFloat(val) === 0;
    btn.disabled = isEmpty;
    btn.style.opacity     = isEmpty ? '0.35' : '1';
    btn.style.cursor      = isEmpty ? 'default' : 'pointer';
    btn.style.borderColor = isEmpty ? 'var(--border)' : '#ff5555';
    btn.style.color       = isEmpty ? 'var(--text2)'  : '#ff5555';
    btn.onmouseover = isEmpty ? null : function() { this.style.background = 'rgba(255,85,85,0.15)'; };
    btn.onmouseout  = isEmpty ? null : function() { this.style.background = 'var(--btn-bg)'; };
  }
  function _setCacheBusy(type, busy) {
    const btn = document.getElementById(type + '-cache-clear-btn');
    if (!btn) return;
    btn.textContent = busy ? 'Clearing\u2026' : 'Clear';
    if (busy) {
      btn.disabled = true;
      btn.style.opacity = '0.5';
      btn.style.cursor  = 'default';
    }
  }
  function _updateCacheWarning() {
    const warn = document.getElementById('cache-warning');
    if (!warn) return;
    const pipEmpty = parseFloat(document.getElementById('pip-cache-size').textContent) === 0;
    const uvEmpty  = parseFloat(document.getElementById('uv-cache-size').textContent)  === 0;
    warn.style.display = (pipEmpty && uvEmpty) ? 'none' : 'flex';
  }
  pywebview.api.get_cache_sizes().then(function(d) {
    if (_stale()) return;
    _setCacheSize('pip-cache-size', d.pip || null);
    _setCacheSize('uv-cache-size',  d.uv  || null);
    _updateCacheWarning();
  }).catch(function() {
    if (_stale()) return;
    _setCacheSize('pip-cache-size', null);
    _setCacheSize('uv-cache-size',  null);
    _updateCacheWarning();
  });
  document.getElementById('pip-cache-clear-btn').addEventListener('click', function() {
    if (_stale()) return;
    _setCacheBusy('pip', true);
    pywebview.api.clear_cache('pip').then(function(d) {
      if (_stale()) return;
      _setCacheSize('pip-cache-size', d.size || null);
      _setCacheBusy('pip', false);
      _updateCacheWarning();
    }).catch(function() {
      if (_stale()) return;
      _setCacheBusy('pip', false);
    });
  });
  document.getElementById('uv-cache-clear-btn').addEventListener('click', function() {
    if (_stale()) return;
    _setCacheBusy('uv', true);
    pywebview.api.clear_cache('uv').then(function(d) {
      if (_stale()) return;
      _setCacheSize('uv-cache-size', d.size || null);
      _setCacheBusy('uv', false);
      _updateCacheWarning();
    }).catch(function() {
      if (_stale()) return;
      _setCacheBusy('uv', false);
    });
  });

  pywebview.api.get_comfyui_versions().then(function(data) {
    if (_stale()) return;
    const sel = document.getElementById('set-comfy-ver');
    if (!sel) return;
    sel.innerHTML = '';
    sel.dataset.current = data.current || '';
    const stable = data.stableVersion || '';
    data.versions.forEach(function(v) {
      const opt = document.createElement('option');
      opt.value = v;
      const isCurrent = v === data.current;
      const isStable  = stable && v === stable;
      let label = v;
      if (isStable)  label += ' ⭐ stable';
      if (isCurrent) label += ' (current)';
      opt.textContent = label;
      if (isCurrent) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.disabled = false;
    sel.onchange = function() {
      _updateVersionHints();
      _checkChanges();
    };
    _checkChanges();
    _updateVersionHints();
  }).catch(function() {
    const sel = document.getElementById('set-comfy-ver');
    if (sel) sel.innerHTML = '<option>Unavailable</option>';
  });

  pywebview.api.get_frontend_versions().then(function(data) {
    if (_stale()) return;
    const sel = document.getElementById('set-frontend-ver');
    if (!sel) return;
    sel.innerHTML = '';
    sel.dataset.current = data.current;
    sel.dataset.isNightly = data.isNightly ? 'true' : 'false';
    data.versions.forEach(function(v) {
      const opt = document.createElement('option');
      opt.value = v;
      opt.textContent = v + (v === data.current ? ' (current)' : '');
      if (v === data.current) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.disabled = false;
    sel.onchange = function() {
      _updateVersionHints();
      _checkChanges();
    };
    _checkChanges();
    _updateVersionHints();
  }).catch(function() {
    const sel = document.getElementById('set-frontend-ver');
    if (sel) sel.innerHTML = '<option>Unavailable</option>';
  });
}


function set_dot_ready() {
  dot.style.background = '';
  dot.style.animation = '';
  dot.classList.add('ready');
  statusEl.textContent = 'ComfyUI is starting';
  try { pywebview.api.set_title('Starting...'); } catch(e) {}
}

function load_ui(url) {
  frame.src = url;
  frame.onload = () => {
    uiLoaded = true; btn.classList.add('active');
    dot.style.background = ''; dot.style.animation = '';
    dot.classList.add('ready');
    try {
      var w = frame.contentWindow;
      if (w) {
        w.onbeforeunload = null;
        Object.defineProperty(w, 'onbeforeunload', {
          get: function() { return null; },
          set: function() {},
          configurable: true
        });
        var _origAEL = w.EventTarget.prototype.addEventListener;
        w.EventTarget.prototype.addEventListener = function(type, fn, opts) {
          if (type === 'beforeunload') return;
          return _origAEL.call(this, type, fn, opts);
        };
      }
    } catch(e) {}
    _restoreTabsAfterLoad();
    if(!showingUI) setTimeout(toggle, 200);
    (function() {
      var notice = document.getElementById('comfy-update-notice');
      if (notice && notice.dataset.unstable === 'true') {
        _nonStableNoticeDismissed = true;
        notice.style.display = 'none';
        var eziVisible = document.getElementById('ezi-update-notice').style.display !== 'none';
        if (!eziVisible) document.getElementById('update-notice').style.display = 'none';
      }
    })();
    setTimeout(function() {
      var comfyNotice = document.getElementById('comfy-update-notice');
      var eziNotice   = document.getElementById('ezi-update-notice');
      var wrapNotice  = document.getElementById('update-notice');
      if (comfyNotice) comfyNotice.style.display = 'none';
      if (eziNotice)   eziNotice.style.display   = 'none';
      if (wrapNotice)  wrapNotice.style.display   = 'none';
    }, 8000);
    try { pywebview.api.set_title('Running'); } catch(e) {}
    _startStorageWatch();
  };
}

function toggle() {
  if (!uiLoaded && !showingUI) return;
  if (_toggling) return;
  _toggling = true;
  if (showingUI) _saveTabsToDisk();
  showingUI = !showingUI;
  if (showingUI) {
    termPanel.style.transform = 'translateX(-100vw)'; termPanel.style.opacity = '0'; termPanel.style.pointerEvents = 'none';
    uiPanel.style.transform = 'translateX(0)'; uiPanel.style.opacity = '1'; uiPanel.style.pointerEvents = 'auto';
    icoBg.style.display = 'none';
    btn.textContent = '◀ CONSOLE'; statusEl.textContent = ''; dot.style.display = 'none';
    document.getElementById('reload-btn').style.display = 'inline-flex';
    uiPanel.addEventListener('transitionend', function _done() {
      uiPanel.removeEventListener('transitionend', _done);
      _toggling = false;
    });
  } else {
    uiPanel.style.transform = 'translateX(100vw)'; uiPanel.style.opacity = '0'; uiPanel.style.pointerEvents = 'none';
    termPanel.style.transition = 'none'; termPanel.style.transform = 'translateX(-100vw)'; void termPanel.offsetWidth;
    termPanel.style.transition = 'transform 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease';
    termPanel.style.transform = 'translateX(0)'; termPanel.style.opacity = '1'; termPanel.style.pointerEvents = 'auto';
    icoBg.style.display = '';
    btn.textContent = 'ComfyUI ▶'; dot.style.display = ''; statusEl.textContent = uiLoaded ? 'ComfyUI is running' : dot.classList.contains('ready') ? 'ComfyUI is starting' : 'Starting...';
    document.getElementById('reload-btn').style.display = 'none';
    termPanel.addEventListener('transitionend', function _done() {
      termPanel.removeEventListener('transitionend', _done);
      _toggling = false;
    });
  }
  setTimeout(function() { _toggling = false; }, 600);
}

function add_to_console(text) {
  const isAtBottom = (term.scrollHeight - term.scrollTop - term.clientHeight) < 20;
  const clean = text.replace(/[\r\n]/g, '');
  const html = ansi.ansi_to_html(clean) || '&nbsp;';
  if (text.includes('\r') && !text.includes('\n')) {
    if (!lastCR) { lastCR = document.createElement('div'); term.appendChild(lastCR); }
    lastCR.innerHTML = html;
  } else {
    if (text === '\n' && lastCR) { lastCR = null; return; }
    const d = document.createElement('div'); d.innerHTML = html; term.appendChild(d);
    if (text.includes('\n')) lastCR = null;
  }
  if (isAtBottom) { term.scrollTop = term.scrollHeight; }
}

function show_port_error() {
  dot.style.background = '#ff5555'; dot.style.animation = 'none';
  statusEl.style.color = '#ff5555'; statusEl.textContent = 'Port in use!';
  btn.textContent = '\u21ba Retry'; btn.classList.add('active');
  btn.style.background = '#6e2020'; btn.style.borderColor = '#ff5555';
  btn.onclick = retry;
  try { pywebview.api.set_title('Port in use!'); } catch(e) {}
}

function retry() {
  btn.textContent = 'Retrying...'; btn.classList.remove('active'); btn.style.background = ''; btn.style.borderColor = '';
  dot.style.background = '#f1fa8c'; dot.style.animation = 'pulse 1.5s infinite';
  statusEl.style.color = '#8b949e'; statusEl.textContent = 'Starting...';
  btn.onclick = toggle;
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  ctx.font = '12px Consolas, "Courier New", monospace';
  const charW = ctx.measureText('M').width || 7.2;
  const style = window.getComputedStyle(term);
  const padL = parseFloat(style.paddingLeft) || 0;
  const padR = parseFloat(style.paddingRight) || 0;
  const scrollbarW = Math.max(term.offsetWidth - term.clientWidth, 17);
  const usable = term.clientWidth - padL - padR - scrollbarW - 2;
  const cols = Math.floor(usable / charW);
  pywebview.api.retry(cols > 0 ? cols : 0);
}

const overlay  = document.getElementById("crop-overlay");
const cropSel  = document.getElementById("crop-sel");
const shadeT   = document.getElementById("crop-shade-t");
const shadeB   = document.getElementById("crop-shade-b");
const shadeL   = document.getElementById("crop-shade-l");
const shadeR   = document.getElementById("crop-shade-r");
let cropStart  = null;

let _cropMode = 'screenshot';
let _cropPending = false;
let _recFps = 30;
function _fpsPickerHTML() {
  var btnStyle = 'margin-left:3px;padding:0 7px;height:22px;font-family:inherit;font-size:11px;font-weight:bold;'
    + 'border-radius:4px;cursor:pointer;pointer-events:auto;display:inline-flex;align-items:center;'
    + 'border:1px solid #ff8888;background:#6e2020;color:#ff8888;box-sizing:border-box;';
  return ' &nbsp;<span style="font-size:11px;opacity:0.85;">FPS:</span>'
    + [15,30,60].map(f =>
        '<button onclick="event.stopPropagation();_recFps='+f+';_updateFpsBtns();" id="fps-btn-'+f+'" '
        + 'style="' + btnStyle + '">'+f+'</button>'
      ).join('')
    + ' &nbsp;';
}
function _updateFpsBtns() {
  [15,30,60].forEach(f => {
    var b = document.getElementById('fps-btn-'+f);
    if (!b) return;
    b.style.background = (_recFps===f) ? '#ff4444' : '#6e2020';
    b.style.color      = (_recFps===f) ? '#fff'    : '#ff8888';
  });
  eziSettings.recFps = _recFps;
  saveEziSettings();
}
function startCrop(mode) {
  _cropMode = mode || 'screenshot';
  closeAllDropdowns();
  const hint = document.getElementById('crop-hint');
  if (_cropMode === 'video') {
    hint.innerHTML = '\uD83C\uDF9E\uFE0F Record: Click for full window &nbsp;|&nbsp; Drag to select area'
      + _fpsPickerHTML()
      + '<button id="crop-cancel-btn" class="btn-danger" style="margin-left:4px;padding:0 10px;height:22px;font-family:inherit;font-size:11px;font-weight:bold;border-radius:4px;cursor:pointer;pointer-events:auto;display:inline-flex;align-items:center;gap:4px;box-sizing:border-box;">\u2715 Cancel</button>';
    hint.style.color = '#ff8888';
    _updateFpsBtns();
  } else {
    hint.innerHTML = 'Click for full window &nbsp;|&nbsp; Drag to select area &nbsp;<button id="crop-cancel-btn" class="btn-danger" style="margin-left:8px;padding:0 10px;height:22px;font-family:inherit;font-size:11px;font-weight:bold;border-radius:4px;cursor:pointer;pointer-events:auto;display:inline-flex;align-items:center;gap:4px;box-sizing:border-box;">\u2715 Cancel</button>';
    hint.style.color = '';
  }
  _reattachCropCancelBtn();
  overlay.classList.add("active");
  cropSel.style.cssText = "left:0;top:0;width:0;height:0;";
  shadeT.style.cssText = "top:0;left:0;right:0;bottom:0;";
  shadeB.style.cssText = shadeL.style.cssText = shadeR.style.cssText = "display:none";
  hint.style.display = '';
}
function _reattachCropCancelBtn() {
  var btn = document.getElementById('crop-cancel-btn');
  if (!btn) return;
  btn.addEventListener('mousedown', function(e) { e.stopPropagation(); e.preventDefault(); });
  btn.addEventListener('click',    function(e) { e.stopPropagation(); e.preventDefault(); cropCancel(); });
  btn.addEventListener('mouseup',  function(e) { e.stopPropagation(); e.preventDefault(); });
}

function cropCancel() {
    cropStart = null;
    overlay.classList.remove("active");
}

function screenshotFull() {
  if (_cropPending) return;
  _cropPending = true;
  if (_cropMode === 'video') {
    pywebview.api.start_recording(0, 0, window.innerWidth, window.innerHeight, _recFps);
  } else {
    pywebview.api.screenshot(0, 0, window.innerWidth, window.innerHeight)
      .finally(function() { _cropPending = false; });
  }
}
function showRecIndicator(x, y, w, h) {
  _cropPending = false;
  var outline = document.getElementById('rec-outline');
  var recIndicator = document.getElementById('rec-indicator');
  var isFullscreen = (w >= window.innerWidth && h >= window.innerHeight);
  if (!isFullscreen) {
    outline.style.cssText = 'display:block;left:' + x + 'px;top:' + y + 'px;width:' + w + 'px;height:' + h + 'px;';
    recIndicator.style.display = 'none';
  } else {
    outline.style.display = 'none';
    recIndicator.style.cssText = 'display:inline-flex;align-items:center;gap:6px;';
    recIndicator.innerHTML = '<span style="width:8px;height:8px;border-radius:50%;background:#ff4444;display:inline-block;animation:rec-blink 1s ease-in-out infinite;flex-shrink:0;"></span><button onclick="stopRecording()" style="padding:3px 10px;font-family:inherit;font-size:11px;font-weight:bold;border:1px solid #ff4444;border-radius:4px;background:#6e2020;color:#ff8888;cursor:pointer;animation:rec-blink 1s ease-in-out infinite;line-height:1;letter-spacing:0.5px;">&#x23F9; Stop REC</button>';
  }
}
function stopRecording() {
  _cropPending = false;
  pywebview.api.stop_recording();
  document.getElementById('rec-outline').style.display = 'none';
  var recIndicator = document.getElementById('rec-indicator');
  recIndicator.style.display = 'none';
  recIndicator.innerHTML = '';
}
function onRecBtnClick() {
  startCrop('video');
}
function toggleScrDropdown(e) {
  e.stopPropagation();
  var dd = document.getElementById('out-dropdown');
  var sd = document.getElementById('scr-dropdown');
  if (dd) dd.classList.remove('open');
  sd.classList.toggle('open');
}

var _nonStableNoticeDismissed = false;

function show_update(version, isStable) {
  const msg = document.getElementById('update-msg');
  const btn  = document.getElementById('update-btn');
  const notice = document.getElementById('comfy-update-notice');
  if (isStable) {
    msg.textContent = '\u2B06 ComfyUI update available' + (version ? ' \u2192 ' + version : '');
    msg.style.color = '#f1fa8c';
    if (btn) { btn.style.display = ''; }
    notice.dataset.unstable = 'false';
  } else {
    if (_nonStableNoticeDismissed) return;
    msg.textContent = '\u2B06 ' + (version ? version : 'new') + ' available (pre-release)';
    msg.style.color = '#888';
    if (btn) { btn.style.display = 'none'; }
    notice.dataset.unstable = 'true';
  }
  notice.style.display = 'flex';
  document.getElementById('update-notice').style.display = 'flex';
}

function hide_update_notice() {
  document.getElementById('comfy-update-notice').style.display = 'none';
  const eziVisible = document.getElementById('ezi-update-notice').style.display !== 'none';
  if (!eziVisible) document.getElementById('update-notice').style.display = 'none';
}

function doUpdate() {
  pywebview.api.run_update();
}

function show_ezi_update(version) {
  const msg = document.getElementById('ezi-update-msg');
  if (msg) msg.textContent = '\u2B06 EZi update available' + (version ? ' \u2192 ' + version : '');
  document.getElementById('ezi-update-notice').style.display = 'flex';
  document.getElementById('update-notice').style.display = 'flex';
}

function doEziUpdate() {
  pywebview.api.run_ezi_update();
}

var _lastGoodSnapshot = null;
var _storageWatchInterval = null;
var _lastStorageHash = '';
var _storageSaveTimer = null;

function _scheduleSave() {
  if (_storageSaveTimer) clearTimeout(_storageSaveTimer);
  _storageSaveTimer = setTimeout(function() {
    _storageSaveTimer = null;
    if (!uiLoaded || !showingUI) return;
    _saveTabsToDisk();
  }, 300);
}

function _patchIframeStorage(w) {
  try {
    ['localStorage', 'sessionStorage'].forEach(function(storeName) {
      var store = w[storeName];
      if (!store || store.__eziPatched) return;
      var _origSet    = store.setItem.bind(store);
      var _origRemove = store.removeItem.bind(store);
      var _origClear  = store.clear.bind(store);
      store.setItem = function(k, v) {
        _origSet(k, v);
        _scheduleSave();
      };
      store.removeItem = function(k) {
        _origRemove(k);
        _scheduleSave();
      };
      store.clear = function() {
        _origClear();
        _scheduleSave();
      };
      store.__eziPatched = true;
    });
  } catch(e) {}
}

function _startStorageWatch() {
  try {
    var w = frame.contentWindow;
    if (w) _patchIframeStorage(w);
  } catch(e) {}
}

function _stopStorageWatch() {
  if (_storageWatchInterval) { clearInterval(_storageWatchInterval); _storageWatchInterval = null; }
  if (_storageSaveTimer) { clearTimeout(_storageSaveTimer); _storageSaveTimer = null; }
  _lastStorageHash = '';
}

function _saveTabsToDisk() {
  try {
    var f = document.getElementById('ui-frame');
    var out = { ls: {}, ss: {} };

    if (f && f.contentWindow && uiLoaded) {
      var w = f.contentWindow;

      var href = '';
      try { href = w.location.href; } catch(e) {}
      if (!href || href === 'about:blank') {
        if (_lastGoodSnapshot) {
          pywebview.api.save_comfy_storage(JSON.stringify(_lastGoodSnapshot));
        }
        return;
      }

      try {
        var ls = w.localStorage;
        for (var i = 0; i < ls.length; i++) {
          var k = ls.key(i);
          if (k) out.ls[k] = ls.getItem(k);
        }
      } catch(e) {}
      try {
        var ss = w.sessionStorage;
        for (var j = 0; j < ss.length; j++) {
          var sk = ss.key(j);
          if (sk) out.ss[sk] = ss.getItem(sk);
        }
      } catch(e) {}
    }

    var hasData = Object.keys(out.ls).length > 0 || Object.keys(out.ss).length > 0;

    if (hasData) {
      _lastGoodSnapshot = out;
      pywebview.api.save_comfy_storage(JSON.stringify(out));
    } else if (_lastGoodSnapshot) {
      pywebview.api.save_comfy_storage(JSON.stringify(_lastGoodSnapshot));
    }
  } catch(e) {}
}

function _ezi_isDraftKey(k) {
  var DRAFT_PREFIXES = [
    'Comfy.Workflow.DraftIndex.v2:',
    'Comfy.Workflow.Draft.v2:',
    'Comfy.Workflow.LastActivePath:',
    'Comfy.Workflow.LastOpenPaths:',
    'workflow'
  ];
  for (var i = 0; i < DRAFT_PREFIXES.length; i++) {
    if (k.indexOf(DRAFT_PREFIXES[i]) === 0) return true;
  }
  return false;
}

function _restoreTabsAfterLoad() {
  try {
    var w = frame.contentWindow;
    if (!w) return;
    var wls = w.localStorage;
    var prefix_ss = '_ezi_ss_';
    var prefix_ls = '_ezi_ls_';
    var hadData = false;
    for (var i = 0; i < localStorage.length; i++) {
      var key = localStorage.key(i);
      if (key && key.startsWith(prefix_ss)) {
        var rk = key.slice(prefix_ss.length);
        if (!_ezi_isDraftKey(rk)) {
          try { w.sessionStorage.setItem(rk, localStorage.getItem(key)); hadData = true; } catch(e) {}
        }
      }
      if (key && key.startsWith(prefix_ls)) {
        var rk = key.slice(prefix_ls.length);
        if (!_ezi_isDraftKey(rk)) {
          try { wls.setItem(rk, localStorage.getItem(key)); hadData = true; } catch(e) {}
        }
      }
    }
    if (hadData) return;
  } catch(e) {}

  try {
    pywebview.api.get_comfy_storage().then(function(stored) {
      if (!stored) return;
      try {
        var w = frame.contentWindow;
        if (!w) return;
        var wls = w.localStorage;
        var wss = w.sessionStorage;
        if (stored.ls) {
          Object.keys(stored.ls).forEach(function(k) {
            if (!_ezi_isDraftKey(k)) {
              try { wls.setItem(k, stored.ls[k]); } catch(e) {}
            }
          });
        }
        if (stored.ss) {
          Object.keys(stored.ss).forEach(function(k) {
            if (!_ezi_isDraftKey(k)) {
              try { wss.setItem(k, stored.ss[k]); } catch(e) {}
            }
          });
        }
        _lastGoodSnapshot = stored;
      } catch(e) {}
    }).catch(function(){});
  } catch(e) {}
}

function switchToConsole(statusMsg) {
  if (showingUI) {
    showingUI = false;
    uiPanel.style.transform = 'translateX(100vw)'; uiPanel.style.opacity = '0'; uiPanel.style.pointerEvents = 'none';
    termPanel.style.transition = 'none'; termPanel.style.transform = 'translateX(-100vw)'; void termPanel.offsetWidth;
    termPanel.style.transition = 'transform 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease';
    termPanel.style.transform = 'translateX(0)'; termPanel.style.opacity = '1'; termPanel.style.pointerEvents = 'auto';
    icoBg.style.display = '';
  }
  _stopStorageWatch();
  _saveTabsToDisk();
  hide_update_notice();
  frame.onload = null;
  try { if (frame.contentWindow) frame.contentWindow.onbeforeunload = undefined; } catch(e) {}
  uiLoaded = false;
  btn.textContent = 'ComfyUI ▶'; btn.classList.remove('active');
  btn.style.background = ''; btn.style.borderColor = '';
  dot.classList.remove('ready'); dot.style.display = '';
  if (statusMsg === 'Stopped') {
    dot.style.background = '#ff5555'; dot.style.animation = 'none';
    statusEl.style.color = '#ff5555'; statusEl.textContent = 'Stopped';
    try { pywebview.api.set_title('Stopped'); } catch(e) {}
  } else {
    dot.style.background = '#f1fa8c'; dot.style.animation = 'pulse 1.5s infinite';
    statusEl.style.color = '#8b949e'; statusEl.textContent = statusMsg || 'Starting...';
    try { pywebview.api.set_title(statusMsg || ''); } catch(e) {}
  }
}

function updateShades(x, y, w, h) {
  const W = window.innerWidth, H = window.innerHeight;
  shadeT.style.cssText  = `top:0;left:0;right:0;height:${y}px;`;
  shadeB.style.cssText  = `top:${y+h}px;left:0;right:0;bottom:0;`;
  shadeL.style.cssText  = `top:${y}px;left:0;width:${x}px;height:${h}px;`;
  shadeR.style.cssText  = `top:${y}px;left:${x+w}px;right:0;height:${h}px;`;
}

const OVERLAY_TOP = 32;

overlay.addEventListener("mousedown", e => {
  if (e.target !== overlay) return;
  cropStart = {x: e.clientX, y: Math.max(e.clientY, OVERLAY_TOP)};
  shadeT.style.cssText = shadeB.style.cssText = shadeL.style.cssText = shadeR.style.cssText = "";
  document.getElementById('crop-hint').style.display = 'none';
});

overlay.addEventListener("mousemove", e => {
  if (!cropStart) return;
  const rawY = Math.max(e.clientY, OVERLAY_TOP);
  const x = Math.min(e.clientX, cropStart.x);
  const y = Math.min(rawY, cropStart.y);
  const w = Math.abs(e.clientX - cropStart.x);
  const h = Math.abs(rawY - cropStart.y);
  cropSel.style.cssText = `left:${x}px;top:${y - OVERLAY_TOP}px;width:${w}px;height:${h}px;`;
  updateShades(x, y - OVERLAY_TOP, w, h);
});

overlay.addEventListener("mouseup", e => {
  if (!cropStart) return;
  const rawY = Math.max(e.clientY, OVERLAY_TOP);
  const x = Math.min(e.clientX, cropStart.x);
  const y = Math.min(rawY, cropStart.y);
  const w = Math.abs(e.clientX - cropStart.x);
  const h = Math.abs(rawY - cropStart.y);
  cropStart = null;
  overlay.classList.remove("active");
  if (_cropPending) return;
  _cropPending = true;
  if (w > 5 && h > 5) {
    if (_cropMode === 'video') {
      pywebview.api.start_recording(Math.round(x), Math.round(y), Math.round(w), Math.round(h), _recFps);
    } else {
      pywebview.api.screenshot(Math.round(x), Math.round(y), Math.round(w), Math.round(h))
        .finally(function() { _cropPending = false; });
    }
  } else {
    _cropPending = false;
    screenshotFull();
  }
});

document.addEventListener("keydown", e => {
  if (e.key === "Escape") { cropStart = null; overlay.classList.remove("active"); }
});

document.getElementById('settings-btn').addEventListener('click', function(e) {
  if (e.ctrlKey && e.shiftKey) {
    function _eziDeob(b){try{return atob(b);}catch(e){return b;}}

    showModal('\uD83E\uDD5A', _eziDeob('RWFzdGVyIEVnZyAoMjAyNi0wNCk='),
      `<div style="text-align:center;line-height:2">
        <div style="font-size:32px;margin-bottom:8px">\uD83D\uDE80</div>
        <div style="color:#f1fa8c;font-size:13px;font-weight:bold">${_eziDeob('Q29tZnlVSS1FYXN5LUluc3RhbGw=')}</div>
        <div style="color:#8b949e;font-size:11px;margin-top:6px">${_eziDeob('TWFkZSB3aXRoIA==')}\u2764\uFE0F${_eziDeob('IGJ5IA==')}<span style="color:#58a6ff">${_eziDeob('aXZvIGFrYSBUYXZyaXMx')}</span></div>
        <div style="color:#00FF00;font-size:11px;margin-top:6px">${_eziDeob('Q29uZ3JhdHVsYXRpb25zIHRvIFBpeGFyb21hIG9uIHJlYWNoaW5nIDEwMCwwMDAgc3Vic2NyaWJlcnMg')}<span style="font-family: 'Segoe UI Emoji', 'Apple Color Emoji', sans-serif; color: unset;">\uD83C\uDF89\uFE0F</span></div>
        <div style="color:#8b949e;font-size:11px;margin-top:6px">${_eziDeob('T25seSA5MDAsMDAwIGxlZnQgdW50aWwgdGhlIG5leHQgRWFzdGVyIGVnZyA=')}<span style="font-family: 'Segoe UI Emoji', 'Apple Color Emoji', sans-serif; color: unset;">\uD83D\uDE0E\uFE0F</span></div>
      </div>`,
      [{ label: 'Cheers!', cls: '', action: () => {} }]
    );
  } else {
    show_settings();
  }
});

function showModal(icon, title, msg, buttons) {
  document.getElementById('modal-icon').textContent = icon;
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-msg').innerHTML = msg;
  const btns = document.getElementById('modal-btns');
  btns.innerHTML = '';
  buttons.forEach(b => {
    const el = document.createElement('button');
    el.className = 'modal-btn' + (b.cls ? ' ' + b.cls : '');
    el.textContent = b.label;
    el.onclick = () => { if (!b.noClose) document.getElementById('modal-overlay').classList.remove('active'); b.action(); };
    btns.appendChild(el);
  });
  document.getElementById('modal-overlay').classList.add('active');
}

function show_close_confirm() {
  showModal('❌', 'Close ComfyUI?',
    'ComfyUI will be stopped and the window will close.',
    [
      { label: 'Cancel', cls: '', action: () => pywebview.api.modal_response(false, 'close') },
      { label: 'Close', cls: 'danger', action: () => pywebview.api.modal_response(true, 'close') },
    ]
  );
}

function show_update_confirm() {
  showModal('⬆', 'Update ComfyUI',
    'ComfyUI will be stopped and the updater will run.<br><br>After the update, ComfyUI&#8209;EZi will restart automatically.',
    [
      { label: 'Cancel', cls: '', action: () => pywebview.api.modal_response(false, 'update') },
      { label: 'Update', cls: 'primary', action: () => pywebview.api.modal_response(true, 'update') },
    ]
  );
}

function show_update_missing(path) {
  showModal('⚠', 'Update not available',
    'Update ComfyUI.bat not found in:<br><code style="color:#f1fa8c;font-size:11px">' + path + '</code><br><br>Nothing was changed.',
    [
      { label: 'OK', cls: 'primary', action: () => {} },
    ]
  );
}

function show_bat_missing(batName) {
  showModal('⚠', 'Bat file not found',
    '<code style="color:#f1fa8c;font-size:11px">' + batName + '</code><br><br>'
    + 'EZi will start with default parameters.',
    [
      { label: 'OK', cls: 'primary', action: () => {} },
    ]
  );
}


function init_output_btn() {
  pywebview.api.check_output_folder().then(function(path) {
    if (path) document.getElementById('out-btn-wrap').classList.add('visible');
  });
}

function toggleOutDropdown(e) {
  e.stopPropagation();
  var dd = document.getElementById('out-dropdown');
  var sd = document.getElementById('scr-dropdown');
  if (sd) sd.classList.remove('open');
  dd.classList.toggle('open');
}

function openSubFolder(type) {
  closeAllDropdowns();
  pywebview.api.open_sub_folder(type);
}

function handleCustomNodesClick(event) {
    closeAllDropdowns();
    if (event.shiftKey) {
        pywebview.api.open_nodes_cmd();
    } else {
        openSubFolder('custom_nodes');
    }
}

function closeAllDropdowns() {
  var dd = document.getElementById('out-dropdown');
  if (dd) dd.classList.remove('open');
  var sd = document.getElementById('scr-dropdown');
  if (sd) sd.classList.remove('open');
}

document.addEventListener('click', function() {
  closeAllDropdowns();
});

function send_columns() {
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  ctx.font = '12px Consolas, "Courier New", monospace';
  const charW = ctx.measureText('M').width || 7.2;
  const style = window.getComputedStyle(term);
  const padL = parseFloat(style.paddingLeft) || 0;
  const padR = parseFloat(style.paddingRight) || 0;
  const scrollbarW = Math.max(term.offsetWidth - term.clientWidth, 17);
  const usable = term.clientWidth - padL - padR - scrollbarW - 2;
  const cols = Math.floor(usable / charW);
  if (cols > 0) pywebview.api.set_columns(cols);
}

window.addEventListener('resize', send_columns);

(function() {
  let _lastScrollbarW = 0;
  const _ro = new ResizeObserver(function() {
    const sw = term.offsetWidth - term.clientWidth;
    if (sw !== _lastScrollbarW) {
      _lastScrollbarW = sw;
      send_columns();
    }
  });
  _ro.observe(term);
})();

(function waitForApi() {
  if (typeof pywebview !== 'undefined' && pywebview.api && pywebview.api.js_ready) {
    pywebview.api.get_ui_settings().then(function(s) {
      if (s) {
        try {
          var loaded = JSON.parse(s);
          Object.assign(eziSettings, loaded);
          applyTheme(eziSettings.theme || 'dark');
          if (typeof eziSettings.recFps !== 'undefined' && [15,30,60].indexOf(eziSettings.recFps) !== -1) {
            _recFps = eziSettings.recFps;
          }
          if (eziSettings.consoleBgImage) {
            try { pywebview.api.apply_console_bg(); } catch(e) {}
          }
          if (eziSettings.consoleDetached) {
            pywebview.api.detach_console().then(function(ok) {
              if (ok) {
                var toggleBtn = document.getElementById('btn');
                if (toggleBtn) toggleBtn.style.display = 'none';
                var reloadBtn = document.getElementById('reload-btn');
                if (reloadBtn) reloadBtn.style.display = 'none';
              } else {
                eziSettings.consoleDetached = false;
                saveEziSettings();
              }
            }).catch(function() {
              eziSettings.consoleDetached = false;
              saveEziSettings();
            });
          }
        } catch(e) {}
      }
    }).catch(function(){});

    (function() {
      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');
      ctx.font = '12px Consolas, "Courier New", monospace';
      const charW = ctx.measureText('M').width || 7.2;
      const style = window.getComputedStyle(term);
      const padL = parseFloat(style.paddingLeft) || 0;
      const padR = parseFloat(style.paddingRight) || 0;
      const scrollbarW = Math.max(term.offsetWidth - term.clientWidth, 17);
      const usable = (term.clientWidth - padL - padR - scrollbarW - 2) || (window.innerWidth - padL - padR - 17 - 2);
      const cols = Math.floor(usable / charW);
      pywebview.api.js_ready(cols > 0 ? cols : 0);
    })();
    init_output_btn();
  } else setTimeout(waitForApi, 30);
})();

window.addEventListener('message', function(event) {
    if (event.data && event.data.type === 'ezi_comfy_ready') {
        _saveTabsToDisk();
        try { pywebview.api.ui_shown(); } catch(e) {}
        return;
    }

    if (event.data && event.data.type === 'ezi_clipboard_request') {
        if (event.data.action === 'paste') {
            pywebview.api.read_clipboard().then(function(text) {
                var iframe = document.getElementById('ui-frame');
                if (iframe && iframe.contentWindow) {
                    iframe.contentWindow.postMessage({ type: 'ezi_clipboard_response', text: text }, '*');
                }
            });
        } else if (event.data.action === 'copy' || event.data.action === 'cut') {
            pywebview.api.write_clipboard(event.data.text);
        }
        return;
    }

    if (event.data && event.data.type === 'ezi_save_blob') {
        pywebview.api.save_blob_data(event.data.filename, event.data.content);
        return;
    }

    if (event.data && event.data.type === 'ezi_open_auth_popup') {
        try { pywebview.api.open_auth_popup(event.data.url); } catch(e) {}
        return;
    }

    if (event.data && event.data.type === 'ezi_save_image') {
        try {
            pywebview.api.handle_comfyui_download(event.data.url, event.data.filename);
        } catch(e) {}
    }
});

</script>
</body>
</html>"""


def _load_ico_as_base64():
    ico_w, ico_h = 256, 256
    if not os.path.exists(ICO_PATH):
        return "", ico_w, ico_h
    try:
        from PIL import Image
        import io as _io
        with Image.open(ICO_PATH) as im:
            frames = []
            try:
                for _i in range(getattr(im, 'n_frames', 1)):
                    im.seek(_i)
                    frames.append((im.size[0] * im.size[1], im.copy()))
            except EOFError:
                pass
            best = max(frames, key=lambda x: x[0])[1] if frames else im
            ico_w, ico_h = best.size
            buf = _io.BytesIO()
            best.convert("RGBA").save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
        return f'url("data:image/png;base64,{b64}")', ico_w, ico_h
    except Exception:
        pass
    try:
        with open(ICO_PATH, "rb") as _f:
            b64 = base64.b64encode(_f.read()).decode()
        return f'url("data:image/x-icon;base64,{b64}")', ico_w, ico_h
    except Exception:
        return "", ico_w, ico_h

def _get_shell_html(settings=None):
    settings = settings or {}
    custom_bg  = settings.get("console_bg_image", "").strip()
    bg_fit     = settings.get("console_bg_fit", "fit")
    bg_opacity = settings.get("console_bg_opacity", 0.12)

    ico_opacity = str(round(float(bg_opacity), 4))
    ico_repeat  = "no-repeat"

    _ico_css, ico_w, ico_h = _load_ico_as_base64()
    if custom_bg and os.path.isfile(custom_bg):
        ext  = os.path.splitext(custom_bg)[1].lower().lstrip(".")
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "webp": "image/webp"}.get(ext, "image/png")
        try:
            with open(custom_bg, "rb") as _f:
                b64 = base64.b64encode(_f.read()).decode()
            ico_css = f'url("data:{mime};base64,{b64}")'
        except Exception:
            ico_css = ""
        fit_map = {
            "fit":     ("contain",   "no-repeat"),
            "stretch": ("100% 100%", "no-repeat"),
            "tile":    ("auto",      "repeat"),
            "center":  ("auto",      "no-repeat"),
        }
        ico_size, ico_repeat = fit_map.get(bg_fit, ("contain", "no-repeat"))
        ico_pos = "inset: 0; width: auto; height: auto; transform: none;"
    elif _ico_css:
        ico_css  = _ico_css
        ico_size = f"{ico_w}px {ico_h}px"
        ico_pos  = (f"width: {ico_w}px; height: {ico_h}px;\n"
                    f"    top: 50%; left: 50%; transform: translate(-50%, -50%);")
    else:
        ico_css  = ""
        ico_size = "256px 256px"
        ico_pos  = "width: 256px; height: 256px;\n    top: 50%; left: 50%; transform: translate(-50%, -50%);"

    return (SHELL_HTML
            .replace("{ICO_BG}",      ico_css)
            .replace("{ICO_POS}",     ico_pos)
            .replace("{ICO_SIZE}",    ico_size)
            .replace("{ICO_REPEAT}",  ico_repeat)
            .replace("{ICO_OPACITY}", ico_opacity)
            .replace("{EZI_VERSION}", APP_VERSION))

async def make_proxy_app(comfy_port_holder, storage_holder, settings_holder=None):
    async def handle_shell(request):
        s = settings_holder[0] if settings_holder else {}
        return web.Response(text=_get_shell_html(s), content_type='text/html', charset='utf-8')

    async def handle_any(request):
        comfy_port = comfy_port_holder[0]
        comfy_host = f"127.0.0.1:{comfy_port}"
        path_qs    = request.path_qs

        if (request.headers.get('Upgrade', '').lower() == 'websocket'):
            ws_server = web.WebSocketResponse(); await ws_server.prepare(request)
            async with ClientSession() as session:
                async with session.ws_connect(f"ws://{comfy_host}{path_qs}") as ws_client:
                    async def fwd(src, dst):
                        async for msg in src:
                            if msg.type == WSMsgType.TEXT: await dst.send_str(msg.data)
                            elif msg.type == WSMsgType.BINARY: await dst.send_bytes(msg.data)
                    await asyncio.gather(fwd(ws_server, ws_client), fwd(ws_client, ws_server))
            return ws_server

        try:
            async with ClientSession(timeout=ClientTimeout(total=120)) as session:
                fwd_hd = {k:v for k,v in request.headers.items() if k.lower() not in ('content-encoding','transfer-encoding')}
                fwd_hd.update({'Host': comfy_host, 'Origin': f"http://{comfy_host}"})
                async with session.request(request.method, f"http://{comfy_host}{path_qs}", headers=fwd_hd, data=await request.read(), allow_redirects=False) as resp:
                    body = await resp.read()
                    resp_hd = {k: v for k, v in resp.headers.items() if k.lower() not in ('content-encoding', 'transfer-encoding', 'content-length')}

                    is_ezi_webview = EZI_UA_TAG in request.headers.get('User-Agent', '')
                    if is_ezi_webview and request.path == '/' and 'text/html' in resp.headers.get('Content-Type', '').lower():
                        html = body.decode('utf-8', errors='replace')

                        stored_data = storage_holder[0]
                        if stored_data:
                            try:
                                data_str = json.dumps(stored_data).replace('</', '<\\/')
                                inject_js = f"""<script>
    (function() {{
        try {{
            var data = {data_str};
            if (data.ls) {{ Object.keys(data.ls).forEach(function(k) {{ try {{ localStorage.setItem(k, data.ls[k]); }} catch(e) {{}} }}); }}
            if (data.ss) {{ Object.keys(data.ss).forEach(function(k) {{ try {{ sessionStorage.setItem(k, data.ss[k]); }} catch(e) {{}} }}); }}
        }} catch(e) {{}}

        var _eziComfyReady = false;
        var _OrigWS = window.WebSocket;
        function _eziCheckMsg(data) {{
            if (_eziComfyReady) return;
            try {{
                var d = JSON.parse(data);
                if (d && d.type === 'status') {{
                    _eziComfyReady = true;
                    window.parent.postMessage({{ type: 'ezi_comfy_ready' }}, '*');
                }}
            }} catch(e) {{}}
        }}
        window.WebSocket = function(url, protocols) {{
            var ws = protocols ? new _OrigWS(url, protocols) : new _OrigWS(url);
            var _origAEL = ws.addEventListener.bind(ws);
            ws.addEventListener = function(type, fn, opts) {{
                if (type === 'message' && !_eziComfyReady) {{
                    return _origAEL('message', function(ev) {{ _eziCheckMsg(ev.data); return fn.apply(this, arguments); }}, opts);
                }}
                return _origAEL(type, fn, opts);
            }};
            var _onmsg = null;
            Object.defineProperty(ws, 'onmessage', {{
                get: function() {{ return _onmsg; }},
                set: function(fn) {{
                    _onmsg = fn ? function(ev) {{ _eziCheckMsg(ev.data); return fn.apply(this, arguments); }} : fn;
                }},
                configurable: true
            }});
            return ws;
        }};
        window.WebSocket.prototype = _OrigWS.prototype;
        window.WebSocket.CONNECTING = _OrigWS.CONNECTING;
        window.WebSocket.OPEN = _OrigWS.OPEN;
        window.WebSocket.CLOSING = _OrigWS.CLOSING;
        window.WebSocket.CLOSED = _OrigWS.CLOSED;

        var _origOpen = window.open;
        window.open = function(url, target, features) {{
            if (url && (
                url.includes('accounts.google.com') ||
                url.includes('github.com/login') ||
                url.includes('/__/auth/') ||
                url.includes('/api/auth/signin')
            )) {{
                try {{
                    window.parent.postMessage({{ type: 'ezi_open_auth_popup', url: url }}, '*');
                }} catch(e) {{}}
                var fakeWin = {{
                    closed: false,
                    close: function() {{ this.closed = true; }},
                    focus: function() {{}},
                    postMessage: function() {{}}
                }};
                return fakeWin;
            }}
            return _origOpen.call(this, url, target, features);
        }};

        var _origConsoleError = console.error;
        console.error = function() {{
            var args = Array.from(arguments);
            var errStr = args.join(' ');
            if (errStr.includes('Firebase: Error (auth/popup') ||
                errStr.includes('Firebase: Error (auth/cancelled-popup-request')) {{
                return;
            }}
            return _origConsoleError.apply(console, args);
        }};

        window.addEventListener('unhandledrejection', function(event) {{
            if (event.reason && event.reason.code && event.reason.code.startsWith('auth/')) {{
                event.preventDefault();
            }}
        }});

        var _origAClick = HTMLAnchorElement.prototype.click;
        HTMLAnchorElement.prototype.click = function() {{
            if (this.hasAttribute('download') && this.href) {{
                try {{
                    var filename = this.getAttribute('download') || 'download';

                    if (this.href.startsWith('blob:')) {{
                        var xhr = new XMLHttpRequest();
                        xhr.open('GET', this.href, true);
                        xhr.responseType = 'blob';
                        xhr.onload = function(e) {{
                            if (this.status == 200) {{
                                var myBlob = this.response;
                                var reader = new FileReader();
                                reader.onload = function() {{
                                    var textData = reader.result;
                                    window.parent.postMessage({{
                                        type: 'ezi_save_blob',
                                        filename: filename,
                                        content: textData
                                    }}, '*');
                                }};
                                reader.readAsText(myBlob);
                            }}
                        }};
                        xhr.send();
                        return;
                    }}

                    var urlObj = new URL(this.href, window.location.origin);
                    var relativeUrl = urlObj.pathname + urlObj.search;
                    window.parent.postMessage({{ type: 'ezi_save_image', url: relativeUrl, filename: filename }}, '*');
                    return;
                }} catch(e) {{ console.error("Download interceptor error:", e); }}
            }}
            return _origAClick.apply(this, arguments);
        }};
    }})();
    </script>"""
                                idx = html.lower().find('<head>')
                                if idx != -1:
                                    html = html[:idx+6] + inject_js + html[idx+6:]
                                else:
                                    html = inject_js + html
                            except Exception:
                                pass

                        cmenu_js = """<script>
    (function() {
        function initCMenu() {
            if (document.getElementById('ezi-cmenu')) return;
            var m = document.createElement('div');
            m.id = 'ezi-cmenu';
            m.style.cssText = 'position:fixed;background:var(--comfy-menu-bg, #1e1e1e);border:1px solid var(--border-color, #444);border-radius:6px;padding:4px 0;z-index:9999999;display:none;font-size:12px;color:var(--input-text, #cccccc);box-shadow:0 6px 16px rgba(0,0,0,0.3);font-family:Segoe UI, Tahoma, Geneva, Verdana, sans-serif;min-width:220px;';
            document.body.appendChild(m);

            function addItem(txt, shortcut, fn, addSeparator) {
                if (addSeparator) {
                    var sep = document.createElement('div');
                    sep.style.cssText = 'height:1px;background-color:var(--border-color, #444);margin:4px 0;';
                    m.appendChild(sep);
                }
                var i = document.createElement('div');
                var textSpan = document.createElement('span');
                textSpan.innerText = txt;
                var shortcutSpan = document.createElement('span');
                shortcutSpan.innerText = shortcut;
                shortcutSpan.style.cssText = 'color:var(--descrip-text, #888);font-size:11px;float:right;margin-left:20px;';
                i.appendChild(textSpan);
                i.appendChild(shortcutSpan);
                i.style.cssText = 'padding:6px 24px 6px 12px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;clear:both;';

                i.onmouseover = function() {
                    this.style.background='var(--comfy-menu-secondary-bg, #2a2a2a)';
                    this.style.color='var(--fg-color, #ffffff)';
                };
                i.onmouseout = function() {
                    this.style.background='';
                    this.style.color='var(--input-text, #cccccc)';
                };
                i.onclick = function(e) { e.stopPropagation(); fn(); m.style.display='none'; };
                m.appendChild(i);
            }

            addItem('Undo', 'Ctrl+Z', function() {
                var el = m.tgt; el.focus(); document.execCommand('undo');
            });

            addItem('Redo', 'Ctrl+Y', function() {
                var el = m.tgt; el.focus(); document.execCommand('redo');
            }, true);

            addItem('Cut', 'Ctrl+X', function() {
                var el = m.tgt;
                window.parent.postMessage({ type: 'ezi_clipboard_request', action: 'cut', text: el.value.substring(el.selectionStart, el.selectionEnd) }, '*');
                el.focus();
                document.execCommand('delete');
            }, true);

            addItem('Copy', 'Ctrl+C', function() {
                var el = m.tgt;
                window.parent.postMessage({ type: 'ezi_clipboard_request', action: 'copy', text: el.value.substring(el.selectionStart, el.selectionEnd) }, '*');
            });

            addItem('Paste', 'Ctrl+V', function() {
                var el = m.tgt;
                el.focus();
                window.parent.postMessage({ type: 'ezi_clipboard_request', action: 'paste' }, '*');
                window.addEventListener('message', function handler(ev) {
                    if (ev.data && ev.data.type === 'ezi_clipboard_response') {
                        window.removeEventListener('message', handler);
                        document.execCommand('insertText', false, ev.data.text);
                    }
                });
            });

            addItem('Delete', 'Del', function() {
                var el = m.tgt; el.focus(); document.execCommand('delete');
            }, true);

            addItem('Select All', 'Ctrl+A', function() {
                var el = m.tgt; el.focus(); el.select();
            });

            document.addEventListener('click', function() { m.style.display='none'; });
            document.addEventListener('contextmenu', function(e) {
                var t = e.target;
                if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable) {
                    e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation();
                    t.focus(); m.tgt = t;
                    m.style.left = e.clientX + 'px'; m.style.top = e.clientY + 'px'; m.style.display = 'block';
                } else { m.style.display='none'; }
            }, true);
        }
        if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', initCMenu); } else { initCMenu(); }
    })();
    </script>"""
                        html = html.replace('</body>', cmenu_js + '</body>')

                        body = html.encode('utf-8')

                    return web.Response(status=resp.status, headers=resp_hd, body=body)
        except: return web.Response(status=502)

    app = web.Application(client_max_size=1024*1024*1024)
    app.router.add_get('/__shell__', handle_shell)
    app.router.add_route('*', '/{path_info:.*}', handle_any)
    return app

def _is_rect_on_active_monitor(left, top, right, bottom):
    try:
        import ctypes.wintypes as wt
        user32 = ctypes.windll.user32

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize",    wt.DWORD),
                        ("rcMonitor", wt.RECT),
                        ("rcWork",    wt.RECT),
                        ("dwFlags",   wt.DWORD)]

        monitors = []
        MonitorEnumProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_void_p, ctypes.c_void_p,
            ctypes.POINTER(wt.RECT), ctypes.c_double
        )

        def _cb(hmon, hdc, lprect, lparam):
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                r = info.rcWork
                monitors.append((r.left, r.top, r.right, r.bottom))
            return True

        user32.EnumDisplayMonitors(None, None, MonitorEnumProc(_cb), 0)

        MIN_W, MIN_H = 100, 50
        for ml, mt, mr, mb in monitors:
            ol = max(left, ml)
            ot = max(top,  mt)
            or_ = min(right, mr)
            ob  = min(bottom, mb)
            if (or_ - ol) >= MIN_W and (ob - ot) >= MIN_H:
                return True
        return False
    except Exception:
        return True


class Api:
    _NO_WIN        = 0x08000000
    _NO_WIN_HIDDEN = 0x08000000 | 0x20000000
    PY_EXE         = os.path.join(ROOT_DIR, "python_embeded", "python.exe")
    COMFY_DIR      = os.path.join(ROOT_DIR, "ComfyUI")

    def exit_app(self):
        self.save_window_state()
        self._confirm_close = True
        self._graceful_close()

    def restart_ezi(self):
        self.save_window_state()
        self._confirm_close = True

        try:
            self._kill_running_proc()
        except Exception:
            pass

        time.sleep(2.0)

        try:
            subprocess.Popen(
                [sys.executable] + sys.argv,
                cwd=os.getcwd(),
                creationflags=0x00000008,
            )
        except Exception as e:
            _log("RESTART", f"relaunch failed: {e}")

        self._graceful_close()

    def restart_after_update(self):
        self._safe_eval("document.getElementById('modal-overlay').classList.remove('active');")
        self._safe_eval("switchToConsole()")
        self._updating = False
        self._restart_comfy()

    def read_clipboard(self):
        try:
            import ctypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            try:
                ctypes.windll.ole32.OleInitialize(None)
            except Exception:
                pass

            user32.OpenClipboard.argtypes = [ctypes.c_void_p]
            user32.OpenClipboard.restype = ctypes.c_int
            user32.GetClipboardData.argtypes = [ctypes.c_uint]
            user32.GetClipboardData.restype = ctypes.c_void_p
            kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalUnlock.restype = ctypes.c_int
            user32.CloseClipboard.argtypes = []
            user32.CloseClipboard.restype = ctypes.c_int

            if not user32.OpenClipboard(0):
                return ""
            try:
                handle = user32.GetClipboardData(13)
                if not handle:
                    return ""
                ptr = kernel32.GlobalLock(handle)
                if not ptr:
                    return ""
                try:
                    return ctypes.c_wchar_p(ptr).value or ""
                finally:
                    kernel32.GlobalUnlock(handle)
            finally:
                user32.CloseClipboard()
        except Exception:
            return ""

    def write_clipboard(self, text):
        try:
            import ctypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            try:
                ctypes.windll.ole32.OleInitialize(None)
            except Exception:
                pass

            user32.OpenClipboard.argtypes = [ctypes.c_void_p]
            user32.OpenClipboard.restype = ctypes.c_int
            user32.EmptyClipboard.argtypes = []
            user32.EmptyClipboard.restype = ctypes.c_int
            user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
            user32.SetClipboardData.restype = ctypes.c_void_p
            kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
            kernel32.GlobalAlloc.restype = ctypes.c_void_p
            kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalUnlock.restype = ctypes.c_int
            kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
            kernel32.GlobalFree.restype = ctypes.c_void_p
            user32.CloseClipboard.argtypes = []
            user32.CloseClipboard.restype = ctypes.c_int

            if not user32.OpenClipboard(0):
                return
            user32.EmptyClipboard()

            try:
                buf = ctypes.create_unicode_buffer(text)
                size = ctypes.sizeof(buf)

                GMEM_MOVEABLE = 0x0002
                h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
                if not h_mem:
                    return

                ptr = kernel32.GlobalLock(h_mem)
                if not ptr:
                    kernel32.GlobalFree(h_mem)
                    return

                try:
                    ctypes.memmove(ptr, buf, size)
                finally:
                    kernel32.GlobalUnlock(h_mem)

                if not user32.SetClipboardData(13, h_mem):
                    kernel32.GlobalFree(h_mem)
            finally:
                user32.CloseClipboard()
        except Exception:
            pass

    def save_blob_data(self, filename, content):
        threading.Thread(target=self._do_save_blob, args=(filename, content), daemon=True).start()

    def _do_save_blob(self, filename, content):
        if not self._window:
            return

        ext = os.path.splitext(filename)[1].lower()
        if ext in ('.json', '.txt', '.yaml', '.yml'):
            file_types = ("JSON Files (*.json)", "Text Files (*.txt)", "All Files (*.*)")
        else:
            file_types = ("All Files (*.*)",)

        save_path = None
        try:
            result = self._window.create_file_dialog(
                SAVE_DIALOG_TYPE,
                directory=self._last_save_dir,
                save_filename=filename,
                file_types=file_types
            )
            if result:
                save_path = result[0] if isinstance(result, (list, tuple)) else result
                self._last_save_dir = os.path.dirname(save_path)
                self._settings["last_save_dir"] = self._last_save_dir
                _save_settings(self._settings)
        except Exception:
            pass

        if save_path:
            try:
                with open(save_path, 'w', encoding='utf-8') as f:
                    f.write(content)
            except Exception as e:
                self._println(f"[Save Blob] Error: {e}\n")

    def open_auth_popup(self, url):
        msg = (
            "Google sign-in doesn't work inside the desktop app - Google "
            "blocks embedded browsers for security. The desktop app uses a "
            "<b>Comfy API Key</b> instead.<br><br>"
            "<b>Step-by-step:</b><br>"
            "1. Click <i>Get a key in browser</i> below - your Comfy "
            "account page will open in your default browser.<br>"
            "2. Sign in there with Google (it only works in a real "
            "browser).<br>"
            "3. On the <i>API Keys</i> page, click <b>+ New API Key</b> "
            "(top-right).<br>"
            "4. Type any name you want (e.g. <i>Desktop EZi</i>), leave "
            "<i>Description</i> blank, then click <b>Generate</b>.<br>"
            "5. The key is shown <u>only once</u>. Click the <i>copy</i> "
            "icon on the right of the key field.<br>"
            "6. Come back here, paste the key into the field below and "
            "click <i>Apply</i>. That's it &mdash; the desktop app will "
            "fill ComfyUI's API Key dialog and sign you in "
            "automatically.<br><br>"
            "<input type='password' id='ezi-api-key' placeholder='Paste your API key here' "
            "style='width:100%;padding:8px;background:#111;color:#ccc;"
            "border:1px solid #555;border-radius:4px;font-family:monospace;"
            "box-sizing:border-box;margin-top:4px;'>"
        )
        safe_msg = json.dumps(msg)
        js = (
            "showModal('\\uD83D\\uDD11', 'Sign in with a Comfy API Key', " + safe_msg + ", ["
            "{ label: 'Cancel', cls: '', action: function(){} },"
            "{ label: 'Get a key in browser', cls: '', noClose: true, "
            "  action: function(){ try { pywebview.api.open_url('https://platform.comfy.org/profile/api-keys'); } catch(e){} } },"
            "{ label: 'Apply', cls: 'primary', "
            "  action: function(){"
            "    var el = document.getElementById('ezi-api-key');"
            "    var k = el && el.value ? el.value.trim() : '';"
            "    try { pywebview.api.apply_api_key(k); } catch(e){}"
            "  } }"
            "]);"
            "setTimeout(function(){"
            "  var el = document.getElementById('ezi-api-key');"
            "  if (el) el.focus();"
            "}, 50);"
        )
        try:
            self._safe_eval(js)
        except Exception:
            pass

    def apply_api_key(self, key):
        key = (key or '').strip()
        if not key:
            self._println("[Auth] No API key provided\n")
            return
        try:
            self.write_clipboard(key)
        except Exception as e:
            self._println(f"[Auth] clipboard write failed: {e}\n")

        key_js = json.dumps(key)
        auto_js = (
            "(function(){"
            "  try {"
            "    var iframe = document.getElementById('ui-frame');"
            "    var doc = iframe && iframe.contentDocument;"
            "    var win = iframe && iframe.contentWindow;"
            "    if (!doc || !win) return 'no-doc';"
            "    var KEY = " + key_js + ";"
            "    var clicked = false;"
            "    var cands = doc.querySelectorAll('button, [role=\"button\"], a');"
            "    for (var i = 0; i < cands.length; i++) {"
            "      var txt = (cands[i].textContent || '').trim();"
            "      if (txt === 'Comfy API Key' || txt.indexOf('Comfy API Key') !== -1) {"
            "        cands[i].click(); clicked = true; break;"
            "      }"
            "    }"
            "    function clickUseApiKey(){"
            "      var bs = doc.querySelectorAll('button');"
            "      for (var j = 0; j < bs.length; j++) {"
            "        var t = (bs[j].textContent || '').trim();"
            "        if (/API Key/i.test(t) && !/Comfy API Key/i.test(t)) { bs[j].click(); return true; }"
            "      }"
            "      return false;"
            "    }"
            "    function submitForm(input){"
            "      var form = input.closest('form');"
            "      if (!form) return false;"
            "      try { if (typeof form.requestSubmit === 'function') { form.requestSubmit(); return true; } } catch(e){}"
            "      var btn = form.querySelector('button[type=\"submit\"]');"
            "      try { form.dispatchEvent(new win.Event('submit', {bubbles: true, cancelable: true})); } catch(e){}"
            "      if (btn && !btn.disabled) { btn.click(); return true; }"
            "      return false;"
            "    }"
            "    var tries = 0;"
            "    function fill(){"
            "      tries++;"
            "      var input = doc.getElementById('comfy-org-api-key');"
            "      if (!input) {"
            "        if (tries === 5) { clickUseApiKey(); }"
            "        if (tries < 80) { setTimeout(fill, 100); return; }"
            "        return;"
            "      }"
            "      try { input.focus(); } catch(e){}"
            "      var setter = null;"
            "      try { setter = Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value').set; } catch(e){}"
            "      try {"
            "        if (setter) setter.call(input, ''); else input.value = '';"
            "        input.dispatchEvent(new win.Event('input', {bubbles: true}));"
            "      } catch(e){}"
            "      try {"
            "        if (setter) setter.call(input, KEY); else input.value = KEY;"
            "      } catch(e) { input.value = KEY; }"
            "      input.dispatchEvent(new win.Event('input', {bubbles: true}));"
            "      input.dispatchEvent(new win.Event('change', {bubbles: true}));"
            "      var submitTries = 0;"
            "      function trySubmit(){"
            "        submitTries++;"
            "        if (submitForm(input)) return;"
            "        try {"
            "          var ev = new win.KeyboardEvent('keydown', {key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true, cancelable:true});"
            "          input.dispatchEvent(ev);"
            "          var ev2 = new win.KeyboardEvent('keypress', {key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true, cancelable:true});"
            "          input.dispatchEvent(ev2);"
            "        } catch(e){}"
            "        if (submitTries < 10) setTimeout(trySubmit, 200);"
            "      }"
            "      setTimeout(trySubmit, 400);"
            "    }"
            "    setTimeout(fill, 300);"
            "    return clicked ? 'auto' : 'no-button';"
            "  } catch(e) { return 'err:' + String(e); }"
            "})();"
        )
        def _do():
            try:
                result = self._window.evaluate_js(auto_js)
                self._println(f"[Auth] API key auto-apply: {result}\n")
            except Exception as e:
                self._println(f"[Auth] auto-apply error: {e}\n")
        threading.Thread(target=_do, daemon=True).start()

    def __init__(self, proxy_port, comfy_port_holder, settings, storage_holder, settings_holder=None):
        self._window, self._proc = None, None
        self._settings = settings
        self._storage_holder = storage_holder
        self._settings_holder = settings_holder
        self._last_save_dir = settings.get("last_save_dir", os.path.expanduser("~"))
        self._url_found, self._started, self._js_ready = False, False, threading.Event()
        self._updating = False
        self._confirm_close = False
        self._ui_shown = False
        self._restarting = False
        self._run_id = 0
        self._line_buf, self._buf_lock = [], threading.Lock()
        self._columns = 120
        self._skip_next_newline = False
        self._console_detached = False
        self._main_hwnd = None
        self._ctrl_handler_ref = None
        self._console_close_decision = None
        self._proxy_port, self._comfy_port_holder = proxy_port, comfy_port_holder
        if sys.platform == "win32":
            hwnd = ctypes.WinDLL('kernel32').GetConsoleWindow()
            if hwnd: ctypes.WinDLL('user32').ShowWindow(hwnd, 0)

    def handle_comfyui_download(self, url, filename):
        threading.Thread(target=self._do_handle_download, args=(url, filename), daemon=True).start()

    def _do_handle_download(self, url, filename):
        import urllib.request
        port = self._comfy_port_holder[0]
        if not port:
            return

        full_url = f"http://127.0.0.1:{port}{url}"

        try:
            req = urllib.request.Request(full_url)
            with urllib.request.urlopen(req, timeout=15) as response:
                file_data = response.read()

            if not self._window:
                return

            ext = os.path.splitext(filename)[1].lower()
            if ext in ('.mp4', '.webm', '.avi', '.mov', '.mkv'):
                file_types = ("Video Files (*.mp4;*.webm;*.avi;*.mov;*.mkv)", "All Files (*.*)")
            elif ext in ('.wav', '.mp3', '.ogg', '.flac', '.aac'):
                file_types = ("Audio Files (*.wav;*.mp3;*.ogg;*.flac;*.aac)", "All Files (*.*)")
            elif ext in ('.gif',):
                file_types = ("GIF Image (*.gif)", "All Files (*.*)")
            else:
                file_types = ("Image Files (*.png;*.jpg;*.jpeg;*.webp)", "All Files (*.*)")

            save_path = None
            try:
                result = self._window.create_file_dialog(
                    SAVE_DIALOG_TYPE,
                    directory=self._last_save_dir,
                    save_filename=filename,
                    file_types=file_types
                )
                if result:
                    save_path = result[0] if isinstance(result, (list, tuple)) else result
                    self._last_save_dir = os.path.dirname(save_path)
                    self._settings["last_save_dir"] = self._last_save_dir
                    _save_settings(self._settings)
            except Exception:
                pass

            if save_path:
                with open(save_path, 'wb') as f:
                    f.write(file_data)

        except Exception as e:
            self._println(f"[Save Media] Error: {e}\n")

    def confirm_close(self):
        if not self._updating:
            self.save_window_state()
        self._confirm_close = True
        self._graceful_close()

    def modal_response(self, result, action):
        if action == 'close':
            if result:
                if not self._updating:
                    self.save_window_state()
                self._confirm_close = True
                self._graceful_close()
            else:
                if self._console_detached:
                    try:
                        c = ctypes.windll.kernel32.GetConsoleWindow()
                        if c:
                            ctypes.windll.user32.ShowWindow(c, 9)
                    except Exception:
                        pass
        elif action == 'update':
            if result:
                bat = os.path.join(ROOT_DIR, 'Update ComfyUI.bat')
                threading.Thread(target=self._do_update, args=(bat,), daemon=True).start()

    def _graceful_close(self):
        try:
            self._window.evaluate_js("_saveTabsToDisk();")
        except Exception:
            pass

        time.sleep(0.2)

        if self._ui_shown:
            try:
                result = self._window.evaluate_js("""
                    (function() {
                        try {
                            var f = document.getElementById('ui-frame');
                            if (!f || !f.contentWindow) return null;
                            var w = f.contentWindow;
                            var out = { ls: {}, ss: {} };
                            try {
                                var ls = w.localStorage;
                                for (var i = 0; i < ls.length; i++) {
                                    var k = ls.key(i);
                                    if (k) out.ls[k] = ls.getItem(k);
                                }
                            } catch(e) {}
                            try {
                                var ss = w.sessionStorage;
                                for (var j = 0; j < ss.length; j++) {
                                    var sk = ss.key(j);
                                    if (sk) out.ss[sk] = ss.getItem(sk);
                                }
                            } catch(e) {}
                            return JSON.stringify(out);
                        } catch(e) { return null; }
                    })();
                """)
                if result:
                    self.save_comfy_storage(result)
            except Exception:
                pass

        try:
            self._safe_eval("""
                (function() {
                    try {
                        var f = document.getElementById('ui-frame');
                        if (!f) return;
                        try {
                            var w = f.contentWindow;
                            if (w) w.onbeforeunload = null;
                        } catch(e2) {}
                        f.src = 'about:blank';
                    } catch(e) {}
                })();
            """)
        except Exception:
            pass

        def _delayed_destroy():
            time.sleep(0.4)
            if self._window:
                self._window.destroy()
        threading.Thread(target=_delayed_destroy, daemon=True).start()

    def set_window(self, w):
        self._window = w

    def set_title(self, suffix: str = ""):
        if self._window:
            try:
                t = f'EZi  v{APP_VERSION}'
                self._window.set_title(t + (f' - {suffix}' if suffix else ''))
            except Exception:
                pass

    def js_ready(self, cols=0):
        try:
            if cols and int(cols) > 0:
                self._columns = max(40, int(cols))
        except Exception:
            pass
        self._js_ready.set()
        with self._buf_lock: buf, self._line_buf = self._line_buf, []
        for text in buf: self._eval_line(text)
        if not self._started:
            self._started = True
            threading.Thread(target=self._run, daemon=True).start()
            threading.Thread(target=self._check_update, daemon=True).start()
            threading.Thread(target=self._check_ezi_update, daemon=True).start()
            threading.Thread(target=self._port_monitor, daemon=True).start()

    def set_columns(self, cols):
        try:
            self._columns = max(40, int(cols))
        except Exception:
            pass

    def _is_maximized(self):
        try:
            import ctypes.wintypes as wt
            hwnd = _get_hwnd(self._window)
            if not hwnd:
                return False
            class WINDOWPLACEMENT(ctypes.Structure):
                _fields_ = [("length", wt.UINT), ("flags", wt.UINT), ("showCmd", wt.UINT),
                            ("ptMinPosition", wt.POINT), ("ptMaxPosition", wt.POINT),
                            ("rcNormalPosition", wt.RECT)]
            wp = WINDOWPLACEMENT()
            wp.length = ctypes.sizeof(WINDOWPLACEMENT)
            ctypes.windll.user32.GetWindowPlacement(hwnd, ctypes.byref(wp))
            return wp.showCmd == 3
        except Exception:
            return False

    def _get_columns(self):
        try:
            if self._window:
                result = self._window.evaluate_js(
                    "(function(){"
                    "var canvas=document.createElement('canvas');"
                    "var ctx=canvas.getContext('2d');"
                    "ctx.font='12px Consolas,\"Courier New\",monospace';"
                    "var charW=ctx.measureText('M').width||7.2;"
                    "var t=document.getElementById('term-panel');"
                    "var style=window.getComputedStyle(t);"
                    "var padL=parseFloat(style.paddingLeft)||0;"
                    "var padR=parseFloat(style.paddingRight)||0;"
                    "var scrollbarW=Math.max(t.offsetWidth-t.clientWidth,17);"
                    "var usable=t.clientWidth-padL-padR-scrollbarW-2;"
                    "var cols=Math.floor(usable/charW);"
                    "return cols>0?cols:0;"
                    "})()"
                )
                if result and int(result) > 0:
                    cols = max(40, int(result))
                    if not self._is_maximized():
                        cols = min(cols, 80)
                    return cols
        except Exception:
            pass
        return self._columns

    def ui_shown(self):
        self._ui_shown = True

    def on_loaded(self):
        hwnd = _get_hwnd(self._window)
        if hwnd:
            self._main_hwnd = hwnd
        _set_window_icon(hwnd)

    def _kill_process_tree(self, root_pid):
        try:
            kernel = ctypes.windll.kernel32
            PROCESS_TERMINATE = 0x0001
            SYNCHRONIZE = 0x00100000
            TH32CS_SNAPPROCESS = 0x00000002

            class PROCESSENTRY32(ctypes.Structure):
                _fields_ = [
                    ("dwSize",              ctypes.c_uint32),
                    ("cntUsage",            ctypes.c_uint32),
                    ("th32ProcessID",       ctypes.c_uint32),
                    ("th32DefaultHeapID",   ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID",        ctypes.c_uint32),
                    ("cntThreads",          ctypes.c_uint32),
                    ("th32ParentProcessID", ctypes.c_uint32),
                    ("pcPriClassBase",      ctypes.c_long),
                    ("dwFlags",             ctypes.c_uint32),
                    ("szExeFile",           ctypes.c_char * 260),
                ]

            def _kill(pid):
                snap = kernel.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
                if snap == ctypes.c_void_p(-1).value:
                    return
                children = []
                try:
                    entry = PROCESSENTRY32()
                    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
                    if kernel.Process32First(snap, ctypes.byref(entry)):
                        while True:
                            if entry.th32ParentProcessID == pid:
                                children.append(entry.th32ProcessID)
                            if not kernel.Process32Next(snap, ctypes.byref(entry)):
                                break
                finally:
                    kernel.CloseHandle(snap)
                for child_pid in children:
                    _kill(child_pid)
                h = kernel.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, pid)
                if h:
                    kernel.TerminateProcess(h, 1)
                    kernel.WaitForSingleObject(h, 3000)
                    kernel.CloseHandle(h)

            _kill(root_pid)
        except Exception:
            pass

    def _kill_port_owner(self, port):
        try:
            iphlpapi = ctypes.windll.iphlpapi

            class MIB_TCPROW_OWNER_PID(ctypes.Structure):
                _fields_ = [
                    ('dwState',      ctypes.c_ulong),
                    ('dwLocalAddr',  ctypes.c_ulong),
                    ('dwLocalPort',  ctypes.c_ulong),
                    ('dwRemoteAddr', ctypes.c_ulong),
                    ('dwRemotePort', ctypes.c_ulong),
                    ('dwOwningPid',  ctypes.c_ulong),
                ]

            buf_size = ctypes.c_ulong(0)
            iphlpapi.GetExtendedTcpTable(None, ctypes.byref(buf_size), False, 2, 5, 0)
            buf = (ctypes.c_byte * buf_size.value)()
            if iphlpapi.GetExtendedTcpTable(buf, ctypes.byref(buf_size), False, 2, 5, 0) == 0:
                count = ctypes.c_ulong.from_buffer(buf).value
                offset = ctypes.sizeof(ctypes.c_ulong)
                row_sz = ctypes.sizeof(MIB_TCPROW_OWNER_PID)
                for i in range(count):
                    row = MIB_TCPROW_OWNER_PID.from_buffer(buf, offset + i * row_sz)
                    local_port = ((row.dwLocalPort & 0xFF) << 8) | ((row.dwLocalPort >> 8) & 0xFF)
                    if local_port == port:
                        pid = row.dwOwningPid
                        if pid and pid != os.getpid():
                            try:
                                self._kill_process_tree(pid)
                            except Exception:
                                pass
        except Exception:
            pass

    def _kill_running_proc(self):
        port = self._comfy_port_holder[0]

        self._restarting = False

        started_own_proc = self._proc is not None

        if self._proc:
            try:
                self._kill_process_tree(self._proc.pid)
            except Exception:
                pass
            self._proc = None

        if port and started_own_proc:
            self._kill_port_owner(port)

        if port and started_own_proc:
            for _ in range(50):
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(0.2)
                        if s.connect_ex(('127.0.0.1', port)) != 0:
                            break
                except Exception:
                    break
                time.sleep(0.1)

    def _port_monitor(self):
        was_up = False
        down_count = 0
        restart_start_time = 0

        while self._window:
            time.sleep(0.5)
            if self._updating:
                was_up = False
                down_count = 0
                continue

            port = self._comfy_port_holder[0]
            if not port:
                continue

            up = False
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    up = s.connect_ex(('127.0.0.1', port)) == 0
            except Exception:
                pass

            if up:
                down_count = 0
                if self._restarting:
                    try:
                        import urllib.request
                        urllib.request.urlopen(f'http://127.0.0.1:{port}/object_info', timeout=3)
                        self._restarting = False
                        self._url_found = True
                        was_up = True
                        self._safe_eval(f"set_dot_ready(); load_ui('http://127.0.0.1:{self._proxy_port}/')")
                    except Exception:
                        pass
                elif not was_up:
                    was_up = True
            else:
                if was_up and not self._restarting:
                    down_count += 1
                    if down_count >= 2:
                        was_up = False
                        down_count = 0
                        self._restarting = True
                        self._url_found = False
                        restart_start_time = time.time()
                        self._println(f"\n\033[93m⚠  ComfyUI is restarting...\033[0m")
                        self._safe_eval("switchToConsole('Restarting...')")

                if self._restarting:
                    if time.time() - restart_start_time > 300:
                        self._restarting = False
                        self._url_found = False
                        was_up = False
                        self._println(f"\n\033[91m⚠  Restart timed out. ComfyUI did not come back online.\033[0m")
                        self._safe_eval("switchToConsole('Stopped')")

    def _check_update(self):
        try:
            if not os.path.isdir(os.path.join(self.COMFY_DIR, '.git')):
                return
            self._println('\033[93mChecking for ComfyUI update...\033[0m')
            subprocess.run(['git', 'fetch', '--quiet', '--tags'], cwd=self.COMFY_DIR, capture_output=True, timeout=8, creationflags=self._NO_WIN)
            local = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                cwd=self.COMFY_DIR, capture_output=True, timeout=5, creationflags=self._NO_WIN
            ).stdout.strip().decode(errors='replace')
            for ref in ['origin/main', 'origin/master', 'origin/HEAD']:
                r = subprocess.run(
                    ['git', 'rev-parse', ref],
                    cwd=self.COMFY_DIR, capture_output=True, timeout=5, creationflags=self._NO_WIN
                )
                if r.returncode == 0:
                    remote = r.stdout.strip().decode(errors='replace')
                    break
            else:
                remote = ''
            all_tags = subprocess.run(
                ['git', 'tag', '--sort=-version:refname'],
                cwd=self.COMFY_DIR, capture_output=True, timeout=5, creationflags=self._NO_WIN
            ).stdout.decode(errors='replace').strip().splitlines()
            latest_tag = all_tags[0].strip() if all_tags else ''
            if latest_tag:
                head_r = subprocess.run(
                    ['git', 'rev-parse', 'HEAD'],
                    cwd=self.COMFY_DIR, capture_output=True, timeout=5, creationflags=self._NO_WIN
                )
                tag_r = subprocess.run(
                    ['git', 'rev-parse', f'{latest_tag}^{{}}'],
                    cwd=self.COMFY_DIR, capture_output=True, timeout=5, creationflags=self._NO_WIN
                )
                head_hash = head_r.stdout.strip().decode(errors='replace')
                tag_hash = tag_r.stdout.strip().decode(errors='replace')
                if head_hash and tag_hash and head_hash != tag_hash:
                    stable_tag = None
                    try:
                        import urllib.request as _ur, json as _json
                        req = _ur.Request(
                            'https://api.github.com/repos/comfyanonymous/ComfyUI/releases/latest',
                            headers={'User-Agent': EZI_UA_TAG}
                        )
                        with _ur.urlopen(req, timeout=8) as resp:
                            rel_data = _json.loads(resp.read())
                        stable_tag = rel_data.get('tag_name') or None
                    except Exception:
                        pass
                    is_stable = bool(stable_tag and latest_tag == stable_tag)
                    if stable_tag:
                        try:
                            import json as _json2
                            _cu_data = {}
                            if os.path.exists(SETTINGS_PATH):
                                with open(SETTINGS_PATH, 'r', encoding='utf-8') as _sf:
                                    _cu_data = _json2.loads(_sf.read())
                            _cu_data['cached_comfy_stable_version'] = stable_tag
                            _tmp = SETTINGS_PATH + '.tmp'
                            with open(_tmp, 'w', encoding='utf-8') as _sf:
                                _json2.dump(_cu_data, _sf, indent=2, ensure_ascii=False)
                            os.replace(_tmp, SETTINGS_PATH)
                        except Exception:
                            pass
                    elif not stable_tag:
                        try:
                            import json as _json2
                            if os.path.exists(SETTINGS_PATH):
                                with open(SETTINGS_PATH, 'r', encoding='utf-8') as _sf:
                                    _cu_data = _json2.loads(_sf.read())
                                _cached_stable = _cu_data.get('cached_comfy_stable_version') or None
                                is_stable = bool(_cached_stable and latest_tag == _cached_stable)
                        except Exception:
                            pass
                    self._safe_eval(f"show_update({json.dumps(latest_tag)}, {json.dumps(is_stable)})")
        except Exception:
            pass

    def _check_ezi_update(self):
        try:
            import urllib.request as _ur
            import json as _json
            self._println('\033[95mChecking for Easy-Install update...\033[0m')
            url = "https://api.github.com/repos/Tavris1/ComfyUI-Easy-Install/releases/latest"
            req = _ur.Request(url, headers={"User-Agent": EZI_UA_TAG})
            with _ur.urlopen(req, timeout=8) as r:
                data = _json.loads(r.read())
            tag = data.get("tag_name", "").strip().lstrip("v")
            if not tag:
                return
            local_parts  = [int(x) for x in APP_VERSION.split(".") if x.isdigit()]
            remote_parts = [int(x) for x in tag.split(".")      if x.isdigit()]
            if remote_parts > local_parts:
                display = "v" + tag
                self._safe_eval(f"show_ezi_update({json.dumps(display)})")
        except Exception:
            pass

    def run_update(self):
        bat = os.path.join(ROOT_DIR, 'Update ComfyUI.bat')
        if not os.path.exists(bat):
            self._safe_eval(f"show_update_missing({json.dumps(ROOT_DIR)})")
            return
        self._safe_eval("show_update_confirm()")

    def run_ezi_update(self):
        bat = os.path.join(ROOT_DIR, "Update Easy-Install.bat")
        if not os.path.exists(bat):
            self._safe_eval(f"show_update_missing({json.dumps(ROOT_DIR)})")
            return
        threading.Thread(target=self._do_run_bat, args=(bat,), daemon=True).start()

    def _do_update(self, bat):
        self._do_run_bat(bat, status_label='Updating...', hide_update_notice=True)

    def retry(self, cols=0):
        try:
            if cols and int(cols) > 0:
                self._columns = max(40, int(cols))
                os.environ['TQDM_NCOLS'] = str(self._columns)
        except Exception:
            pass
        self._restart_comfy(check_update=False)

    def _restart_comfy(self, check_update=True):
        self._started = False
        self._url_found = False
        self._ui_shown = False
        self._run_id += 1
        threading.Thread(target=self._run, daemon=True).start()
        if check_update:
            threading.Thread(target=self._check_update, daemon=True).start()
            threading.Thread(target=self._check_ezi_update, daemon=True).start()

    def _resolve_output_dir(self):
        output_dir = None
        try:
            if os.path.exists(BAT_FILE):
                with open(BAT_FILE, 'r', encoding='utf-8', errors='replace') as f:
                    bat_content = f.read()
                m_env = re.search(
                    r'(?i)set\s+"?COMFY_OUTPUT_DIR=([^"\n]+)"?',
                    bat_content
                )
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

    def get_system_info(self):
        import shutil
        import glob
        from concurrent.futures import ThreadPoolExecutor

        def _ps(cmd, timeout=8):
            return subprocess.run(
                ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', cmd],
                capture_output=True, stdin=subprocess.DEVNULL, timeout=timeout, creationflags=self._NO_WIN_HIDDEN
            )

        def _get_python():
            try:
                r = subprocess.run([self.PY_EXE, "--version"], capture_output=True, stdin=subprocess.DEVNULL, timeout=5, creationflags=self._NO_WIN)
                ver = r.stdout.decode(errors='replace').strip() or r.stderr.decode(errors='replace').strip()
                parts = ver.split()
                return parts[1] if len(parts) > 1 else ver
            except Exception:
                return 'N/A'

        def _get_torch():
            try:
                site = os.path.join(ROOT_DIR, 'python_embeded', 'Lib', 'site-packages')
                version_file = os.path.join(site, 'torch', 'version.py')
                with open(version_file, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                torch_m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
                cuda_m  = re.search(r'\bcuda(?:\s*:\s*\S+)?\s*=\s*["\']([^"\']+)["\']', content)
                tv = torch_m.group(1).split('+')[0].rsplit('.', 1)[0] if torch_m else 'N/A'
                cv = cuda_m.group(1) if cuda_m else 'N/A'
                return tv, cv
            except Exception:
                pass
            try:
                r = subprocess.run(
                    [self.PY_EXE, "-c", "import torch; v=torch.__version__.split('+')[0]; cv=torch.version.cuda or 'N/A'; print(v.rsplit('.',1)[0]+'|'+cv)"],
                    capture_output=True, stdin=subprocess.DEVNULL, timeout=10, creationflags=self._NO_WIN
                )
                out = r.stdout.decode(errors='replace').strip()
                if '|' in out:
                    torch_v, cuda_v = out.split('|', 1)
                    return torch_v, cuda_v
            except Exception:
                pass
            return 'N/A', 'N/A'

        def _get_comfyui():
            try:
                r = subprocess.run(
                    ['git', 'describe', '--tags', '--exact-match', 'HEAD'],
                    cwd=self.COMFY_DIR, capture_output=True, stdin=subprocess.DEVNULL, timeout=5, creationflags=self._NO_WIN
                )
                if r.returncode == 0:
                    return r.stdout.decode(errors='replace').strip()
                r2 = subprocess.run(
                    ['git', 'describe', '--tags', '--abbrev=0', 'HEAD'],
                    cwd=self.COMFY_DIR, capture_output=True, stdin=subprocess.DEVNULL, timeout=5, creationflags=self._NO_WIN
                )
                return r2.stdout.decode(errors='replace').strip() or 'N/A'
            except Exception:
                return 'N/A'

        def _get_frontend():
            try:
                import importlib.metadata as _im
                ver = _im.version('comfyui_frontend_package')
                if ver and ver != '0.1.0':
                    return ver
            except Exception:
                pass
            try:
                site = os.path.join(ROOT_DIR, 'python_embeded', 'Lib', 'site-packages')
                matches = sorted(glob.glob(
                    os.path.join(site, 'comfyui_frontend_package-*.dist-info', 'METADATA')
                ), reverse=True)
                for meta_path in matches:
                    with open(meta_path, 'r', encoding='utf-8', errors='replace') as f:
                        for line in f:
                            if line.startswith('Version:'):
                                ver = line.split(':', 1)[1].strip()
                                if ver and ver != '0.1.0':
                                    return ver
                            elif line.startswith('Name:') or (line.strip() == '' and line != line.lstrip()):
                                break
            except Exception:
                pass
            return 'N/A'

        def _get_ram():
            try:
                r = _ps('[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)')
                return r.stdout.decode(errors='replace').strip() + ' GB'
            except Exception:
                return 'N/A'

        def _get_pagefile():
            try:
                r = _ps(
                    "$u = Get-CimInstance Win32_PageFileUsage | Select-Object -First 1; "
                    "$s = Get-CimInstance Win32_PageFileSetting | Select-Object -First 1; "
                    "$max = if ($s) { $s.MaximumSize } else { 0 }; "
                    "$cur = if ($u) { $u.AllocatedBaseSize } else { 0 }; "
                    "Write-Output ($max.ToString() + '|' + $cur.ToString())"
                )
                out = r.stdout.decode(errors='replace').strip()
                if '|' in out:
                    max_mb, cur_mb = out.split('|', 1)
                    max_mb, cur_mb = int(max_mb.strip()), int(cur_mb.strip())
                    return f'Auto (current: {cur_mb} MB)' if max_mb == 0 else f'{max_mb} MB (current: {cur_mb} MB)'
            except Exception:
                pass
            return 'N/A'

        def _get_gpu():
            try:
                if shutil.which('nvidia-smi'):
                    r = subprocess.run(
                        ['nvidia-smi', '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader'],
                        capture_output=True, stdin=subprocess.DEVNULL, timeout=5, creationflags=self._NO_WIN
                    )
                    out = r.stdout.decode(errors='replace').strip()
                    parts = [p.strip() for p in out.split(',')]
                    gpu    = parts[0] if len(parts) > 0 else 'N/A'
                    try:
                        vram = str(round(int(parts[1].replace('MiB', '').strip()) / 1024)) + ' GB' if len(parts) > 1 else 'N/A'
                    except Exception:
                        vram = 'N/A'
                    driver = parts[2] if len(parts) > 2 else 'N/A'
                    return gpu, vram, driver
                else:
                    return 'Not detected', 'N/A', 'N/A'
            except Exception:
                return 'N/A', 'N/A', 'N/A'

        def _get_long_paths():
            try:
                r = subprocess.run(
                    ['reg', 'query', r'HKLM\SYSTEM\CurrentControlSet\Control\FileSystem', '/v', 'LongPathsEnabled'],
                    capture_output=True, stdin=subprocess.DEVNULL, timeout=5, creationflags=self._NO_WIN
                )
                return '0x1' in r.stdout.decode(errors='replace')
            except Exception:
                return False

        info = {}
        with ThreadPoolExecutor(max_workers=8) as ex:
            f_python     = ex.submit(_get_python)
            f_torch      = ex.submit(_get_torch)
            f_comfyui    = ex.submit(_get_comfyui)
            f_frontend   = ex.submit(_get_frontend)
            f_ram        = ex.submit(_get_ram)
            f_pagefile   = ex.submit(_get_pagefile)
            f_gpu        = ex.submit(_get_gpu)
            f_long_paths = ex.submit(_get_long_paths)

            info['python']                    = f_python.result()
            info['torch'], info['cuda']       = f_torch.result()
            info['comfyui']                   = f_comfyui.result()
            info['frontend']                  = f_frontend.result()
            info['ram']                       = f_ram.result()
            info['pagefile']                  = f_pagefile.result()
            info['gpu'], info['vram'], info['driver'] = f_gpu.result()
            info['long_paths']                = f_long_paths.result()

        return info

    def get_cache_sizes(self):
        import shutil

        def _dir_size_mb(path):
            total = 0
            try:
                for dirpath, _dirnames, filenames in os.walk(path):
                    for f in filenames:
                        try:
                            total += os.path.getsize(os.path.join(dirpath, f))
                        except Exception:
                            pass
            except Exception:
                pass
            return total

        def _fmt(b):
            if b <= 0:
                return '0 MB'
            mb = b / (1024 * 1024)
            if mb >= 1024:
                return f'{mb/1024:.2f} GB'
            if mb < 0.1:
                return '0 MB'
            return f'{mb:.1f} MB'

        pip_size = 0
        try:
            r = subprocess.run(
                [self.PY_EXE, '-m', 'pip', 'cache', 'dir'],
                capture_output=True, stdin=subprocess.DEVNULL, timeout=10, creationflags=self._NO_WIN
            )
            pip_dir = r.stdout.decode(errors='replace').strip()
            if pip_dir and os.path.isdir(pip_dir):
                pip_size = _dir_size_mb(pip_dir)
        except Exception:
            pass

        uv_size = 0
        try:
            uv_exe = os.path.join(ROOT_DIR, 'python_embeded', 'Scripts', 'uv.exe')
            if not os.path.exists(uv_exe):
                import shutil as _sh
                uv_exe = _sh.which('uv') or ''
            if uv_exe:
                r = subprocess.run(
                    [uv_exe, 'cache', 'dir'],
                    capture_output=True, stdin=subprocess.DEVNULL, timeout=10, creationflags=self._NO_WIN
                )
                uv_dir = r.stdout.decode(errors='replace').strip()
                if uv_dir and os.path.isdir(uv_dir):
                    uv_size = _dir_size_mb(uv_dir)
        except Exception:
            pass

        return {'pip': _fmt(pip_size), 'uv': _fmt(uv_size)}

    def clear_cache(self, cache_type):
        import shutil as _sh

        def _fmt(b):
            if b <= 0:
                return '0 MB'
            mb = b / (1024 * 1024)
            if mb >= 1024:
                return f'{mb/1024:.2f} GB'
            if mb < 0.1:
                return '0 MB'
            return f'{mb:.1f} MB'

        if cache_type == 'pip':
            try:
                subprocess.run(
                    [self.PY_EXE, '-m', 'pip', 'cache', 'purge'],
                    capture_output=True, stdin=subprocess.DEVNULL, timeout=30, creationflags=self._NO_WIN
                )
            except Exception:
                pass
            size = 0
            try:
                r = subprocess.run(
                    [self.PY_EXE, '-m', 'pip', 'cache', 'dir'],
                    capture_output=True, stdin=subprocess.DEVNULL, timeout=10, creationflags=self._NO_WIN
                )
                pip_dir = r.stdout.decode(errors='replace').strip()
                if pip_dir and os.path.isdir(pip_dir):
                    for dp, _d, fs in os.walk(pip_dir):
                        for f in fs:
                            try:
                                size += os.path.getsize(os.path.join(dp, f))
                            except Exception:
                                pass
            except Exception:
                pass
            return {'size': _fmt(size)}

        if cache_type == 'uv':
            uv_exe = os.path.join(ROOT_DIR, 'python_embeded', 'Scripts', 'uv.exe')
            if not os.path.exists(uv_exe):
                uv_exe = _sh.which('uv') or ''
            if uv_exe:
                try:
                    subprocess.run(
                        [uv_exe, 'cache', 'clean', '--all'],
                        capture_output=True, stdin=subprocess.DEVNULL, timeout=30, creationflags=self._NO_WIN
                    )
                except Exception:
                    pass
            size = 0
            try:
                if uv_exe:
                    r = subprocess.run(
                        [uv_exe, 'cache', 'dir'],
                        capture_output=True, stdin=subprocess.DEVNULL, timeout=10, creationflags=self._NO_WIN
                    )
                    uv_dir = r.stdout.decode(errors='replace').strip()
                    if uv_dir and os.path.isdir(uv_dir):
                        for dp, _d, fs in os.walk(uv_dir):
                            for f in fs:
                                try:
                                    size += os.path.getsize(os.path.join(dp, f))
                                except Exception:
                                    pass
            except Exception:
                pass
            return {'size': _fmt(size)}

        return {'size': None}

    def check_output_folder(self):
        path = self._resolve_output_dir()
        return path or ""

    def get_frontend_versions(self):
        import urllib.request as _ur, json as _json
        current = None
        try:
            import importlib.metadata as _im
            for _pkg in ('comfyui_frontend_package', 'comfyui-frontend-package'):
                try:
                    ver = _im.version(_pkg)
                    if ver and ver != '0.1.0':
                        current = ver
                        break
                except Exception:
                    continue
        except Exception:
            pass
        if not current:
            try:
                site = os.path.join(ROOT_DIR, 'python_embeded', 'Lib', 'site-packages')
                matches = sorted(glob.glob(
                    os.path.join(site, 'comfyui_frontend_package-*.dist-info', 'METADATA')
                ), reverse=True)
                for meta_path in matches:
                    with open(meta_path, 'r', encoding='utf-8', errors='replace') as _f:
                        for line in _f:
                            if line.startswith('Version:'):
                                ver = line.split(':', 1)[1].strip()
                                if ver and ver != '0.1.0':
                                    current = ver
                                break
                    if current:
                        break
            except Exception:
                pass
        try:
            with _ur.urlopen('https://pypi.org/pypi/comfyui-frontend-package/json', timeout=8) as r:
                data = _json.loads(r.read())
            all_versions = sorted(
                data.get('releases', {}).keys(),
                key=lambda v: [int(x) for x in v.replace('.post', '.').split('.') if x.isdigit()],
                reverse=True
            )
            versions = all_versions[:100]
            if current and current not in versions:
                versions.append(current)
                versions.sort(key=lambda v: [int(x) for x in v.replace('.post', '.').split('.') if x.isdigit()], reverse=True)
        except Exception:
            versions = [current] if current else []
        is_nightly = self.get_frontend_is_nightly()
        return {'current': current, 'versions': versions, 'isNightly': bool(is_nightly)}

    def get_frontend_is_nightly(self):
        import glob as _glob, re as _re

        site_pkgs = os.path.join(ROOT_DIR, 'python_embeded', 'Lib', 'site-packages')
        pkg_dir   = os.path.join(site_pkgs, 'comfyui_frontend_package')
        if not os.path.isdir(pkg_dir):
            candidates = _glob.glob(os.path.join(site_pkgs, 'comfyui_frontend_package*'))
            pkg_dir = next((c for c in candidates
                            if os.path.isdir(c) and 'dist-info' not in c), None)
        if not pkg_dir:
            return None

        assets_dir = os.path.join(pkg_dir, 'static', 'assets')
        if not os.path.isdir(assets_dir):
            return None

        patterns = [
            re.compile(r'__IS_NIGHTLY__\s*[=:]\s*(true|false)', re.IGNORECASE),
            re.compile(r'isNightly\s*=\s*(true|false)',           re.IGNORECASE),
        ]

        js_files = sorted(
            _glob.glob(os.path.join(assets_dir, 'index-*.js')),
            key=os.path.getsize, reverse=True
        )
        if not js_files:
            js_files = _glob.glob(os.path.join(assets_dir, '*.js'))

        for js_path in js_files[:3]:
            try:
                with open(js_path, 'r', encoding='utf-8', errors='replace') as f:
                    chunk_size = 256 * 1024
                    prev_tail  = ''
                    while True:
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        search_text = prev_tail + chunk
                        for pat in patterns:
                            m = pat.search(search_text)
                            if m:
                                return m.group(1).lower() == 'true'
                        prev_tail = chunk[-200:]
            except Exception:
                continue

        return None

    def get_comfyui_required_frontend(self, tag):
        import re as _re, urllib.request as _ur, base64 as _b64
        if not tag or tag == 'NIGHTLY':
            return None

        def _parse_fe_version(line):
            m = _re.search(r'==\s*([^\s,;#]+)', line)
            return m.group(1).strip() if m else None

        def _find_in_lines(lines):
            for line in lines:
                line = line.strip()
                if line.lower().startswith('comfyui-frontend-package'):
                    return _parse_fe_version(line)
            return None

        try:
            r = subprocess.run(
                ['git', 'show', f'tags/{tag}:requirements.txt'],
                cwd=self.COMFY_DIR, capture_output=True, timeout=5,
                creationflags=self._NO_WIN
            )
            if r.returncode == 0:
                result = _find_in_lines(r.stdout.decode(errors='replace').splitlines())
                if result is not None:
                    return result
                return None
        except Exception:
            pass

        try:
            url = (f'https://raw.githubusercontent.com/comfyanonymous/ComfyUI'
                   f'/{tag}/requirements.txt')
            req = _ur.Request(url, headers={'User-Agent': 'ComfyUI-EZi'})
            with _ur.urlopen(req, timeout=8) as resp:
                text = resp.read().decode('utf-8', errors='replace')
            result = _find_in_lines(text.splitlines())
            if result is not None:
                return result
            return None
        except Exception:
            pass

        try:
            current_tag = None
            r = subprocess.run(
                ['git', 'describe', '--tags', '--exact-match', 'HEAD'],
                cwd=self.COMFY_DIR, capture_output=True, timeout=3,
                creationflags=self._NO_WIN
            )
            if r.returncode == 0:
                current_tag = r.stdout.strip().decode(errors='replace')
            if current_tag and current_tag == tag:
                req_path = os.path.join(self.COMFY_DIR, 'requirements.txt')
                if os.path.exists(req_path):
                    with open(req_path, 'r', encoding='utf-8', errors='replace') as f:
                        return _find_in_lines(f)
        except Exception:
            pass

        return None

    def get_comfyui_versions(self):
        import urllib.request as _ur, json as _json

        def _ver_key(tag):
            t = tag.lstrip('v')
            parts = []
            for x in t.replace('-', '.').split('.'):
                try: parts.append(int(x))
                except ValueError: parts.append(0)
            return parts

        current = None
        try:
            r = subprocess.run(
                ['git', 'describe', '--tags', '--exact-match', 'HEAD'],
                cwd=self.COMFY_DIR, capture_output=True, timeout=5, creationflags=self._NO_WIN
            )
            if r.returncode == 0:
                current = r.stdout.strip().decode(errors='replace')
        except Exception:
            pass

        local_tags = []
        try:
            r = subprocess.run(
                ['git', 'tag', '--sort=-version:refname'],
                cwd=self.COMFY_DIR, capture_output=True, timeout=5, creationflags=self._NO_WIN
            )
            local_tags = [t.strip() for t in r.stdout.decode(errors='replace').strip().splitlines() if t.strip()]
        except Exception:
            pass

        remote_tags = []
        for page in (1, 2):
            try:
                req = _ur.Request(
                    f'https://api.github.com/repos/comfyanonymous/ComfyUI/tags?per_page=100&page={page}',
                    headers={'User-Agent': 'ComfyUI-EZi'}
                )
                with _ur.urlopen(req, timeout=8) as resp:
                    data = _json.loads(resp.read())
                batch = [t['name'] for t in data if t.get('name')]
                remote_tags.extend(batch)
                if len(batch) < 100:
                    break
            except Exception:
                break

        all_tags = list({t for t in (local_tags + remote_tags) if re.match(r'^v?\d+\.\d+', t)})
        all_tags.sort(key=_ver_key, reverse=True)
        all_tags = all_tags[:20]
        if current and current not in all_tags:
            all_tags.insert(0, current)
            all_tags = all_tags[:20]
        if not current:
            all_tags.insert(0, 'NIGHTLY')
            current = 'NIGHTLY'

        stable_version = None
        try:
            req = _ur.Request(
                'https://api.github.com/repos/comfyanonymous/ComfyUI/releases/latest',
                headers={'User-Agent': 'ComfyUI-EZi'}
            )
            with _ur.urlopen(req, timeout=8) as resp:
                rel_data = _json.loads(resp.read())
            stable_version = rel_data.get('tag_name') or None
            if stable_version:
                try:
                    _cached_data = {}
                    if os.path.exists(SETTINGS_PATH):
                        with open(SETTINGS_PATH, 'r', encoding='utf-8') as _sf:
                            _cached_data = _json.loads(_sf.read())
                    _cached_data['cached_comfy_stable_version'] = stable_version
                    _tmp = SETTINGS_PATH + '.tmp'
                    with open(_tmp, 'w', encoding='utf-8') as _sf:
                        _json.dump(_cached_data, _sf, indent=2, ensure_ascii=False)
                    os.replace(_tmp, SETTINGS_PATH)
                except Exception:
                    pass
        except Exception:
            try:
                if os.path.exists(SETTINGS_PATH):
                    with open(SETTINGS_PATH, 'r', encoding='utf-8') as _sf:
                        _cached_data = _json.loads(_sf.read())
                    stable_version = _cached_data.get('cached_comfy_stable_version') or None
            except Exception:
                pass

        return {'current': current, 'versions': all_tags, 'stableVersion': stable_version}

    def set_comfyui_version(self, tag):
        threading.Thread(target=self._do_set_comfyui_version, args=(tag,), daemon=True).start()

    def _do_set_comfyui_version(self, tag):
        self._safe_eval("switchToConsole('Switching...')")
        self._println(f"\033[93m=== Switching ComfyUI to {tag} ===\033[0m")
        self._kill_running_proc()
        try:
            self._println("\033[93mFetching tags...\033[0m")
            subprocess.run(['git', 'fetch', '--tags', '--quiet'],
                           cwd=self.COMFY_DIR, capture_output=True, timeout=30, creationflags=self._NO_WIN)
            r = subprocess.run(['git', 'checkout', f'tags/{tag}'],
                               cwd=self.COMFY_DIR, capture_output=True, timeout=15, creationflags=self._NO_WIN)
            out = (r.stdout + r.stderr).decode(errors='replace').strip()
            if out:
                self._println(out)
            if r.returncode == 0:
                self._println(f"\033[92m=== Switched to {tag}. Restarting ComfyUI... ===\033[0m")
                self._safe_eval("switchToConsole()")
                self._updating = False
                self._restart_comfy()
            else:
                self._println(f"\033[91m=== Checkout failed (exit {r.returncode}) ===\033[0m")
        except Exception as e:
            self._println(f"\033[91mError: {e}\033[0m")

    def set_comfyui_version_then_frontend(self, tag, fe_version):
        threading.Thread(target=self._do_set_comfyui_version_then_frontend, args=(tag, fe_version), daemon=True).start()

    def _do_set_comfyui_version_then_frontend(self, tag, fe_version):
        self._safe_eval("switchToConsole('Switching...')")
        self._println(f"\033[93m=== Switching ComfyUI to {tag} + frontend {fe_version} ===\033[0m")
        self._kill_running_proc()
        try:
            self._println("\033[93mFetching tags...\033[0m")
            subprocess.run(['git', 'fetch', '--tags', '--quiet'],
                           cwd=self.COMFY_DIR, capture_output=True, timeout=30, creationflags=self._NO_WIN)
            r = subprocess.run(['git', 'checkout', f'tags/{tag}'],
                               cwd=self.COMFY_DIR, capture_output=True, timeout=15, creationflags=self._NO_WIN)
            out = (r.stdout + r.stderr).decode(errors='replace').strip()
            if out:
                self._println(out)
            if r.returncode != 0:
                self._println(f"\033[91m=== Checkout failed (exit {r.returncode}) ===\033[0m")
                return
            self._println(f"\033[92m=== Switched to {tag} ===\033[0m")
            if not fe_version:
                req_path = os.path.join(self.COMFY_DIR, 'requirements.txt')
                try:
                    with open(req_path, 'r', encoding='utf-8') as _f:
                        for _line in _f:
                            _line = _line.strip()
                            if _line.lower().startswith('comfyui-frontend-package'):
                                import re as _re
                                _m = _re.search(r'==\s*([^\s]+)', _line)
                                if _m:
                                    fe_version = _m.group(1)
                                break
                except Exception:
                    pass
            if fe_version:
                if not self._pip_install_frontend(fe_version):
                    self._println(f"\033[91m=== Frontend install failed ===\033[0m")
                    return
                self._println(f"\033[92m=== Installed frontend {fe_version}. Restarting ComfyUI... ===\033[0m")
            else:
                self._println(f"\033[93m=== No matching frontend version found, skipping. Restarting ComfyUI... ===\033[0m")
            self._safe_eval("switchToConsole()")
            self._updating = False
            self._restart_comfy()
        except Exception as e:
            self._println(f"\033[91mError: {e}\033[0m")

    def _pip_install_frontend(self, version):
        self._println(f"\033[93m=== Installing comfyui-frontend-package=={version} ===\033[0m")
        proc = subprocess.Popen(
            [self.PY_EXE, '-m', 'pip', 'install', f'comfyui-frontend-package=={version}',
             '--no-warn-script-location'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=ROOT_DIR, creationflags=self._NO_WIN
        )
        for line in proc.stdout:
            self._print(line.decode('utf-8', errors='replace'))
        proc.wait()
        return proc.returncode == 0

    def set_frontend_version(self, version):
        threading.Thread(target=self._do_set_frontend_version, args=(version,), daemon=True).start()

    def _do_set_frontend_version(self, version):
        self._safe_eval("switchToConsole('Installing...')")
        try:
            if self._pip_install_frontend(version):
                self._println(f"\033[92m=== Installed. Restarting ComfyUI... ===\033[0m")
                self._kill_running_proc()
                time.sleep(1)
                self._safe_eval("switchToConsole()")
                self._updating = False
                self._restart_comfy()
            else:
                self._println(f"\033[91m=== Installation failed ===\033[0m")
        except Exception as e:
            self._println(f"\033[91mError: {e}\033[0m")

    def run_bat(self, rel_path):
        if self._updating:
            return
        rel_clean = rel_path.lstrip('./\\').replace('\\\\', '\\')
        bat = os.path.normpath(os.path.join(ROOT_DIR, rel_clean))
        if not os.path.exists(bat):
            self._safe_eval(f"show_update_missing({json.dumps(os.path.dirname(bat))})")
            return
        threading.Thread(target=self._do_run_bat, args=(bat,), daemon=True).start()

    def _do_run_bat(self, bat, status_label=None, hide_update_notice=False):
        name = os.path.basename(bat)
        label = status_label or f'Running {name}...'
        self._updating = True
        self._safe_eval(f"switchToConsole({json.dumps(label)})")
        self._safe_eval("document.getElementById('update-notice').style.display='none';")
        self._println(f"\033[93m=== Stopping ComfyUI ===\033[0m")
        self._kill_running_proc()
        self._println(f"\033[93m=== Running {name} ===\033[0m")
        try:
            proc = subprocess.Popen(
                ['cmd', '/c', 'chcp', '65001', '>', 'nul', '&&', bat, 'NoPause'],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                cwd=os.path.dirname(bat),
                creationflags=self._NO_WIN,
            )
            buf = bytearray()
            for chunk in iter(lambda: proc.stdout.read(1), b''):
                buf.extend(chunk)
                if chunk in (b'\r', b'\n'):
                    self._print(buf.decode('utf-8', errors='replace'))
                    buf.clear()
            if buf:
                self._print(buf.decode('utf-8', errors='replace'))
            proc.wait()
        except Exception as e:
            self._println(f"\033[91mError running {name}: {e}\033[0m")

        self._println(f"\033[92m=== {name} finished. ===\033[0m")

        if hide_update_notice:
            self._safe_eval("document.getElementById('update-notice').style.display='none';")

        is_ezi_update = name.lower() == "update easy-install.bat"

        if is_ezi_update:
            self._println(f"\033[92mRestarting ComfyUI-EZi...\033[0m")
            time.sleep(1)
            self.restart_ezi()
        else:
            self._println(f"\033[92mRestarting ComfyUI...\033[0m")
            time.sleep(1)
            self._safe_eval("switchToConsole()")
            self._updating = False
            self._restart_comfy(check_update=True)

    def open_output_folder(self):
        path = self._resolve_output_dir()
        if not path:
            return
        try:
            custom_browser = self._settings.get("custom_file_browser", "").strip()
            if custom_browser and os.path.isfile(custom_browser):
                subprocess.Popen([custom_browser, path])
            else:
                subprocess.Popen(['explorer', path])
        except Exception as e:
            self._println(f"[Output] Could not open folder: {e}\n")

    def _open_folder_path(self, path):
        if not path or not os.path.isdir(path):
            return False
        try:
            custom_browser = self._settings.get("custom_file_browser", "").strip()
            if custom_browser and os.path.isfile(custom_browser):
                subprocess.Popen([custom_browser, path])
            else:
                subprocess.Popen(['explorer', path])
            return True
        except Exception as e:
            self._println(f"[Folder] Could not open folder: {e}\n")
            return False

    def _resolve_input_dir(self):
        try:
            if os.path.exists(BAT_FILE):
                with open(BAT_FILE, 'r', encoding='utf-8', errors='replace') as f:
                    bat_content = f.read()
                m_env = re.search(r'(?i)set\s+"?COMFY_INPUT_DIR=([^"\n]+)"?', bat_content)
                if m_env:
                    d = m_env.group(1).strip().strip('"')
                    if not os.path.isabs(d):
                        d = os.path.normpath(os.path.join(ROOT_DIR, d))
                    return d if os.path.isdir(d) else None
                comfy_line = _find_bat_comfy_line(bat_content)
                if comfy_line:
                    m = re.search(r'python_embeded[/\\]python\.exe["\']?\s+(.*)',
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

    def _resolve_workflows_dir(self):
        user_dir = _get_comfy_user_dir()
        d = os.path.join(user_dir, 'workflows')
        return d if os.path.isdir(d) else None

    def _resolve_models_dir(self):
        yaml_path = os.path.normpath(os.path.join(ROOT_DIR, 'ComfyUI', 'extra_model_paths.yaml'))
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
                            parent = os.path.normpath(os.path.join(base_path, first_component))

                        if os.path.isdir(parent):
                            parent_votes[parent] = parent_votes.get(parent, 0) + 1

                    if parent_votes:
                        best = max(parent_votes, key=lambda p: parent_votes[p])
                        return best

            except Exception:
                pass
        d = os.path.normpath(os.path.join(ROOT_DIR, 'ComfyUI', 'models'))
        return d if os.path.isdir(d) else None

    def _resolve_custom_nodes_dir(self):
        d = os.path.normpath(os.path.join(ROOT_DIR, 'ComfyUI', 'custom_nodes'))
        return d if os.path.isdir(d) else None

    def open_sub_folder(self, folder_type):
        if folder_type == 'input':
            path = self._resolve_input_dir()
        elif folder_type == 'workflows':
            path = self._resolve_workflows_dir()
        elif folder_type == 'models':
            path = self._resolve_models_dir()
        elif folder_type == 'custom_nodes':
            path = self._resolve_custom_nodes_dir()
        else:
            return
        if not self._open_folder_path(path):
            self._println(f"[Folder] '{folder_type}' folder not found.\n")

    def open_nodes_cmd(self):
        path = self._resolve_custom_nodes_dir()
        if not path:
            return
        try:
            subprocess.Popen(["cmd.exe", "/k"], cwd=path)
        except Exception as e:
            self._println(f"[Custom Nodes] Could not open command prompt: {e}\n")

    def browse_for_exe(self):
        try:
            result = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=('Executable files (*.exe)', 'All files (*.*)')
            )
            if result and result[0]:
                return result[0]
        except Exception:
            pass
        return None

    def browse_for_folder(self):
        try:
            result = self._window.create_file_dialog(
                webview.FOLDER_DIALOG,
                allow_multiple=False
            )
            if result and result[0]:
                return result[0]
        except Exception:
            pass
        return None

    def browse_for_image(self):
        try:
            result = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=('Image files (*.png;*.jpg;*.jpeg;*.webp)', 'All files (*.*)')
            )
            if result and result[0]:
                return result[0]
        except Exception:
            pass
        return None

    def apply_console_bg(self):
        custom_bg  = self._settings.get("console_bg_image", "").strip()
        bg_fit     = self._settings.get("console_bg_fit", "fit")
        opacity    = float(self._settings.get("console_bg_opacity", 0.12))

        _ico_css, ico_w, ico_h = _load_ico_as_base64()

        if custom_bg and os.path.isfile(custom_bg):
            ext  = os.path.splitext(custom_bg)[1].lower().lstrip(".")
            mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "webp": "image/webp"}.get(ext, "image/png")
            try:
                with open(custom_bg, "rb") as _f:
                    b64 = base64.b64encode(_f.read()).decode()
                css_url = f'url("data:{mime};base64,{b64}")'
            except Exception:
                css_url = ""
            fit_map = {
                "fit":     ("contain",   "no-repeat"),
                "stretch": ("100% 100%", "no-repeat"),
                "tile":    ("auto",      "repeat"),
                "center":  ("auto",      "no-repeat"),
            }
            bg_size, bg_repeat = fit_map.get(bg_fit, ("contain", "no-repeat"))
            js = f"""
(function(){{
    var el = document.getElementById('ico-bg');
    if (!el) return;
    el.style.backgroundImage    = {json.dumps(css_url)};
    el.style.backgroundSize     = {json.dumps(bg_size)};
    el.style.backgroundRepeat   = {json.dumps(bg_repeat)};
    el.style.backgroundPosition = 'center';
    el.style.opacity   = {opacity};
    el.style.inset     = '0';
    el.style.width     = 'auto';
    el.style.height    = 'auto';
    el.style.transform = 'none';
}})();
"""
        else:
            css_url = _ico_css
            bg_size = f"{ico_w}px {ico_h}px" if _ico_css else "256px 256px"

            js = (
                "(function(){{"
                "var el = document.getElementById('ico-bg');"
                "if (!el) return;"
                f"el.style.backgroundImage    = {json.dumps(css_url)};"
                f"el.style.backgroundSize     = {json.dumps(bg_size)};"
                "el.style.backgroundRepeat   = 'no-repeat';"
                "el.style.backgroundPosition = 'center';"
                f"el.style.opacity            = '{opacity}';"
                "el.style.inset              = 'unset';"
                f"el.style.width              = '{ico_w}px';"
                f"el.style.height             = '{ico_h}px';"
                "el.style.top                = '50%';"
                "el.style.left               = '50%';"
                "el.style.transform          = 'translate(-50%, -50%)';"
                "}})()"
            )
        self._safe_eval(js)

    def get_custom_paths(self):
        paths = {'input': '', 'output': '', 'user': ''}
        try:
            if not os.path.exists(BAT_FILE):
                return json.dumps(paths)
            with open(BAT_FILE, 'r', encoding='utf-8', errors='replace') as f:
                bat_content = f.read()
            comfy_line = _find_bat_comfy_line(bat_content)
            if not comfy_line:
                return json.dumps(paths)
            m = re.search(r'python_embeded[/\\]python\.exe["\']?\s+(.*)',
                          comfy_line, re.IGNORECASE)
            if not m:
                return json.dumps(paths)
            tokens = shlex.split(m.group(1).strip(), posix=False)
            param_map = {
                '--input-directory':  'input',
                '--output-directory': 'output',
                '--user-directory':   'user',
            }
            i = 0
            while i < len(tokens):
                tok = tokens[i]
                if tok in param_map and i + 1 < len(tokens):
                    paths[param_map[tok]] = tokens[i + 1].strip('"\'')
                    i += 2
                else:
                    i += 1
        except Exception:
            pass
        return json.dumps(paths)

    def set_custom_paths(self, input_dir, output_dir, user_dir):
        bat_names = [
            'Start ComfyUI.bat',
            'Start ComfyUI SageAttention.bat',
            'Start ComfyUI FlashAttention.bat',
        ]
        new_vals = {
            '--input-directory':  input_dir.strip().strip('"'),
            '--output-directory': output_dir.strip().strip('"'),
            '--user-directory':   user_dir.strip().strip('"'),
        }

        for bat_name in bat_names:
            bat_path = os.path.join(ROOT_DIR, bat_name)
            if not os.path.exists(bat_path):
                continue
            try:
                with open(bat_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()

                lines = content.splitlines(keepends=True)

                i = 0
                start_idx = None
                end_idx = None
                logical_line = None

                while i < len(lines):
                    stripped = lines[i].rstrip('\r\n')
                    accumulated = stripped
                    j = i
                    while accumulated.rstrip().endswith('^') and j + 1 < len(lines):
                        accumulated = accumulated.rstrip()[:-1] + ' ' + lines[j + 1].lstrip().rstrip('\r\n')
                        j += 1

                    acc_s = accumulated.strip()
                    if (acc_s and
                            not acc_s.startswith('::') and
                            not re.match(r'(?i)^rem(\s|$)', acc_s) and
                            re.search(r'python_embeded[/\\]python\.exe', acc_s, re.IGNORECASE) and
                            re.search(r'ComfyUI[/\\]main\.py', acc_s, re.IGNORECASE)):
                        start_idx = i
                        end_idx = j
                        logical_line = acc_s
                        break
                    i += 1

                if logical_line is None or start_idx is None:
                    continue

                m = re.search(r'(.*python_embeded[/\\]python\.exe["\']?)\s+(.*)',
                              logical_line, re.IGNORECASE | re.DOTALL)
                if not m:
                    continue
                py_prefix = m.group(1)
                rest = m.group(2).strip()

                tokens = shlex.split(rest, posix=False)

                script_idx = None
                for idx, tok in enumerate(tokens):
                    if re.search(r'main\.py', tok, re.IGNORECASE):
                        script_idx = idx
                        break

                if script_idx is None:
                    continue

                pre_script = tokens[:script_idx + 1]
                post_script = tokens[script_idx + 1:]

                SINGLE_VAL_PARAMS = {
                    '--input-directory', '--output-directory', '--user-directory',
                    '--port', '--tls-keyfile', '--tls-certfile', '--max-upload-size',
                    '--base-directory', '--temp-directory', '--cuda-device',
                    '--default-device', '--oneapi-device-selector', '--preview-size',
                    '--cache-lru', '--reserve-vram', '--default-hashing-function',
                    '--front-end-version', '--front-end-root', '--comfy-api-base',
                    '--database-url',
                }
                rebuilt = []
                k = 0
                while k < len(post_script):
                    tok = post_script[k]
                    if tok in new_vals:
                        k += 2 if (k + 1 < len(post_script)) else 1
                    elif tok in SINGLE_VAL_PARAMS:
                        rebuilt.append(tok)
                        if k + 1 < len(post_script):
                            rebuilt.append(post_script[k + 1])
                            k += 2
                        else:
                            k += 1
                    else:
                        rebuilt.append(tok)
                        k += 1

                for param, val in new_vals.items():
                    if val:
                        rebuilt.extend([param, f'"{val}"'])

                new_cmd_parts = [py_prefix] + pre_script + rebuilt
                new_line = ' '.join(new_cmd_parts)

                orig_ending = '\r\n' if '\r\n' in lines[start_idx] else '\n'

                new_lines = (
                    lines[:start_idx] +
                    [new_line + orig_ending] +
                    lines[end_idx + 1:]
                )

                with open(bat_path, 'w', encoding='utf-8', newline='') as f:
                    f.write(''.join(new_lines))

            except Exception as e:
                self._println(f"[CustomPaths] Error updating {bat_name}: {e}\n")

        self._println("\n[CustomPaths] Restarting ComfyUI to apply new folder settings...\n")
        self._kill_running_proc()
        self._restart_comfy(check_update=False)

    def open_url(self, url):
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

    def screenshot(self, x, y, w, h):
        threading.Thread(target=self._do_screenshot, args=(x, y, w, h), daemon=True).start()

    def start_recording(self, x, y, w, h, fps=15):
        threading.Thread(target=self._do_start_recording, args=(x, y, w, h, int(fps)), daemon=True).start()

    def stop_recording(self):
        if hasattr(self, '_rec_stop_event') and self._rec_stop_event:
            self._rec_stop_event.set()

    def _capture_frame_gdi(self, hwnd, x, y, w, h):
        import ctypes, ctypes.wintypes as wt
        gdi  = ctypes.windll.gdi32
        user = ctypes.windll.user32
        _vp  = ctypes.c_void_p
        gdi.CreateCompatibleDC.restype       = _vp
        gdi.CreateCompatibleDC.argtypes      = [_vp]
        gdi.CreateCompatibleBitmap.restype   = _vp
        gdi.CreateCompatibleBitmap.argtypes  = [_vp, ctypes.c_int, ctypes.c_int]
        gdi.SelectObject.restype             = _vp
        gdi.SelectObject.argtypes            = [_vp, _vp]
        gdi.DeleteObject.restype             = wt.BOOL
        gdi.DeleteObject.argtypes            = [_vp]
        gdi.DeleteDC.restype                 = wt.BOOL
        gdi.DeleteDC.argtypes                = [_vp]
        gdi.BitBlt.restype                   = wt.BOOL
        gdi.BitBlt.argtypes                  = [_vp, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, _vp, ctypes.c_int, ctypes.c_int, wt.DWORD]
        gdi.GetDIBits.restype                = ctypes.c_int
        gdi.GetDIBits.argtypes               = [_vp, _vp, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.c_void_p, wt.UINT]
        user.GetDC.restype                   = _vp
        user.GetDC.argtypes                  = [_vp]
        user.ReleaseDC.restype               = ctypes.c_int
        user.ReleaseDC.argtypes              = [_vp, _vp]
        user.DrawIconEx.restype              = wt.BOOL
        user.DrawIconEx.argtypes             = [_vp, ctypes.c_int, ctypes.c_int, _vp, ctypes.c_int, ctypes.c_int, wt.UINT, _vp, wt.UINT]
        user.ClientToScreen.restype          = wt.BOOL
        user.ClientToScreen.argtypes         = [_vp, ctypes.c_void_p]
        try:
            prev_ctx = None
            try:
                user.SetThreadDpiAwarenessContext.argtypes = [_vp]
                user.SetThreadDpiAwarenessContext.restype  = _vp
                prev_ctx = user.SetThreadDpiAwarenessContext(_vp(-4))
            except Exception:
                pass

            try:
                dpr = 1.0
                try:
                    user.GetDpiForWindow.argtypes = [_vp]
                    user.GetDpiForWindow.restype  = wt.UINT
                    dpi = user.GetDpiForWindow(_vp(hwnd))
                    if dpi: dpr = dpi / 96.0
                except Exception:
                    pass

                phys_x = max(0, int(round(x * dpr)))
                phys_y = max(0, int(round(y * dpr)))
                cap_w  = max(1, int(round(w * dpr)))
                cap_h  = max(1, int(round(h * dpr)))

                pt = wt.POINT(0, 0)
                user.ClientToScreen(_vp(hwnd), ctypes.byref(pt))
                src_x = pt.x + phys_x
                src_y = pt.y + phys_y

                class CURSORINFO(ctypes.Structure):
                    _fields_ = [("cbSize",wt.DWORD),("flags",wt.DWORD),
                                ("hCursor",_vp),("ptScreenPos",wt.POINT)]
                class ICONINFO(ctypes.Structure):
                    _fields_ = [("fIcon",wt.BOOL),("xHotspot",wt.DWORD),("yHotspot",wt.DWORD),
                                ("hbmMask",_vp),("hbmColor",_vp)]
                ci = CURSORINFO()
                ci.cbSize = ctypes.sizeof(CURSORINFO)
                cursor_ok = bool(user.GetCursorInfo(ctypes.byref(ci))) and ci.flags == 1
                cur_x = cur_y = 0
                if cursor_ok:
                    ii = ICONINFO()
                    if user.GetIconInfo(_vp(ci.hCursor), ctypes.byref(ii)):
                        cur_x = ci.ptScreenPos.x - src_x - int(ii.xHotspot)
                        cur_y = ci.ptScreenPos.y - src_y - int(ii.yHotspot)
                        if ii.hbmColor: gdi.DeleteObject(_vp(ii.hbmColor))
                        if ii.hbmMask:  gdi.DeleteObject(_vp(ii.hbmMask))
                    else:
                        cursor_ok = False

                hdc_screen = user.GetDC(None)
                hdc_mem    = gdi.CreateCompatibleDC(hdc_screen)
                hbm        = gdi.CreateCompatibleBitmap(hdc_screen, cap_w, cap_h)
                old_bm     = gdi.SelectObject(hdc_mem, hbm)

                gdi.BitBlt(hdc_mem, 0, 0, cap_w, cap_h, hdc_screen, src_x, src_y, 0x00CC0020)

                if cursor_ok:
                    try:
                        user.DrawIconEx(hdc_mem, cur_x, cur_y, ci.hCursor, 0, 0, 0, None, 0x0003)
                    except Exception:
                        pass

                class BITMAPINFOHEADER(ctypes.Structure):
                    _fields_ = [("biSize",wt.DWORD),("biWidth",wt.LONG),("biHeight",wt.LONG),
                                ("biPlanes",wt.WORD),("biBitCount",wt.WORD),("biCompression",wt.DWORD),
                                ("biSizeImage",wt.DWORD),("biXPelsPerMeter",wt.LONG),
                                ("biYPelsPerMeter",wt.LONG),("biClrUsed",wt.DWORD),("biClrImportant",wt.DWORD)]

                bih = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER),
                                       biWidth=cap_w, biHeight=-cap_h, biPlanes=1, biBitCount=32,
                                       biCompression=0)
                buf = (ctypes.c_char * (cap_w * cap_h * 4))()
                gdi.GetDIBits(hdc_mem, hbm, 0, cap_h, buf, ctypes.byref(bih), 0)
                gdi.SelectObject(hdc_mem, old_bm)
                gdi.DeleteObject(hbm)
                gdi.DeleteDC(hdc_mem)
                user.ReleaseDC(None, hdc_screen)

                from PIL import Image
                return Image.frombuffer("RGBA", (cap_w, cap_h), buf, "raw", "BGRA", 0, 1).convert("RGB")

            finally:
                if prev_ctx is not None:
                    try: user.SetThreadDpiAwarenessContext(prev_ctx)
                    except Exception: pass

        except Exception as _cap_err:
            self._println(f"[Record] Capture error: {_cap_err}")
            return None

    def _do_start_recording(self, x, y, w, h, fps=15):
        import ctypes, ctypes.wintypes as wt
        FPS = max(1, min(60, int(fps)))
        self._rec_stop_event = threading.Event()

        try:
            from PIL import Image
        except ImportError:
            self._println("[Record] Error: Pillow is not installed.")
            self._safe_eval("stopRecording()")
            return

        hwnd = None
        for _attempt in range(10):
            hwnd = _get_hwnd(self._window) if self._window else None
            if hwnd:
                break
            time.sleep(0.3)
        if not hwnd:
            self._println("[Record] Error: could not find application window handle.")
            self._safe_eval("stopRecording()")
            return

        test_frame = self._capture_frame_gdi(hwnd, x, y, w, h)
        if test_frame is None:
            self._println("[Record] Failed to capture test frame.")
            self._safe_eval("stopRecording()")
            return

        fw, fh = test_frame.size
        fw = max(2, fw if fw % 2 == 0 else fw - 1)
        fh = max(2, fh if fh % 2 == 0 else fh - 1)

        if fw < 16 or fh < 16:
            self._println(f"[Record] Region too small ({fw}x{fh}). Minimum is 16x16 pixels.")
            self._safe_eval("stopRecording()")
            return

        self._safe_eval(f"showRecIndicator({x},{y},{w},{h})")

        import shutil, subprocess as sp
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg:
            for candidate in [
                os.path.join(ROOT_DIR, 'ffmpeg.exe'),
                os.path.join(ROOT_DIR, 'ffmpeg', 'ffmpeg.exe'),
                os.path.join(ROOT_DIR, 'ffmpeg', 'bin', 'ffmpeg.exe'),
                r'C:\ffmpeg\bin\ffmpeg.exe',
                r'C:\ffmpeg\ffmpeg.exe',
            ]:
                if os.path.isfile(candidate):
                    ffmpeg = candidate
                    break

        tmp_file = os.path.join(self._last_save_dir, f'_ezi_rec_tmp_{int(time.time())}.mp4')

        if ffmpeg:
            cmd = [
                ffmpeg, '-y',
                '-f', 'rawvideo',
                '-vcodec', 'rawvideo',
                '-s', f'{fw}x{fh}',
                '-pix_fmt', 'rgb24',
                '-r', str(FPS),
                '-i', 'pipe:0',
                '-an',
                '-vcodec', 'libx264',
                '-preset', 'ultrafast',
                '-crf', '23',
                '-pix_fmt', 'yuv420p',
                tmp_file
            ]
            try:
                proc = sp.Popen(cmd, stdin=sp.PIPE, stdout=sp.DEVNULL, stderr=sp.DEVNULL,
                                creationflags=0x08000000)
            except Exception as e:
                self._println(f"[Record] ffmpeg launch failed: {e}")
                self._safe_eval("stopRecording()")
                return

            self._println(f"[Record] Recording started (ffmpeg, {fw}x{fh} @ {FPS}fps)...")
            interval = 1.0 / FPS
            try:
                while not self._rec_stop_event.is_set():
                    t0 = time.time()
                    frame = self._capture_frame_gdi(hwnd, x, y, w, h)
                    if frame is not None:
                        frame = frame.resize((fw, fh), Image.LANCZOS) if frame.size != (fw, fh) else frame
                        try:
                            proc.stdin.write(frame.tobytes())
                        except BrokenPipeError:
                            break
                    elapsed = time.time() - t0
                    wait = interval - elapsed
                    if wait > 0:
                        self._rec_stop_event.wait(wait)
            finally:
                try:
                    proc.stdin.close()
                    proc.wait(timeout=15)
                except Exception:
                    try: proc.kill()
                    except Exception: pass

        else:
            self._println("[Record] ffmpeg not found - collecting frames (may use more RAM)...")
            frames = []
            interval = 1.0 / FPS
            while not self._rec_stop_event.is_set():
                t0 = time.time()
                frame = self._capture_frame_gdi(hwnd, x, y, w, h)
                if frame is not None:
                    frame = frame.resize((fw, fh), Image.LANCZOS) if frame.size != (fw, fh) else frame
                    frames.append(frame.tobytes())
                elapsed = time.time() - t0
                wait = interval - elapsed
                if wait > 0:
                    self._rec_stop_event.wait(wait)

            if not frames:
                self._println("[Record] No frames captured.")
                self._safe_eval("stopRecording()")
                return

            written = False
            try:
                import cv2
                import numpy as np
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                out = cv2.VideoWriter(tmp_file, fourcc, FPS, (fw, fh))
                for raw in frames:
                    arr = np.frombuffer(raw, dtype=np.uint8).reshape((fh, fw, 3))
                    out.write(cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))
                out.release()
                written = True
                self._println("[Record] Encoded with OpenCV.")
            except ImportError:
                pass
            except Exception as e:
                self._println(f"[Record] OpenCV error: {e}")

            if not written:
                try:
                    tmp_file = tmp_file.replace('.mp4', '.avi')
                    self._write_mjpeg_avi(tmp_file, frames, fw, fh, FPS)
                    written = True
                    self._println("[Record] Encoded as MJPEG AVI (ffmpeg not found).")
                except Exception as e:
                    self._println(f"[Record] AVI write error: {e}")

            if not written:
                self._println("[Record] Recording failed - install ffmpeg or opencv-python.")
                self._safe_eval("stopRecording()")
                return

        self._println(f"[Record] Recording stopped. Saving...")

        default_name = os.path.basename(tmp_file).replace('_ezi_rec_tmp_', 'ComfyUI-EZi-recording-')
        if not default_name.endswith('.mp4') and not default_name.endswith('.avi'):
            default_name = f"ComfyUI-EZi-recording-{time.strftime('%Y%m%d_%H%M%S')}.mp4"
        else:
            ext = '.mp4' if tmp_file.endswith('.mp4') else '.avi'
            default_name = f"ComfyUI-EZi-recording-{time.strftime('%Y%m%d_%H%M%S')}{ext}"

        save_path = None
        if self._window and os.path.exists(tmp_file):
            try:
                ft = ("MP4 Video (*.mp4)", "All Files (*.*)") if tmp_file.endswith('.mp4') else ("AVI Video (*.avi)", "All Files (*.*)",)
                result = self._window.create_file_dialog(
                    SAVE_DIALOG_TYPE,
                    directory=self._last_save_dir,
                    save_filename=default_name,
                    file_types=ft
                )
                if result:
                    save_path = result[0] if isinstance(result, (list, tuple)) else result
                    self._last_save_dir = os.path.dirname(save_path)
                    self._settings["last_save_dir"] = self._last_save_dir
                    _save_settings(self._settings)
            except Exception:
                pass

        if save_path and os.path.exists(tmp_file):
            import shutil as _sh
            try:
                _sh.move(tmp_file, save_path)
                self._println(f"[Record] Saved: {save_path}")
            except Exception as e:
                self._println(f"[Record] Save error: {e}")
        elif os.path.exists(tmp_file):
            try: os.remove(tmp_file)
            except Exception: pass

    def _write_mjpeg_avi(self, path, frames_raw, w, h, fps):
        import io, struct
        from PIL import Image

        jpegs = []
        for raw in frames_raw:
            img = Image.frombytes('RGB', (w, h), raw)
            buf = io.BytesIO()
            img.save(buf, 'JPEG', quality=85)
            jpegs.append(buf.getvalue())

        def dw(n):  return struct.pack('<I', n)
        def dd(n):  return struct.pack('<i', n)
        def dw2(n): return struct.pack('<H', n)

        n = len(jpegs)
        us_per_frame = int(1_000_000 / fps)

        movi_data = b''
        idx1_data = b''
        offset = 4
        for jpg in jpegs:
            padded = jpg + (b'\x00' if len(jpg) % 2 else b'')
            chunk = b'00dc' + dw(len(jpg)) + padded
            idx1_data += b'00dc' + dw(0x10) + dw(offset) + dw(len(jpg))
            offset += len(chunk)
            movi_data += chunk

        movi_size = len(movi_data) + 4
        idx1_size = len(idx1_data)

        strh = (b'vids' + b'MJPG' + dw(0)*4 + dw(1) + dw(fps) +
                dw(0) + dw(n) + dw(0) + dw(int(w*h*3)) +
                dw2(w) + dw2(h))
        strf = (dw(40) + dd(w) + dd(h) + dw2(1) + dw2(24) +
                b'MJPG' + dw(w*h*3) + dd(0)*2 + dw(0)*2)

        strl = (b'LIST' + dw(4 + 8 + len(strh) + 8 + len(strf)) + b'strl' +
                b'strh' + dw(len(strh)) + strh +
                b'strf' + dw(len(strf)) + strf)

        avih = (dw(us_per_frame) + dw(int(w*h*3*fps)) + dw(0) + dw(0x10) +
                dw(n) + dw(0) + dw(1) + dw(0) + dw(w) + dw(h))
        hdrl = b'LIST' + dw(4 + 8 + len(avih) + len(strl)) + b'hdrl' + b'avih' + dw(len(avih)) + avih + strl

        movi_chunk = b'LIST' + dw(movi_size) + b'movi' + movi_data
        idx1_chunk = b'idx1' + dw(idx1_size) + idx1_data

        riff_data = hdrl + movi_chunk + idx1_chunk
        with open(path, 'wb') as f:
            f.write(b'RIFF' + dw(len(riff_data) + 4) + b'AVI ' + riff_data)

    def _do_screenshot(self, x, y, w, h):
        time.sleep(0.15)
        try:
            try:
                from PIL import Image
            except ImportError:
                self._println("[Screenshot] Error: Pillow is not installed.\n"
                            "Run: python_embeded\\python.exe -m pip install Pillow")
                return

            import ctypes, ctypes.wintypes as wt
            gdi  = ctypes.windll.gdi32
            user = ctypes.windll.user32

            _vp = ctypes.c_void_p
            user.GetDC.argtypes    = [_vp];           user.GetDC.restype    = _vp
            user.ReleaseDC.argtypes = [_vp, _vp]
            user.ClientToScreen.argtypes = [_vp, ctypes.POINTER(wt.POINT)]
            user.GetClientRect.argtypes  = [_vp, ctypes.c_void_p]
            user.GetDpiForWindow.argtypes = [_vp]; user.GetDpiForWindow.restype = wt.UINT
            gdi.CreateCompatibleDC.argtypes     = [_vp]; gdi.CreateCompatibleDC.restype     = _vp
            gdi.CreateCompatibleBitmap.argtypes = [_vp, ctypes.c_int, ctypes.c_int]
            gdi.CreateCompatibleBitmap.restype  = _vp
            gdi.SelectObject.argtypes = [_vp, _vp]; gdi.SelectObject.restype = _vp
            gdi.BitBlt.argtypes = [_vp,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,
                                   _vp,ctypes.c_int,ctypes.c_int,wt.DWORD]
            gdi.BitBlt.restype = wt.BOOL
            gdi.GetDIBits.argtypes = [_vp,_vp,wt.UINT,wt.UINT,ctypes.c_void_p,ctypes.c_void_p,wt.UINT]
            gdi.DeleteObject.argtypes = [_vp]
            gdi.DeleteDC.argtypes     = [_vp]

            hwnd = _get_hwnd(self._window) if self._window else None
            if not hwnd:
                self._print("[Screenshot] Error: No window handle found.")
                return

            prev_dpi_ctx = None
            try:
                user.SetThreadDpiAwarenessContext.argtypes = [_vp]
                user.SetThreadDpiAwarenessContext.restype  = _vp
                prev_dpi_ctx = user.SetThreadDpiAwarenessContext(_vp(-4))
            except Exception:
                pass

            try:
                dpr = 1.0
                try:
                    dpi = user.GetDpiForWindow(hwnd)
                    dpr = dpi / 96.0
                except Exception:
                    dpr = 1.0

                class RECT(ctypes.Structure):
                    _fields_ = [("left",ctypes.c_long),("top",ctypes.c_long),
                                 ("right",ctypes.c_long),("bottom",ctypes.c_long)]
                rc = RECT()
                user.GetClientRect(hwnd, ctypes.byref(rc))
                cap_w = max(1, rc.right)
                cap_h = max(1, rc.bottom)

                pt = wt.POINT(0, 0)
                user.ClientToScreen(hwnd, ctypes.byref(pt))

                hdc_screen = user.GetDC(_vp(0))
                hdc_mem    = gdi.CreateCompatibleDC(hdc_screen)
                hbm        = gdi.CreateCompatibleBitmap(hdc_screen, cap_w, cap_h)
                old_bm     = gdi.SelectObject(hdc_mem, hbm)

                gdi.BitBlt(hdc_mem, 0, 0, cap_w, cap_h,
                           hdc_screen, pt.x, pt.y, 0x00CC0020)

                class BITMAPINFOHEADER(ctypes.Structure):
                    _fields_ = [("biSize",wt.DWORD),("biWidth",wt.LONG),("biHeight",wt.LONG),
                                ("biPlanes",wt.WORD),("biBitCount",wt.WORD),("biCompression",wt.DWORD),
                                ("biSizeImage",wt.DWORD),("biXPelsPerMeter",wt.LONG),
                                ("biYPelsPerMeter",wt.LONG),("biClrUsed",wt.DWORD),("biClrImportant",wt.DWORD)]

                bih = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER),
                                       biWidth=cap_w, biHeight=-cap_h, biPlanes=1, biBitCount=32,
                                       biCompression=0)
                buf = (ctypes.c_char * (cap_w * cap_h * 4))()
                gdi.GetDIBits(hdc_mem, hbm, 0, cap_h, buf, ctypes.byref(bih), 0)

                gdi.SelectObject(hdc_mem, old_bm)
                gdi.DeleteObject(hbm)
                gdi.DeleteDC(hdc_mem)
                user.ReleaseDC(_vp(0), hdc_screen)

                full_img = Image.frombuffer("RGBA", (cap_w, cap_h), buf, "raw", "BGRA", 0, 1)

                px = max(0, int(round(x * dpr)))
                py = max(0, int(round(y * dpr)))
                pw = max(1, int(round(w * dpr)))
                ph = max(1, int(round(h * dpr)))
                img = full_img.crop((px, py, px + pw, py + ph))

            finally:
                if prev_dpi_ctx is not None:
                    try: user.SetThreadDpiAwarenessContext(prev_dpi_ctx)
                    except Exception: pass

            default_name = f"ComfyUI-EZi-screenshot-{time.strftime('%Y%m%d_%H%M%S')}.png"
            save_path = None
            if self._window:
                try:
                    result = self._window.create_file_dialog(
                        SAVE_DIALOG_TYPE,
                        directory=self._last_save_dir,
                        save_filename=default_name,
                        file_types=("PNG Image (*.png)", "All Files (*.*)")
                    )
                    if result:
                        save_path = result[0] if isinstance(result, (list, tuple)) else result
                        self._last_save_dir = os.path.dirname(save_path)
                        self._settings["last_save_dir"] = self._last_save_dir
                        _save_settings(self._settings)
                except Exception:
                    save_path = None

            if not save_path:
                try:
                    import ctypes.wintypes as wt
                    ctypes.windll.ole32.CoInitializeEx(None, 0x2)
                    class OPENFILENAME(ctypes.Structure):
                        _fields_ = [
                            ("lStructSize",wt.DWORD),("hwndOwner",wt.HWND),("hInstance",wt.HINSTANCE),
                            ("lpstrFilter",wt.LPCWSTR),("lpstrCustomFilter",wt.LPWSTR),
                            ("nMaxCustFilter",wt.DWORD),("nFilterIndex",wt.DWORD),
                            ("lpstrFile",wt.LPWSTR),("nMaxFile",wt.DWORD),
                            ("lpstrFileTitle",wt.LPWSTR),("nMaxFileTitle",wt.DWORD),
                            ("lpstrInitialDir",wt.LPCWSTR),("lpstrTitle",wt.LPCWSTR),
                            ("Flags",wt.DWORD),("nFileOffset",wt.WORD),("nFileExtension",wt.WORD),
                            ("lpstrDefExt",wt.LPCWSTR),("lCustData",wt.LPARAM),
                            ("lpfnHook",wt.LPVOID),("lpTemplateName",wt.LPCWSTR),
                            ("pvReserved",wt.LPVOID),("dwReserved",wt.DWORD),("FlagsEx",wt.DWORD)
                        ]
                    buf_path = ctypes.create_unicode_buffer(default_name, 1024)
                    ofn = OPENFILENAME()
                    ofn.lStructSize = ctypes.sizeof(OPENFILENAME)
                    ofn.hwndOwner   = hwnd if hwnd else None
                    ofn.lpstrFilter = "PNG Image\0*.png\0All Files\0*.*\0"
                    ofn.nFilterIndex = 1
                    ofn.lpstrFile   = buf_path
                    ofn.nMaxFile    = 1024
                    ofn.lpstrInitialDir = self._last_save_dir
                    ofn.lpstrTitle  = "Save Screenshot"
                    ofn.lpstrDefExt = "png"
                    ofn.Flags       = 0x00000002 | 0x00000800
                    if ctypes.windll.comdlg32.GetSaveFileNameW(ctypes.byref(ofn)):
                        save_path = buf_path.value
                        self._last_save_dir = os.path.dirname(save_path)
                        self._settings["last_save_dir"] = self._last_save_dir
                        _save_settings(self._settings)
                    ctypes.windll.ole32.CoUninitialize()
                except Exception:
                    pass

            if save_path:
                img.convert("RGB").save(save_path, "PNG")
        except Exception as e:
            self._print(f"Screenshot error: {e}")

    def save_window_state(self):
        if not self._window:
            return
        try:
            hwnd = self._main_hwnd or _get_hwnd(self._window)
            if not hwnd:
                return

            import ctypes.wintypes as wt
            user = ctypes.windll.user32

            if bool(user.IsIconic(hwnd)):
                return

            class WINDOWPLACEMENT(ctypes.Structure):
                _fields_ = [
                    ("length",              wt.UINT),
                    ("flags",               wt.UINT),
                    ("showCmd",             wt.UINT),
                    ("ptMinPosition",       wt.POINT),
                    ("ptMaxPosition",       wt.POINT),
                    ("rcNormalPosition",    wt.RECT),
                ]
            wp = WINDOWPLACEMENT()
            wp.length = ctypes.sizeof(WINDOWPLACEMENT)
            if not user.GetWindowPlacement(hwnd, ctypes.byref(wp)):
                return

            is_maximized = (wp.showCmd == 3)
            nr = wp.rcNormalPosition
            normal_rect = [nr.left, nr.top, nr.right, nr.bottom]

            w = normal_rect[2] - normal_rect[0]
            h = normal_rect[3] - normal_rect[1]
            if w < 50 or h < 50:
                return

            try:
                user.GetDpiForWindow.argtypes = [ctypes.c_void_p]
                user.GetDpiForWindow.restype  = wt.UINT
                saved_dpi = user.GetDpiForWindow(ctypes.c_void_p(hwnd))
            except Exception:
                saved_dpi = 96
            if not saved_dpi:
                saved_dpi = 96

            saved_state = {
                "showCmd":          3 if is_maximized else 1,
                "rcNormalPosition": normal_rect,
                "saved_dpi":        saved_dpi,
            }

            if is_maximized:
                rc = wt.RECT()
                if user.GetWindowRect(hwnd, ctypes.byref(rc)):
                    saved_state["maximized_rect"] = [rc.left, rc.top, rc.right, rc.bottom]

            if self._settings.get("window_placement") != saved_state:
                self._settings["window_placement"] = saved_state
                _save_settings(self._settings)
        except Exception:
            pass

        if self._console_detached:
            try:
                c_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
                if c_hwnd:
                    self._save_console_placement(c_hwnd)
            except Exception:
                pass

    def save_comfy_storage(self, storage_json):
        try:
            data = json.loads(storage_json)
            if not data or (isinstance(data.get("ls"), dict) and not data["ls"] and isinstance(data.get("ss"), dict) and not data["ss"]):
                return
            DRAFT_PREFIXES = (
                "Comfy.Workflow.DraftIndex.v2:",
                "Comfy.Workflow.Draft.v2:",
                "Comfy.Workflow.LastActivePath:",
                "Comfy.Workflow.LastOpenPaths:",
                "workflow",
            )
            MAX_STORAGE_BYTES = 2 * 1024 * 1024
            def _should_skip(k):
                return any(k.startswith(p) for p in DRAFT_PREFIXES)
            if isinstance(data.get("ls"), dict):
                data["ls"] = {k: v for k, v in data["ls"].items() if not _should_skip(k)}
            if isinstance(data.get("ss"), dict):
                data["ss"] = {k: v for k, v in data["ss"].items() if not _should_skip(k)}
            try:
                if len(json.dumps(data)) > MAX_STORAGE_BYTES:
                    return
            except Exception:
                pass
            self._settings["comfy_storage"] = data
            self._storage_holder[0] = data
            _save_settings(self._settings)
        except Exception:
            pass

    def get_ui_settings(self):
        try:
            hide = self._settings.get("hide_deprecation_warnings", True)
            fb = self._settings.get("custom_file_browser", "")
            theme = self._settings.get("theme", "dark")
            comfy_theme = _get_comfy_current_theme()
            comfy_theme_vars = _get_comfy_theme_css_vars()
            comfy_settings_path = os.path.join(_get_comfy_user_dir(), 'comfy.settings.json')
            console_detached = self._settings.get("console_detached", False)
            console_placement = self._settings.get("console_placement", None)
            custom_paths_json = self.get_custom_paths()
            custom_paths = json.loads(custom_paths_json) if custom_paths_json else {'input': '', 'output': '', 'user': ''}
            return json.dumps({
                "hideDeprecationWarnings": hide,
                "customFileBrowser": fb,
                "theme": theme,
                "comfyTheme": comfy_theme,
                "comfyThemeVars": comfy_theme_vars,
                "comfySettingsPath": comfy_settings_path,
                "consoleDetached": console_detached,
                "consolePlacement": console_placement,
                "customPaths": custom_paths,
                "recFps": self._settings.get("rec_fps", 15),
                "consoleBgImage":   self._settings.get("console_bg_image", ""),
                "consoleBgFit":     self._settings.get("console_bg_fit", "fit"),
                "consoleBgOpacity": self._settings.get("console_bg_opacity", 0.12),
            })
        except Exception as e:
            print(f"[EZi DEBUG] get_ui_settings ERROR: {e}", flush=True)
            return None

    def save_ui_settings(self, settings_json):
        try:
            if not settings_json or not isinstance(settings_json, str) or not settings_json.strip():
                return
            data = json.loads(settings_json)
            if not isinstance(data, dict) or not data:
                return
            if "hideDeprecationWarnings" in data:
                self._settings["hide_deprecation_warnings"] = bool(data["hideDeprecationWarnings"])
            if "customFileBrowser" in data:
                self._settings["custom_file_browser"] = str(data["customFileBrowser"]).strip()
            if "theme" in data and data["theme"] in ("dark", "pixaroma", "light", "comfyui"):
                self._settings["theme"] = data["theme"]
            if "consoleDetached" in data:
                self._settings["console_detached"] = bool(data["consoleDetached"])
            if "recFps" in data and int(data["recFps"]) in (15, 30, 60):
                self._settings["rec_fps"] = int(data["recFps"])
            if "consoleBgImage" in data:
                self._settings["console_bg_image"] = str(data["consoleBgImage"]).strip()
            if "consoleBgFit" in data and data["consoleBgFit"] in ("fit", "stretch", "tile", "center"):
                self._settings["console_bg_fit"] = data["consoleBgFit"]
            if "consoleBgOpacity" in data:
                try:
                    val = float(data["consoleBgOpacity"])
                    if 0.03 <= val <= 0.60:
                        self._settings["console_bg_opacity"] = val
                except (ValueError, TypeError):
                    pass
            if self._settings_holder is not None:
                self._settings_holder[0] = self._settings
            _save_settings(self._settings)
        except Exception:
            pass

    def get_comfy_storage(self):
        return self._settings.get("comfy_storage", None)

    def detach_console(self):
        try:
            kernel32 = ctypes.windll.kernel32
            user32   = ctypes.windll.user32

            kernel32.AllocConsole()

            hwnd = kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.kernel32.SetConsoleTitleW(f"ComfyUI Console  [EZi v{APP_VERSION}]")
                placement = self._settings.get("console_placement")
                if placement and isinstance(placement, dict):
                    try:
                        import ctypes.wintypes as wt
                        x  = placement.get("x",  100)
                        y  = placement.get("y",  100)
                        cx = placement.get("cx", 900)
                        cy = placement.get("cy", 500)
                        sw = placement.get("showCmd", 1)
                        if sw == 3:
                            mx_rect = placement.get("maximized_rect")
                            if mx_rect and _is_rect_on_active_monitor(mx_rect[0], mx_rect[1], mx_rect[2], mx_rect[3]):
                                user32.MoveWindow(hwnd, x, y, cx, cy, False)
                                user32.ShowWindow(hwnd, 3)
                            else:
                                user32.ShowWindow(hwnd, 3)
                        else:
                            if _is_rect_on_active_monitor(x, y, x + cx, y + cy):
                                user32.MoveWindow(hwnd, x, y, cx, cy, True)
                            user32.ShowWindow(hwnd, 9)
                    except Exception:
                        user32.ShowWindow(hwnd, 9)
                else:
                    user32.ShowWindow(hwnd, 9)
                user32.SetForegroundWindow(hwnd)
                _set_window_icon(hwnd)

            ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            ENABLE_PROCESSED_OUTPUT            = 0x0001
            STD_OUTPUT_HANDLE = ctypes.c_ulong(-11)
            h_stdout = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
            if h_stdout and h_stdout != ctypes.c_void_p(-1).value:
                mode = ctypes.c_ulong(0)
                if kernel32.GetConsoleMode(h_stdout, ctypes.byref(mode)):
                    kernel32.SetConsoleMode(
                        h_stdout,
                        mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING | ENABLE_PROCESSED_OUTPUT
                    )

            import msvcrt
            stdout_fd = msvcrt.open_osfhandle(
                kernel32.GetStdHandle(-11),
                os.O_WRONLY | os.O_TEXT
            )
            stderr_fd = msvcrt.open_osfhandle(
                kernel32.GetStdHandle(-12),
                os.O_WRONLY | os.O_TEXT
            )
            sys.stdout = open(stdout_fd, 'w', encoding='utf-8', errors='replace', closefd=False, newline='')
            sys.stderr = open(stderr_fd, 'w', encoding='utf-8', errors='replace', closefd=False, newline='')

            self._settings["console_detached"] = True
            _save_settings(self._settings)

            self._console_detached = True

            CTRL_CLOSE_EVENT = 2
            HandlerRoutine = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulong)

            def _ctrl_handler(ctrl_type):
                if ctrl_type == CTRL_CLOSE_EVENT and self._console_detached:
                    try:
                        self.save_window_state()
                    except Exception:
                        pass
                    self._confirm_close = True
                    try:
                        if self._proc:
                            self._kill_process_tree(self._proc.pid)
                            self._proc = None
                    except Exception:
                        pass
                    try:
                        self._window.destroy()
                    except Exception:
                        pass
                    return False
                return False

            self._ctrl_handler_ref = HandlerRoutine(_ctrl_handler)
            self._console_close_decision = None
            kernel32.SetConsoleCtrlHandler(self._ctrl_handler_ref, True)



            return True
        except Exception as e:
            return False

    def _save_console_placement(self, hwnd):
        try:
            import ctypes.wintypes as wt
            user32 = ctypes.windll.user32

            is_maximized = bool(user32.IsZoomed(hwnd))
            if bool(user32.IsIconic(hwnd)):
                return

            rc = wt.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rc)):
                return
            placement = {
                "x":       rc.left,
                "y":       rc.top,
                "cx":      rc.right  - rc.left,
                "cy":      rc.bottom - rc.top,
                "showCmd": 3 if is_maximized else 1,
            }

            if is_maximized:
                placement["maximized_rect"] = [rc.left, rc.top, rc.right, rc.bottom]

            if self._settings.get("console_placement") != placement:
                self._settings["console_placement"] = placement
                _save_settings(self._settings)
        except Exception:
            pass

    def reattach_console(self):
        try:
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                self._save_console_placement(hwnd)

            try:
                if hasattr(self, '_ctrl_handler_ref') and self._ctrl_handler_ref:
                    ctypes.windll.kernel32.SetConsoleCtrlHandler(self._ctrl_handler_ref, False)
                    self._ctrl_handler_ref = None
            except Exception:
                pass

            ctypes.windll.kernel32.FreeConsole()

            try:
                _devnull = open(os.devnull, 'w', encoding='utf-8', errors='replace')
                sys.stdout = _devnull
                sys.stderr = _devnull
            except Exception:
                pass

            self._console_detached = False
            self._settings["console_detached"] = False
            _save_settings(self._settings)
            return True
        except Exception:
            self._console_detached = False
            self._settings["console_detached"] = False
            _save_settings(self._settings)
            return False

    def stop(self):
        try:
            self.save_window_state()
        except Exception:
            pass
        self._window = None
        self._kill_running_proc()

    def _run(self):
        try:
            if not os.path.isdir(os.path.join(ROOT_DIR, "python_embeded")):
                self._println(
                    f"\033[91m✖  Wrong script location!\033[0m\n"
                    f"\n"
                    f"ComfyUI-EZi.py must be placed three levels below the ComfyUI root:\n"
                    f"\033[93m  <ComfyUI Root>\\Add-Ons\\Tools\\Helper-CEI\\ComfyUI-EZi.py\033[0m\n"
                    f"\n"
                    f"Current location:\n"
                    f"\033[93m  {CURRENT_SCRIPT_DIR}\033[0m"
                )
                return
            main_path = None
            for loc in [os.path.join(ROOT_DIR, "main.py"), os.path.join(ROOT_DIR, "ComfyUI", "main.py")]:
                if os.path.exists(loc):
                    main_path = loc; break

            if not main_path:
                self._print("Error: main.py not found!"); return

            extra_args = []
            py_flags = ['-X', 'utf8=1']
            if not os.path.exists(BAT_FILE):
                bat_name = os.path.basename(BAT_FILE)
                self._safe_eval(f"show_bat_missing({json.dumps(bat_name)})")
            if os.path.exists(BAT_FILE):
                with open(BAT_FILE, 'r', encoding='utf-8', errors='replace') as f:
                    bat_content = f.read()

                ENV_TO_ARG = {
                    'COMFY_INPUT_DIR':  '--input-directory',
                    'COMFY_OUTPUT_DIR': '--output-directory',
                    'COMFY_USER_DIR':   '--user-directory',
                }
                env_dirs = {}
                for env_name, arg_name in ENV_TO_ARG.items():
                    m_env = re.search(
                        r'(?i)set\s+"?' + re.escape(env_name) + r'=([^"\n]+)"?',
                        bat_content
                    )
                    if m_env:
                        env_dirs[arg_name] = m_env.group(1).strip().strip('"')

                m = re.search(r'python_embeded[/\\]python\.exe["\']?\s+(.*)',
                              _find_bat_comfy_line(bat_content) or '', re.IGNORECASE)
                if m:
                    raw_str = m.group(1).strip()
                    parsed = shlex.split(raw_str, posix=False)

                    script_idx = None
                    for idx, token in enumerate(parsed):
                        if token.endswith('.py'):
                            script_idx = idx
                            break

                    if script_idx is not None:
                        pre_script = parsed[:script_idx]
                        post_script = parsed[script_idx + 1:]
                    else:
                        pre_script = []
                        post_script = parsed

                    PY_FLAGS_WITH_VALUE = {'-W', '-X'}
                    j = 0
                    while j < len(pre_script):
                        tok = pre_script[j]
                        if tok in PY_FLAGS_WITH_VALUE and j + 1 < len(pre_script):
                            py_flags.extend([tok, pre_script[j + 1]])
                            j += 2
                        elif tok.startswith('-'):
                            py_flags.append(tok)
                            j += 1
                        else:
                            j += 1

                    ARGS_SINGLE_VAL = {
                        '--port', '--tls-keyfile', '--tls-certfile',
                        '--max-upload-size', '--base-directory',
                        '--output-directory', '--temp-directory', '--input-directory',
                        '--cuda-device', '--default-device',
                        '--oneapi-device-selector',
                        '--preview-size', '--cache-lru',
                        '--reserve-vram', '--default-hashing-function',
                        '--front-end-version', '--front-end-root',
                        '--user-directory', '--comfy-api-base', '--database-url',
                    }
                    ARGS_OPT_VAL = {
                        '--listen', '--enable-cors-header', '--directml',
                        '--preview-method', '--cache-ram', '--async-offload',
                        '--verbose',
                    }
                    ARGS_MULTI_VAL = {
                        '--extra-model-paths-config', '--whitelist-custom-nodes',
                    }
                    ARGS_OPT_MULTI_VAL = {
                        '--fast',
                    }
                    i = 0
                    while i < len(post_script):
                        arg = post_script[i]
                        if arg in ARGS_SINGLE_VAL:
                            if i + 1 < len(post_script):
                                val = post_script[i + 1].strip('"\'')
                                extra_args.extend([arg, val])
                                env_dirs.pop(arg, None)
                                i += 2
                            else:
                                i += 1
                        elif arg in ARGS_OPT_VAL:
                            extra_args.append(arg)
                            if (i + 1 < len(post_script) and
                                    not post_script[i + 1].startswith('--')):
                                extra_args.append(post_script[i + 1].strip('"\''))
                                i += 2
                            else:
                                i += 1
                        elif arg in ARGS_MULTI_VAL:
                            extra_args.append(arg)
                            i += 1
                            while i < len(post_script) and not post_script[i].startswith('--'):
                                extra_args.append(post_script[i].strip('"\''))
                                i += 1
                        elif arg in ARGS_OPT_MULTI_VAL:
                            extra_args.append(arg)
                            i += 1
                            while i < len(post_script) and not post_script[i].startswith('--'):
                                extra_args.append(post_script[i].strip('"\''))
                                i += 1
                        elif arg.startswith('--'):
                            if 'auto-launch' not in arg:
                                extra_args.append(arg)
                            i += 1
                        else:
                            i += 1

                for arg_name, path_val in env_dirs.items():
                    extra_args.extend([arg_name, path_val])

            final_args = py_flags + [main_path] + extra_args + ["--disable-auto-launch"]

            target_port = self._comfy_port_holder[0]
            for arg_i, arg_v in enumerate(extra_args):
                if arg_v == '--port' and arg_i + 1 < len(extra_args):
                    try: target_port = int(extra_args[arg_i + 1])
                    except ValueError: pass

            def _port_busy(port):
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _s:
                    _s.settimeout(0.5)
                    return _s.connect_ex(('127.0.0.1', port)) == 0

            if _port_busy(target_port):
                self._println(
                    f"\033[93m⚠  Port {target_port} is already in use!\033[0m\n"
                    f"Another application is occupying this port.\n"
                    f"Please close it, then press \033[92mRetry\033[0m."
                )
                self._safe_eval("show_port_error()")
                return

            _cols = self._get_columns()
            cmd_display = os.path.relpath(self.PY_EXE, ROOT_DIR) + ' ' + ' '.join(final_args)
            self._println('\033[2m' + cmd_display + '\033[0m\n')
            my_run_id = self._run_id
            run_env = os.environ.copy() | {"PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "TQDM_NCOLS": str(_cols)}
            _comfy_args = repr([main_path] + extra_args + ["--disable-auto-launch"])
            _bootstrap = (
                "import sys, runpy, logging\n"
                "sys.stderr = sys.stdout\n"
                "_oe = logging.StreamHandler.emit\n"
                "def _pe(self, r):\n"
                "    self.stream = sys.stdout\n"
                "    _oe(self, r)\n"
                "logging.StreamHandler.emit = _pe\n"
                f"sys.argv = {_comfy_args}\n"
                f"runpy.run_path({main_path!r}, run_name='__main__')\n"
            )
            self._proc = subprocess.Popen(
                [self.PY_EXE] + py_flags + ['-c', _bootstrap],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=ROOT_DIR, env=run_env,
                creationflags=0x08000000|0x00000200
            )
            buf = bytearray()
            prev_cr_line = ''
            for chunk in iter(lambda: self._proc.stdout.read(1), b''):
                if self._run_id != my_run_id:
                    break
                if chunk == b'\r':
                    try:
                        line = buf.decode('utf-8')
                    except UnicodeDecodeError:
                        line = buf.decode('cp1252', errors='replace')
                    buf.clear()
                    if line:
                        prev_cr_line = line
                        self._print(line + '\r')
                elif chunk == b'\n':
                    try:
                        line = buf.decode('utf-8')
                    except UnicodeDecodeError:
                        line = buf.decode('cp1252', errors='replace')
                    buf.clear()
                    if not line and prev_cr_line:
                        self._print('\n')
                        line = prev_cr_line
                    else:
                        self._print(line + '\n')
                    prev_cr_line = ''
                    m = COMFYUI_URL_RE.search(line)
                    if m and not self._url_found and not self._restarting:
                        self._url_found = True
                        detected_port = int(m.group(1))
                        self._comfy_port_holder[0] = detected_port
                        self._safe_eval("set_dot_ready()")
                        def _wait_and_load(port, proxy_port):
                            import urllib.request as _ur
                            for _ in range(40):
                                try:
                                    _ur.urlopen(f'http://127.0.0.1:{port}/object_info', timeout=2)
                                    self._safe_eval(f"load_ui('http://127.0.0.1:{proxy_port}/')")
                                    return
                                except Exception:
                                    time.sleep(0.5)
                            self._safe_eval(f"load_ui('http://127.0.0.1:{proxy_port}/')")
                        threading.Thread(target=_wait_and_load,
                                         args=(detected_port, self._proxy_port),
                                         daemon=True).start()
                    elif m and self._restarting:
                        self._comfy_port_holder[0] = int(m.group(1))
                else:
                    prev_cr_line = ''
                    buf.extend(chunk)
        except Exception as e: self._print(f"Error: {str(e)}")

    @staticmethod
    def _cmd_write_no_autoscroll(text):
        try:
            kernel32 = ctypes.windll.kernel32
            hOut = kernel32.GetStdHandle(ctypes.c_ulong(-11 & 0xFFFFFFFF))

            class _COORD(ctypes.Structure):
                _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]
            class _SMALL_RECT(ctypes.Structure):
                _fields_ = [("Left",  ctypes.c_short), ("Top",    ctypes.c_short),
                             ("Right", ctypes.c_short), ("Bottom", ctypes.c_short)]
            class _CSBI(ctypes.Structure):
                _fields_ = [("dwSize",              _COORD),
                             ("dwCursorPosition",   _COORD),
                             ("wAttributes",        ctypes.c_ushort),
                             ("srWindow",           _SMALL_RECT),
                             ("dwMaximumWindowSize", _COORD)]

            csbi = _CSBI()
            if not kernel32.GetConsoleScreenBufferInfo(hOut, ctypes.byref(csbi)):
                sys.stdout.write(text)
                sys.stdout.flush()
                return

            at_bottom  = csbi.srWindow.Bottom >= csbi.dwCursorPosition.Y
            win_height = csbi.srWindow.Bottom - csbi.srWindow.Top
            saved_top  = csbi.srWindow.Top
            old_curs_y = csbi.dwCursorPosition.Y
            buf_h      = csbi.dwSize.Y

            sys.stdout.write(text)
            sys.stdout.flush()

            if not at_bottom:
                extra_lines = text.count('\n')
                buf_scroll  = max(0, old_curs_y + extra_lines - (buf_h - 1))
                new_top     = max(0, saved_top - buf_scroll)
                new_bottom  = new_top + win_height
                if new_bottom >= buf_h:
                    new_bottom = buf_h - 1
                    new_top    = max(0, new_bottom - win_height)
                rect = _SMALL_RECT(
                    csbi.srWindow.Left,  ctypes.c_short(new_top).value,
                    csbi.srWindow.Right, ctypes.c_short(new_bottom).value,
                )
                kernel32.SetConsoleWindowInfo(hOut, True, ctypes.byref(rect))
        except Exception:
            sys.stdout.write(text)
            sys.stdout.flush()

    def _print(self, text):
        if self._console_detached:
            try:
                _DEPR = '[DEPRECATION WARNING] Detected import of deprecated legacy API:'
                if _DEPR in text:
                    if self._settings.get('hide_deprecation_warnings', True):
                        self._skip_next_newline = True
                        return
                if self._skip_next_newline:
                    self._skip_next_newline = False
                    if text == '\n' and self._settings.get('hide_deprecation_warnings', True):
                        return
                self._cmd_write_no_autoscroll(text)
            except Exception:
                pass
            return
        if self._js_ready.is_set(): self._eval_line(text)
        else:
            with self._buf_lock: self._line_buf.append(text)

    def _println(self, text):
        for line in text.split('\n'):
            self._print(line + '\n')

    def _eval_line(self, text):
        _DEPR = '[DEPRECATION WARNING] Detected import of deprecated legacy API:'
        if _DEPR in text:
            self._skip_next_newline = True
            self._safe_eval("if(!eziSettings.hideDeprecationWarnings)" +
                            f"add_to_console({json.dumps(text)})")
            return
        if self._skip_next_newline:
            self._skip_next_newline = False
            if text == '\n':
                self._safe_eval("if(!eziSettings.hideDeprecationWarnings)" +
                                f"add_to_console({json.dumps(text)})")
                return
        self._safe_eval(f"add_to_console({json.dumps(text)})")

    def _safe_eval(self, js):
        if self._window:
            try: self._window.evaluate_js(js)
            except: pass

if __name__ == '__main__':
    def find_free_port():
        with socket.socket() as s: s.bind(('', 0)); return s.getsockname()[1]

    _autorun_bat = os.path.normpath(os.path.join(CURRENT_SCRIPT_DIR, "..", "AutoRun.bat"))
    try:
        if os.path.isfile(_autorun_bat):
            os.remove(_autorun_bat)
    except Exception:
        pass

    settings = _load_settings()
    settings["_dpi_aware_version"] = 1
    p_port = find_free_port()
    c_port_h = [COMFY_PORT]
    storage_holder = [settings.get("comfy_storage")]
    settings_holder = [settings]

    _proxy_ready = threading.Event()

    loop = asyncio.new_event_loop()
    def start_proxy():
        asyncio.set_event_loop(loop)
        async def _run():
            app = await make_proxy_app(c_port_h, storage_holder, settings_holder)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, '127.0.0.1', p_port)
            await site.start()
            _proxy_ready.set()
            await asyncio.Event().wait()
        loop.run_until_complete(_run())

    threading.Thread(target=start_proxy, daemon=True).start()
    _proxy_ready.wait(timeout=10)

    def _clear_webview2_cache():
        try:
            import shutil
            base = os.environ.get('LOCALAPPDATA', '')
            temp = os.environ.get('TEMP', '')
            candidates = [
                os.path.join(base, 'pywebview', 'EBWebView'),
                os.path.join(temp, 'pywebview', 'EBWebView'),
            ]
            for path in candidates:
                if os.path.isdir(path):
                    try:
                        shutil.rmtree(path, ignore_errors=True)
                    except Exception:
                        pass
        except Exception:
            pass
    _clear_webview2_cache()

    api = Api(p_port, c_port_h, settings, storage_holder, settings_holder)

    import atexit
    atexit.register(api._kill_running_proc)

    try:
        window = webview.create_window(
            f'ComfyUI-EZi Desktop  v{APP_VERSION}',
            url=f'http://127.0.0.1:{p_port}/__shell__',
            js_api=api,
            user_agent=CHROME_UA,
        )
    except TypeError:
        window = webview.create_window(
            f'ComfyUI-EZi Desktop  v{APP_VERSION}',
            url=f'http://127.0.0.1:{p_port}/__shell__',
            js_api=api,
        )
    api.set_window(window)
    window.events.loaded += api.on_loaded
    window.events.closed  += api.stop

    def _on_closing():
        if api._updating or api._confirm_close:
            return True
        def _ask():
            try:
                u32 = ctypes.windll.user32
                hwnd = _get_hwnd(window)
                if api._console_detached:
                    try:
                        c = ctypes.windll.kernel32.GetConsoleWindow()
                        if c:
                            u32.ShowWindow(c, 0)
                    except Exception:
                        pass
                if hwnd:
                    try:
                        if u32.IsIconic(hwnd):
                            u32.ShowWindow(hwnd, 9)
                        u32.SetForegroundWindow(hwnd)
                        u32.BringWindowToTop(hwnd)
                    except Exception:
                        pass
                api._window.evaluate_js("show_close_confirm();")
                time.sleep(0.08)
                if hwnd:
                    try:
                        u32.SetForegroundWindow(hwnd)
                    except Exception:
                        pass
            except Exception:
                if api._console_detached:
                    try:
                        c = ctypes.windll.kernel32.GetConsoleWindow()
                        if c:
                            ctypes.windll.user32.ShowWindow(c, 9)
                    except Exception:
                        pass
                api._confirm_close = True
                try:
                    api._window.destroy()
                except Exception:
                    pass
        threading.Thread(target=_ask, daemon=True).start()
        return False
    window.events.closing += _on_closing

    def _restore_on_shown():
        try:
            hwnd = _get_hwnd(window)
            if not hwnd:
                threading.Timer(0.3, _restore_on_shown).start()
                return

            wp_data = settings.get("window_placement")
            if not wp_data or not isinstance(wp_data, dict):
                return

            import ctypes.wintypes as wt
            user = ctypes.windll.user32

            prev_dpi_ctx = None
            try:
                prev_dpi_ctx = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
            except Exception:
                pass

            try:
                class WINDOWPLACEMENT(ctypes.Structure):
                    _fields_ = [("length", wt.UINT), ("flags", wt.UINT), ("showCmd", wt.UINT),
                                ("ptMinPosition", wt.POINT), ("ptMaxPosition", wt.POINT),
                                ("rcNormalPosition", wt.RECT)]

                wp = WINDOWPLACEMENT()
                wp.length = ctypes.sizeof(WINDOWPLACEMENT)

                show_cmd = wp_data.get("showCmd", 1)
                rc_data  = wp_data.get("rcNormalPosition")
                if not rc_data or len(rc_data) != 4:
                    return

                saved_dpi = wp_data.get("saved_dpi", 96) or 96
                current_dpi = 96
                try:
                    user.GetDpiForWindow.argtypes = [ctypes.c_void_p]
                    user.GetDpiForWindow.restype  = wt.UINT
                    current_dpi = user.GetDpiForWindow(ctypes.c_void_p(hwnd)) or 96
                except Exception:
                    pass

                if saved_dpi != current_dpi:
                    scale = current_dpi / saved_dpi
                    def _scale_rect(r):
                        left  = int(round(r[0] * scale))
                        top   = int(round(r[1] * scale))
                        right = int(round(left + (r[2] - r[0]) * scale))
                        bottom= int(round(top  + (r[3] - r[1]) * scale))
                        return [left, top, right, bottom]
                    rc_data = _scale_rect(rc_data)
                    mx_rect = wp_data.get("maximized_rect")
                    if mx_rect:
                        mx_rect = _scale_rect(mx_rect)
                    else:
                        mx_rect = None
                else:
                    mx_rect = wp_data.get("maximized_rect")

                def _primary_monitor_center_rect(w=1100, h=700):
                    try:
                        sw = user.GetSystemMetrics(0)
                        sh = user.GetSystemMetrics(1)
                        x = max(0, (sw - w) // 2)
                        y = max(0, (sh - h) // 2)
                        return [x, y, x + w, y + h]
                    except Exception:
                        return [100, 100, 1200, 800]

                if show_cmd == 3:
                    check_rect = mx_rect if mx_rect else rc_data
                    if not _is_rect_on_active_monitor(check_rect[0], check_rect[1], check_rect[2], check_rect[3]):
                        fallback = _primary_monitor_center_rect()
                        wp.showCmd = 1
                        wp.rcNormalPosition = wt.RECT(fallback[0], fallback[1], fallback[2], fallback[3])
                    else:
                        wp.showCmd = 3
                        wp.rcNormalPosition = wt.RECT(rc_data[0], rc_data[1], rc_data[2], rc_data[3])
                else:
                    if not _is_rect_on_active_monitor(rc_data[0], rc_data[1], rc_data[2], rc_data[3]):
                        fallback = _primary_monitor_center_rect()
                        wp.showCmd = 1
                        wp.rcNormalPosition = wt.RECT(fallback[0], fallback[1], fallback[2], fallback[3])
                    else:
                        wp.showCmd = 1
                        wp.rcNormalPosition = wt.RECT(rc_data[0], rc_data[1], rc_data[2], rc_data[3])

                user.SetWindowPlacement(hwnd, ctypes.byref(wp))
                def _reapply():
                    try:
                        user.SetWindowPlacement(hwnd, ctypes.byref(wp))
                    except Exception:
                        pass
                threading.Timer(0.25, _reapply).start()
            finally:
                if prev_dpi_ctx is not None:
                    try:
                        user.SetThreadDpiAwarenessContext(prev_dpi_ctx)
                    except Exception:
                        pass
        except Exception:
            pass

    window.events.shown += _restore_on_shown

    try:
        webview.start(user_agent=CHROME_UA)
    except TypeError:
        webview.start()
