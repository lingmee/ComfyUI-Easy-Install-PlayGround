try:
    import webview
except ImportError:
    import sys, subprocess, os
    print("pywebview not found — attempting to install...")
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
import os
import sys
import ctypes
import asyncio
import socket
import shlex
import base64
import time

try:
    from aiohttp import web, ClientSession, ClientTimeout, WSMsgType
except ImportError:
    print("aiohttp not found — install it or use ComfyUI's python_embeded")
    sys.exit(1)


CURRENT_SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
ROOT_DIR = os.path.normpath(os.path.join(CURRENT_SCRIPT_DIR, "..", "..", ".."))

ICO_PATH = os.path.join(CURRENT_SCRIPT_DIR, "ComfyUI-EZi-Desktop.ico")
SETTINGS_PATH = os.path.join(CURRENT_SCRIPT_DIR, "ComfyUI-EZi.settings.json")

APP_VERSION = "3.0.0"

_bat_arg = sys.argv[1] if len(sys.argv) > 1 else "Start ComfyUI.bat"
BAT_FILE = _bat_arg if os.path.isabs(_bat_arg) else os.path.join(ROOT_DIR, _bat_arg)
COMFY_PORT = 8188

COMFYUI_URL_RE = re.compile(r'https?://(?:127\.0\.0\.1|localhost|0\.0\.0\.0):(\d+)', re.IGNORECASE)

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

def _load_settings():
    defaults = {
        "last_save_dir": _get_desktop(),
        "window_maximized": False,
        "window_placement": None,
        "hide_deprecation_warnings": True,
    }
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            defaults.update(data)
    except Exception:
        pass
    return defaults

def _save_settings(settings):
    try:
        if not settings or not isinstance(settings, dict):
            return
        ALLOWED = ("last_save_dir", "window_maximized", "comfy_storage", "hide_deprecation_warnings", "window_placement")
        existing = {}
        try:
            if os.path.exists(SETTINGS_PATH):
                with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if not isinstance(existing, dict):
                    existing = {}
        except Exception:
            pass
        merged = existing.copy()
        for k in ALLOWED:
            if k in settings:
                merged[k] = settings[k]
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
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #0c0e12; font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px; color: #ccc; height: 100vh; display: flex;
    flex-direction: column; overflow: hidden;
  }
  #bar {
    display: flex; align-items: center; background: #161b22;
    border-bottom: 1px solid #21262d; padding: 0 10px; height: 32px;
    flex-shrink: 0; user-select: none; gap: 8px; z-index: 100000;
    position: relative;
  }
  #dot { width: 8px; height: 8px; border-radius: 50%; background: #f1fa8c; animation: pulse 1.5s infinite; }
  #dot.ready { background: #50fa7b; animation: none; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.25} }
  #status { color: #8b949e; font-size: 11px; }
  #btn {
    padding: 3px 14px; font-family: inherit; font-size: 11px; font-weight: bold;
    border: 1px solid #30363d; border-radius: 4px; background: #21262d; color: #8b949e;
    cursor: default; transition: all .2s; order: -1; margin-right: 4px;
    line-height: 1; pointer-events: none;
  }
  #btn.active {
    border-color: #388bfd; background: #0d419d; color: #fff;
    cursor: pointer; pointer-events: auto;
  }
  #btn.active:hover { background:#1158c7; border-color:#58a6ff; }
  #update-btn {
    padding: 3px 12px; font-family: inherit; font-size: 11px; font-weight: bold;
    border: 1px solid #f1fa8c; border-radius: 4px; background: #5a4a00; color: #f1fa8c;
    cursor: pointer; transition: all .2s; line-height: 1; letter-spacing: 0.5px;
  }
  #update-btn:hover { background:#7a6500; border-color:#fff; color:#fff; }
  #scr-btn {
    padding: 3px 10px; font-family: inherit; font-size: 11px; font-weight: bold;
    border: 1px solid #388bfd; border-radius: 4px; background: #0d419d; color: #fff;
    cursor: pointer; transition: all .2s;
    line-height: 1; letter-spacing: 0.5px;
  }
  #out-btn {
    padding: 3px 10px; font-family: inherit; font-size: 11px; font-weight: bold;
    border: 1px solid #30363d; border-radius: 4px; background: #21262d; color: #8b949e;
    cursor: pointer; transition: all .2s;
    line-height: 1; letter-spacing: 0.5px;
  }
  #out-btn:hover { background: #2d333b; border-color: #484f58; color: #ccc; }
  #update-notice {
    position: absolute; left: 50%; transform: translateX(-50%);
    display: none; align-items: center; gap: 8px;
  }
  #out-btn { margin-left: auto; display: none; }
  #out-btn.visible { display: inline-block; }
  #scr-btn:hover { background:#1158c7; border-color:#58a6ff; }
  #settings-btn {
    padding: 3px 8px; font-family: inherit; font-size: 13px; font-weight: bold;
    border: 1px solid #30363d; border-radius: 4px; background: #21262d; color: #8b949e;
    cursor: pointer; transition: all .2s; line-height: 1;
  }
  #settings-btn:hover { background: #2d333b; border-color: #484f58; color: #ccc; }
  .settings-row {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 0; border-bottom: 1px solid #21262d;
  }
  .settings-row:last-child { border-bottom: none; }
  .settings-row label { flex: 1; font-size: 12px; color: #ccc; cursor: pointer; user-select: none; }
  .settings-row input[type=checkbox] { width: 15px; height: 15px; cursor: pointer; accent-color: #388bfd; flex-shrink: 0; }
  .settings-row select {
    background: #0d1117; color: #ccc; border: 1px solid #30363d; border-radius: 4px;
    font-family: inherit; font-size: 11px; padding: 3px 6px; cursor: pointer;
    flex-shrink: 0; max-width: 160px;
  }
  .settings-row select:focus { outline: none; border-color: #388bfd; }
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
    position: absolute; border: 1px solid #58a6ff;
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
  #panels { flex: 1; position: relative; overflow: hidden; background: #0c0e12; }
  #term-panel, #ui-panel {
    position: absolute; inset: 0;
    transition: transform 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease;
    background: #0c0e12;
  }
  #term-panel { 
    z-index: 5; overflow-y: auto; padding: 10px 14px; 
    user-select: text !important; transform: translateX(0); opacity: 1;
    white-space: pre-wrap; word-break: break-all;
  }
  #ico-bg {
    pointer-events: none; position: absolute;
    width: {ICO_W}px; height: {ICO_H}px;
    top: 50%; left: 50%; transform: translate(-50%, -50%);
    background-image: {ICO_BG};
    background-repeat: no-repeat; background-size: {ICO_W}px {ICO_H}px;
    opacity: 0.12; z-index: 6;
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
    background: #161b22; border: 1px solid #30363d; border-radius: 10px;
    padding: 22px 24px 18px; min-width: 320px; max-width: 480px;
    max-height: 90vh; overflow-y: auto;
    box-shadow: 0 8px 32px rgba(0,0,0,0.6); display: flex; flex-direction: column; gap: 12px;
    animation: modal-in 0.15s ease;
  }
  @keyframes modal-in { from { opacity:0; transform:scale(0.93) translateY(-8px); } to { opacity:1; transform:none; } }
  #modal-icon { font-size: 28px; line-height: 1; }
  #modal-title { font-size: 14px; font-weight: bold; color: #e6edf3; }
  #modal-msg { font-size: 12px; color: #8b949e; line-height: 1.6; user-select: text; }
  #modal-btns { display: flex; gap: 10px; justify-content: flex-end; margin-top: 4px; }
  .modal-btn {
    padding: 5px 18px; font-family: inherit; font-size: 11px; font-weight: bold;
    border-radius: 6px; border: 1px solid #30363d; background: #21262d; color: #8b949e;
    cursor: pointer; transition: all .15s; line-height: 1.4;
  }
  .modal-btn:hover { background: #2d333b; color: #ccc; border-color: #484f58; }
  .modal-btn.primary { background: #0d419d; border-color: #388bfd; color: #fff; }
  .modal-btn.primary:hover { background: #1158c7; border-color: #58a6ff; }
  .modal-btn.danger { background: #6e2020; border-color: #ff5555; color: #fff; }
  .modal-btn.danger:hover { background: #8a2a2a; border-color: #ff7070; }
  .stab-btn {
    padding: 4px 14px; font-family: inherit; font-size: 11px; font-weight: bold;
    border: 1px solid #30363d; border-radius: 4px; background: #21262d; color: #8b949e;
    cursor: pointer; transition: all .15s; line-height: 1.4;
  }
  .stab-btn:hover { background: #2d333b; color: #ccc; border-color: #484f58; }
  .stab-btn.active { background: #0d419d; border-color: #388bfd; color: #fff; }
  .bat-section-title { font-size: 11px; font-weight: bold; color: #8b949e; margin-bottom:4px; }
  .bat-section-title--accent { color: #58a6ff; text-transform: uppercase; letter-spacing: 0.6px; font-size: 10px; border-bottom: 1px solid #21262d; padding-bottom: 3px; }
  .bat-row {
    display: flex; align-items: center; gap: 8px;
    padding: 5px 0; border-bottom: 1px solid #21262d;
  }
  .bat-row:last-child { border-bottom: none; }
  .bat-info { flex: 1; display: flex; flex-direction: column; gap: 1px; }
  .bat-label { font-size: 12px; color: #e6edf3; }
  .bat-desc  { font-size: 10px; color: #8b949e; }
  .bat-run-btn { flex-shrink: 0; padding: 3px 12px; font-size: 11px; }
  .bat-clickable {
    display: flex; align-items: center;
    padding: 6px 8px; border-bottom: 1px solid #21262d;
    cursor: pointer; border-radius: 4px; transition: background .15s;
  }
  .bat-clickable:last-child { border-bottom: none; }
  .bat-clickable:hover { background: #1c2128; }
  .bat-clickable:hover .bat-label { color: #58a6ff; }
  .modal-btn:disabled {
    opacity: 0.4;
    cursor: default !important;
    background: #21262d !important;
    border-color: #30363d !important;
    color: #8b949e !important;
  }
</style>
</head>
<body>
<div id="bar"><div id="dot"></div><span id="status">Starting...</span><div id="update-notice"><span id="update-msg" style="color:#f1fa8c;font-size:11px;font-weight:bold;">&#x2B06; ComfyUI update available</span><button id="update-btn" onclick="doUpdate()">Update ComfyUI</button></div><button id="btn" onclick="toggle()">ComfyUI ▶</button><button id="out-btn" onclick="pywebview.api.open_output_folder()" title="Open Output Folder">&#x1F4C2; Output</button><button id="scr-btn" onclick="startCrop()" title="Screenshot">&#x1F4F7; Screenshot</button><button id="settings-btn" title="Settings">&#x2699;</button></div>
<div id="crop-overlay"><div id="crop-shade-t"></div><div id="crop-shade-b"></div><div id="crop-shade-l"></div><div id="crop-shade-r"></div><div id="crop-sel"></div><div id="crop-hint">Click for full window &nbsp;|&nbsp; Drag to select area &nbsp;<button id="crop-cancel-btn" style="margin-left:8px;padding:2px 10px;font-family:inherit;font-size:11px;font-weight:bold;border:1px solid #ff5555;border-radius:4px;background:#6e2020;color:#fff;cursor:pointer;pointer-events:auto;vertical-align:middle;position:relative;top:2px;"><span style="position:relative;top:-1px;">✕</span> <span style="position:relative;top:-1px;">Cancel</span></button></div></div>
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
let lastCR = null, uiLoaded = false, showingUI = false;

const settingsDefaults = { hideDeprecationWarnings: true };
let eziSettings = Object.assign({}, settingsDefaults);
function saveEziSettings() {
  try { pywebview.api.save_ui_settings(JSON.stringify(eziSettings)); } catch(e) {}
}

function show_settings() {
  function _sysRow(label, value, color) {
    return `<tr><td style="color:#8b949e;padding:2px 10px 2px 0;white-space:nowrap">${label}</td>` +
           `<td style="color:${color||'#f1fa8c'};font-weight:bold">${value}</td></tr>`;
  }
  function _sysRowColor(label, value, color) { return _sysRow(label, value, color); }

  function _showTab(name) {
    ['general','addons','advanced'].forEach(t => {
      document.getElementById('stab-'+t).style.display = (t===name)?'block':'none';
      document.getElementById('stabtn-'+t).classList.toggle('active', t===name);
    });
  }

  const tabBar = `<div style="display:flex;gap:6px;margin-bottom:14px;border-bottom:1px solid #21262d;padding-bottom:8px">
    <button id="stabtn-general"  class="stab-btn active">General</button>
    <button id="stabtn-addons"   class="stab-btn">Add-ons</button>
    <button id="stabtn-advanced" class="stab-btn">Advanced</button>
  </div>`;

  const tabGeneral = `<div id="stab-general">
    <div style="margin-bottom:12px; padding-bottom:8px; border-bottom:1px solid #21262d;">
      <a href="#" onclick="event.preventDefault(); pywebview.api.open_url('https://github.com/Tavris1/ComfyUI-Easy-Install')" 
         style="color:#58a6ff; font-size:11px; text-decoration:none; font-weight:bold; word-break:break-all;"
         onmouseover="this.style.textDecoration='underline'" 
         onmouseout="this.style.textDecoration='none'">
         https://github.com/Tavris1/ComfyUI-Easy-Install
      </a>
    </div>
    <div style="margin-bottom:10px">
      <span style="color:#f1fa8c;font-size:11px;font-weight:bold">System info</span>
      <span id="sysinfo-loading" style="font-size:11px;margin-left:8px;font-weight:bold;color:#f1fa8c;animation:sysinfo-pulse 0.9s ease-in-out infinite">Loading...</span>
      <style>@keyframes sysinfo-pulse{0%,100%{opacity:1;text-shadow:0 0 8px #f1fa8c}50%{opacity:0.25;text-shadow:none}}</style>
      <div id="sysinfo-table"></div>
    </div>
  </div>`;

  function _batBtn(label, path, desc) {
    return `<div class="bat-clickable" data-bat="${path.replace(/"/g,'&quot;')}" title="${desc.replace(/"/g,'&quot;')}">
      <span class="bat-label" style="margin-left: 36px;">${label}</span>
    </div>`;
  }
  const tabAddons = `<div id="stab-addons" style="display:none">
    <div class="bat-section-title bat-section-title--accent">Updates</div>
    ${_batBtn('Update Easy-Install', '.\\\\Update Easy-Install.bat', 'Updates Add-ons and other folders')}
    <div class="bat-section-title bat-section-title--accent" style="margin-top:10px">Add-ons</div>
    ${_batBtn('Easy-Models-Linker', '.\\\\Add-Ons\\\\1. Easy-Models-Linker.bat', 'Link existing MODELS folder via extra_model_paths.yaml')}
    ${_batBtn('FlashAttention v2.8.3', '.\\\\Add-Ons\\\\FlashAttention.bat', 'Installs FlashAttention v2.8.3')}
    ${_batBtn('InsightFace', '.\\\\Add-Ons\\\\Insightface.bat', 'Installs InsightFace')}
    ${_batBtn('Nunchaku', '.\\\\Add-Ons\\\\Nunchaku.bat', 'Installs Nunchaku')}
    ${_batBtn('SageAttention v2.2.0 + v3', '.\\\\Add-Ons\\\\SageAttention-Multi (v2.2.0 and v3).bat', 'Installs both SageAttention v2.2.0 and v3')}
    ${_batBtn('Trellis 2.0', '.\\\\Add-Ons\\\\Trellis2 (requires Torch 2.8.0+cu128).bat', 'Installs Trellis 2.0 + model (requires Torch 2.8.0+cu128)')}
    <div class="bat-section-title bat-section-title--accent" style="margin-top:10px">Torch Pack</div>
    ${_batBtn('Torch 2.7.1+cu128', '.\\\\Add-Ons\\\\Torch-Pack\\\\Torch 2.7.1+cu128.bat', 'Switch to Torch 2.7.1+cu128')}
    ${_batBtn('Torch 2.8.0+cu128', '.\\\\Add-Ons\\\\Torch-Pack\\\\Torch 2.8.0+cu128.bat', 'Switch to Torch 2.8.0+cu128')}
    ${_batBtn('Torch 2.9.1+cu130', '.\\\\Add-Ons\\\\Torch-Pack\\\\Torch 2.9.1+cu130 (default).bat', 'Switch to Torch 2.9.1+cu130 (default)')}
    <div class="bat-section-title bat-section-title--accent" style="margin-top:10px">Tools</div>
    ${_batBtn('Easy-model2GGUF', '.\\\\Add-Ons\\\\Tools\\\\Easy-model2GGUF.bat', 'Convert & quantize models to GGUF (Q2_K - Q8_0)')}
    ${_batBtn('Long Paths Enabler', '.\\\\Add-Ons\\\\Tools\\\\Long-Paths-Enabler.bat', 'Enables Long Paths in Windows 10/11')}
    ${_batBtn('Toggle DynamicVRAM', '.\\\\Add-Ons\\\\Tools\\\\Toggle-DynamicVRAM.bat', 'Toggles --disable-dynamic-vram in startup files')}
  </div>`;

  const tabAdvanced = `<div id="stab-advanced" style="display:none">
    <div class="settings-row">
      <input type="checkbox" id="set-hide-deprecation" ${eziSettings.hideDeprecationWarnings ? 'checked' : ''}>
      <label for="set-hide-deprecation">Hide deprecation warnings in console</label>
    </div>
    <div style="border-top:1px solid #21262d;margin:6px 0"></div>
    <div class="settings-row">
      <label for="set-comfy-ver" style="cursor:default">ComfyUI version</label>
      <select id="set-comfy-ver" disabled><option>Loading...</option></select>
    </div>
    <div id="comfy-fe-hint" style="display:none;padding:2px 0 6px 0;font-size:11px;color:#8b949e">
      &#x2139; Requires frontend: <span id="comfy-fe-hint-ver" style="color:#f1fa8c;font-weight:bold"></span>
      <br><span style="color:#555">(selecting a different frontend will show NIGHTLY)</span>
    </div>
    <div class="settings-row">
      <label for="set-frontend-ver" style="cursor:default">ComfyUI Frontend version</label>
      <select id="set-frontend-ver" disabled><option>Loading...</option></select>
    </div>
  </div>`;

  let _initialHideDeprecation = eziSettings.hideDeprecationWarnings;

  function _checkChanges() {
    const hideDepChanged = document.getElementById('set-hide-deprecation').checked !== _initialHideDeprecation;
    const selComfy = document.getElementById('set-comfy-ver');
    const comfyChanged = selComfy && !selComfy.disabled && selComfy.dataset.current !== selComfy.value;
    const selFe = document.getElementById('set-frontend-ver');
    const feChanged = selFe && !selFe.disabled && selFe.dataset.current !== selFe.value;

    const applyBtn = Array.from(document.querySelectorAll('#modal-btns .modal-btn')).find(b => b.textContent.trim() === 'Apply');
    if (applyBtn) {
      const hasChanges = hideDepChanged || comfyChanged || feChanged;
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
    saveEziSettings();
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

    if (hideDepChanged || comfyChanged || feChanged) {
      document.getElementById('modal-overlay').classList.remove('active');
    }
  }

  showModal('\u2699\uFE0F', 'Settings',
    `<div style="min-width:400px">${tabBar}${tabGeneral}${tabAddons}${tabAdvanced}</div>`,
    [
      { label: 'Apply', cls: 'primary', noClose: true, action: _applySettings },
      { label: 'Close', cls: '', action: () => {} },
    ]
  );

  ['general','addons','advanced'].forEach(t => {
    const btn = document.getElementById('stabtn-'+t);
    if (btn) btn.addEventListener('click', () => {
      _showTab(t);
      _updateModalBtns(t);
    });
  });

  function _updateModalBtns(tabName) {
    const applyBtn = Array.from(document.querySelectorAll('#modal-btns .modal-btn')).find(b => b.textContent.trim() === 'Apply');
    const copyBtn  = Array.from(document.querySelectorAll('#modal-btns .modal-btn')).find(b => b.textContent.includes('Copy SysInfo') || b.textContent.includes('Copied') || b.textContent.includes('Failed'));
    if (applyBtn) applyBtn.style.display = (tabName === 'advanced') ? '' : 'none';
    if (copyBtn)  copyBtn.style.display  = (tabName === 'general')  ? '' : 'none';
    if (tabName === 'advanced') _checkChanges();
  }

  setTimeout(() => _updateModalBtns('general'), 0);

  document.getElementById('stab-addons').addEventListener('click', function(e) {
    const row = e.target.closest('.bat-clickable');
    if (!row || !row.dataset.bat) return;
    document.getElementById('modal-overlay').classList.remove('active');
    switchToConsole();
    pywebview.api.run_bat(row.dataset.bat);
  });

  setTimeout(() => {
    const depCheck = document.getElementById('set-hide-deprecation');
    if (depCheck) depCheck.addEventListener('change', _checkChanges);
    const comfySel = document.getElementById('set-comfy-ver');
    if (comfySel) comfySel.addEventListener('change', _checkChanges);
    const feSel = document.getElementById('set-frontend-ver');
    if (feSel) feSel.addEventListener('change', _checkChanges);
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
    const loadEl = document.getElementById('sysinfo-loading');
    if (loadEl) loadEl.style.display = 'none';
    const driverMajor = s.driver ? parseInt(s.driver.split('.')[0], 10) : NaN;
    const driverColor = isNaN(driverMajor) ? '#f1fa8c' : (driverMajor >= 580 ? '#50fa7b' : '#ff5555');
    const rows = [
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
    const copyBtn = document.createElement('button');
    copyBtn.className = 'modal-btn';
    copyBtn.textContent = '\uD83D\uDCCB Copy SysInfo';
    copyBtn.onclick = () => {
      const text = [
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
    const loadEl = document.getElementById('sysinfo-loading');
    if (loadEl) loadEl.textContent = 'N/A';
  });

  pywebview.api.get_comfyui_versions().then(function(data) {
    const sel = document.getElementById('set-comfy-ver');
    if (!sel) return;
    sel.innerHTML = '';
    sel.dataset.current = data.current || '';
    data.versions.forEach(function(v) {
      const opt = document.createElement('option');
      opt.value = v;
      opt.textContent = v + (v === data.current ? ' (current)' : '');
      if (v === data.current) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.disabled = false;
    sel.onchange = function() {
      const hint = document.getElementById('comfy-fe-hint');
      const hintVer = document.getElementById('comfy-fe-hint-ver');
      if (!hint || !hintVer) return;
      hint.style.display = 'none'; hintVer.textContent = '';
      pywebview.api.get_comfyui_required_frontend(sel.value).then(function(fe) {
        if (fe) { hintVer.textContent = fe; hint.style.display = ''; }
      }).catch(function(){});
      _checkChanges();
    };
    _checkChanges();
  }).catch(function() {
    const sel = document.getElementById('set-comfy-ver');
    if (sel) sel.innerHTML = '<option>Unavailable</option>';
  });

  pywebview.api.get_frontend_versions().then(function(data) {
    const sel = document.getElementById('set-frontend-ver');
    if (!sel) return;
    sel.innerHTML = '';
    sel.dataset.current = data.current;
    data.versions.forEach(function(v) {
      const opt = document.createElement('option');
      opt.value = v;
      opt.textContent = v + (v === data.current ? ' (current)' : '');
      if (v === data.current) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.disabled = false;
    _checkChanges();
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
    try { pywebview.api.ui_shown(); } catch(e) {}
    try { pywebview.api.set_title('Running'); } catch(e) {}
  };
}

function toggle() {
  if (!uiLoaded && !showingUI) return;
  if (showingUI) _saveTabsToDisk();
  showingUI = !showingUI;
  if (showingUI) {
    termPanel.style.transform = 'translateX(-100vw)'; termPanel.style.opacity = '0'; termPanel.style.pointerEvents = 'none';
    uiPanel.style.transform = 'translateX(0)'; uiPanel.style.opacity = '1'; uiPanel.style.pointerEvents = 'auto';
    icoBg.style.display = 'none';
    btn.textContent = '◀ CONSOLE'; statusEl.textContent = ''; dot.style.display = 'none';
  } else {
    uiPanel.style.transform = 'translateX(100vw)'; uiPanel.style.opacity = '0'; uiPanel.style.pointerEvents = 'none';
    termPanel.style.transition = 'none'; termPanel.style.transform = 'translateX(-100vw)'; void termPanel.offsetWidth;
    termPanel.style.transition = 'transform 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease';
    termPanel.style.transform = 'translateX(0)'; termPanel.style.opacity = '1'; termPanel.style.pointerEvents = 'auto';
    icoBg.style.display = '';
    btn.textContent = 'ComfyUI ▶'; dot.style.display = ''; statusEl.textContent = uiLoaded ? 'ComfyUI is running' : dot.classList.contains('ready') ? 'ComfyUI is starting' : 'Starting...';
  }
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

function startCrop() {
  overlay.classList.add("active");
  cropSel.style.cssText = "left:0;top:0;width:0;height:0;";
  shadeT.style.cssText = "top:0;left:0;right:0;bottom:0;";
  shadeB.style.cssText = shadeL.style.cssText = shadeR.style.cssText = "display:none";
  document.getElementById('crop-hint').style.display = '';
}

function cropCancel() {
    cropStart = null;
    overlay.classList.remove("active");
}

document.getElementById('crop-cancel-btn').addEventListener('mousedown', function(e) {
    e.stopPropagation();
});
document.getElementById('crop-cancel-btn').addEventListener('mouseup', function(e) {
    e.stopPropagation();
    e.preventDefault();
    cropCancel();
});

function screenshotFull() {
  pywebview.api.screenshot(0, 0, window.innerWidth, window.innerHeight);
}

function show_update(version) {
  const n = document.getElementById('update-notice');
  const msg = document.getElementById('update-msg');
  msg.textContent = '\u2B06 ComfyUI update available' + (version ? ' \u2192 ' + version : '');
  n.style.display = 'flex';
}

function hide_update_notice() {
  document.getElementById('update-notice').style.display = 'none';
}

function doUpdate() {
  pywebview.api.run_update();
}

function _saveTabsToDisk() {
  try {
    var f = document.getElementById('ui-frame');
    var out = { ls: {}, ss: {} };
    
    if (f && f.contentWindow && uiLoaded) {
      var w = f.contentWindow;
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

    if (Object.keys(out.ls).length > 0 || Object.keys(out.ss).length > 0) {
      pywebview.api.save_comfy_storage(JSON.stringify(out));
    }
  } catch(e) {}
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
        try { w.sessionStorage.setItem(key.slice(prefix_ss.length), localStorage.getItem(key)); hadData = true; } catch(e) {}
      }
      if (key && key.startsWith(prefix_ls)) {
        try { wls.setItem(key.slice(prefix_ls.length), localStorage.getItem(key)); hadData = true; } catch(e) {}
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
            try { wls.setItem(k, stored.ls[k]); } catch(e) {}
          });
        }
        if (stored.ss) {
          Object.keys(stored.ss).forEach(function(k) {
            try { wss.setItem(k, stored.ss[k]); } catch(e) {}
          });
        }
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
  cropStart = {x: e.clientX, y: e.clientY};
  shadeT.style.cssText = shadeB.style.cssText = shadeL.style.cssText = shadeR.style.cssText = "";
  document.getElementById('crop-hint').style.display = 'none';
});

overlay.addEventListener("mousemove", e => {
  if (!cropStart) return;
  const x = Math.min(e.clientX, cropStart.x);
  const y = Math.min(e.clientY, cropStart.y);
  const w = Math.abs(e.clientX - cropStart.x);
  const h = Math.abs(e.clientY - cropStart.y);
  cropSel.style.cssText = `left:${x}px;top:${y - OVERLAY_TOP}px;width:${w}px;height:${h}px;`;
  updateShades(x, y - OVERLAY_TOP, w, h);
});

overlay.addEventListener("mouseup", e => {
  if (!cropStart) return;
  const x = Math.min(e.clientX, cropStart.x);
  const y = Math.min(e.clientY, cropStart.y);
  const w = Math.abs(e.clientX - cropStart.x);
  const h = Math.abs(e.clientY - cropStart.y);
  cropStart = null;
  overlay.classList.remove("active");
  if (w > 5 && h > 5) {
    pywebview.api.screenshot(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
  } else {
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
        <div style="color:#00FF00;font-size:11px;margin-top:6px">${_eziDeob('Q29uZ3JhdHVsYXRpb25zIHRvIFBpeGFyb21hIG9uIHJlYWNoaW5nIDEwMCwwMDAgc3Vic2NyaWJlcnMg')}\uD83C\uDF89</div>
        <div style="color:#8b949e;font-size:11px;margin-top:6px">${_eziDeob('T25seSA5MDAsMDAwIGxlZnQgdW50aWwgdGhlIG5leHQgRWFzdGVyIGVnZyA=')}\uD83D\uDE0E</div>
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


function init_output_btn() {
  pywebview.api.check_output_folder().then(function(path) {
    if (path) document.getElementById('out-btn').classList.add('visible');
  });
}

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
</script>
</body>
</html>"""

def _get_shell_html():
    ico_css = ""
    ico_w, ico_h = 256, 256
    if os.path.exists(ICO_PATH):
        try:
            from PIL import Image
            import io
            with Image.open(ICO_PATH) as im:
                frames = []
                try:
                    for i in range(getattr(im, 'n_frames', 1)):
                        im.seek(i)
                        frames.append((im.size[0] * im.size[1], im.copy()))
                except EOFError:
                    pass
                best = max(frames, key=lambda x: x[0])[1] if frames else im
                ico_w, ico_h = best.size
                buf = io.BytesIO()
                best.convert("RGBA").save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode()
            ico_css = f'url("data:image/png;base64,{b64}")'
        except Exception:
            try:
                with open(ICO_PATH, "rb") as _f:
                    b64 = base64.b64encode(_f.read()).decode()
                ico_css = f'url("data:image/x-icon;base64,{b64}")'
            except Exception:
                pass
    return (SHELL_HTML
            .replace("{ICO_BG}", ico_css)
            .replace("{ICO_W}", str(ico_w))
            .replace("{ICO_H}", str(ico_h)))

async def make_proxy_app(comfy_port_holder, storage_holder):
    async def handle_shell(request):
        return web.Response(text=_get_shell_html(), content_type='text/html', charset='utf-8')
    
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
                    
                    if request.path == '/' and 'text/html' in resp.headers.get('Content-Type', '').lower():
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
    }})();
    </script>"""
                                html = body.decode('utf-8', errors='replace')
                                idx = html.lower().find('<head>')
                                if idx != -1:
                                    html = html[:idx+6] + inject_js + html[idx+6:]
                                else:
                                    html = inject_js + html
                                body = html.encode('utf-8')
                            except Exception:
                                pass

                    return web.Response(status=resp.status, headers=resp_hd, body=body)
        except: return web.Response(status=502)

    app = web.Application(client_max_size=1024*1024*1024)
    app.router.add_get('/__shell__', handle_shell)
    app.router.add_route('*', '/{path_info:.*}', handle_any)
    return app

class Api:
    _NO_WIN        = 0x08000000
    _NO_WIN_HIDDEN = 0x08000000 | 0x20000000
    PY_EXE         = os.path.join(ROOT_DIR, "python_embeded", "python.exe")
    COMFY_DIR      = os.path.join(ROOT_DIR, "ComfyUI")

    def __init__(self, proxy_port, comfy_port_holder, settings, storage_holder):
        self._window, self._proc = None, None
        self._settings = settings
        self._storage_holder = storage_holder
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
        self._proxy_port, self._comfy_port_holder = proxy_port, comfy_port_holder
        if sys.platform == "win32":
            hwnd = ctypes.WinDLL('kernel32').GetConsoleWindow()
            if hwnd: ctypes.WinDLL('user32').ShowWindow(hwnd, 0)

    def confirm_close(self):
        if not self._updating:
            self.save_window_state()
        self._confirm_close = True
        self._graceful_close()

    def modal_response(self, result, action):
        if not result:
            return
        if action == 'close':
            if not self._updating:
                self.save_window_state()
            self._confirm_close = True
            self._graceful_close()
        elif action == 'update':
            bat = os.path.join(ROOT_DIR, 'Update ComfyUI.bat')
            threading.Thread(target=self._do_update, args=(bat,), daemon=True).start()

    def _graceful_close(self):
        try:
            self._window.evaluate_js("_saveTabsToDisk();")
        except Exception:
            pass
        
        time.sleep(0.2)

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
        def _size_watcher():
            import time
            while self._window:
                try:
                    self.save_window_state()
                except Exception:
                    pass
                time.sleep(2)
        threading.Thread(target=_size_watcher, daemon=True).start()

    def set_title(self, suffix: str = ""):
        if self._window:
            try:
                t = f'ComfyUI-EZi-Desktop  v{APP_VERSION}'
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
        _set_window_icon(_get_hwnd(self._window))

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
                    if time.time() - restart_start_time > 60:
                        self._restarting = False
                        self._url_found = False
                        was_up = False
                        self._println(f"\n\033[91m⚠  Restart timed out. ComfyUI did not come back online.\033[0m")
                        self._safe_eval("switchToConsole('Stopped')")

    def _check_update(self):
        try:
            if not os.path.isdir(os.path.join(self.COMFY_DIR, '.git')):
                return
            subprocess.run(['git', 'fetch', '--quiet', '--tags'], cwd=self.COMFY_DIR, capture_output=True, timeout=15, creationflags=self._NO_WIN)
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
                    self._safe_eval(f"show_update({json.dumps(latest_tag)})")
        except Exception:
            pass

    def run_update(self):
        bat = os.path.join(ROOT_DIR, 'Update ComfyUI.bat')
        if not os.path.exists(bat):
            self._safe_eval(f"show_update_missing({json.dumps(ROOT_DIR)})")
            return
        self._safe_eval("show_update_confirm()")

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
                m_arg = re.search(r'python\.exe["\'"]?\s+(.*)', bat_content, re.IGNORECASE | re.DOTALL)
                if m_arg:
                    raw_str = m_arg.group(1)
                    raw_str = re.sub(r'\s*\^\s*\n\s*', ' ', raw_str)
                    raw_str = re.sub(r'[\n]+', ' ', raw_str).strip()
                    parsed = shlex.split(raw_str, posix=False)
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
        info = {}

        def _ps(cmd, timeout=8):
            return subprocess.run(
                ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', cmd],
                capture_output=True, timeout=timeout, creationflags=self._NO_WIN_HIDDEN
            )

        try:
            r = subprocess.run([self.PY_EXE, "--version"], capture_output=True, timeout=5, creationflags=self._NO_WIN)
            ver = r.stdout.decode(errors='replace').strip() or r.stderr.decode(errors='replace').strip()
            parts = ver.split()
            info['python'] = parts[1] if len(parts) > 1 else ver
        except Exception:
            info['python'] = 'N/A'

        try:
            r = subprocess.run(
                [self.PY_EXE, "-c", "import torch; v=torch.__version__.split('+')[0]; cv=torch.version.cuda or 'N/A'; print(v.rsplit('.',1)[0]+'|'+cv)"],
                capture_output=True, timeout=10, creationflags=self._NO_WIN
            )
            out = r.stdout.decode(errors='replace').strip()
            if '|' in out:
                torch_v, cuda_v = out.split('|', 1)
                info['torch'] = torch_v
                info['cuda'] = cuda_v
            else:
                info['torch'] = 'N/A'
                info['cuda'] = 'N/A'
        except Exception:
            info['torch'] = 'N/A'
            info['cuda'] = 'N/A'

        try:
            r = subprocess.run(
                ['git', 'describe', '--tags', '--exact-match', 'HEAD'],
                cwd=self.COMFY_DIR, capture_output=True, timeout=5, creationflags=self._NO_WIN
            )
            if r.returncode == 0:
                info['comfyui'] = r.stdout.decode(errors='replace').strip()
            else:
                r2 = subprocess.run(
                    ['git', 'describe', '--tags', '--abbrev=0', 'HEAD'],
                    cwd=self.COMFY_DIR, capture_output=True, timeout=5, creationflags=self._NO_WIN
                )
                info['comfyui'] = r2.stdout.decode(errors='replace').strip() or 'N/A'
        except Exception:
            info['comfyui'] = 'N/A'

        try:
            r = subprocess.run(
                [self.PY_EXE, "-c", "import importlib.metadata; print(importlib.metadata.version('comfyui-frontend-package'))"],
                capture_output=True, timeout=5, creationflags=self._NO_WIN
            )
            ver = r.stdout.decode(errors='replace').strip()
            info['frontend'] = ver if ver else 'N/A'
        except Exception:
            info['frontend'] = 'N/A'

        try:
            r = _ps('[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)')
            info['ram'] = r.stdout.decode(errors='replace').strip() + ' GB'
        except Exception:
            info['ram'] = 'N/A'

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
                try:
                    max_mb = int(max_mb.strip())
                    cur_mb = int(cur_mb.strip())
                    if max_mb == 0:
                        info['pagefile'] = f'Auto (current: {cur_mb} MB)'
                    else:
                        info['pagefile'] = f'{max_mb} MB (current: {cur_mb} MB)'
                except ValueError:
                    info['pagefile'] = 'N/A'
            else:
                info['pagefile'] = 'N/A'
        except Exception:
            info['pagefile'] = 'N/A'

        try:
            import shutil
            if shutil.which('nvidia-smi'):
                r = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'],
                                   capture_output=True, timeout=5, creationflags=self._NO_WIN)
                info['gpu'] = r.stdout.decode(errors='replace').strip() or 'N/A'
                r2 = _ps("$v = nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits; if ($v) { [math]::Round([decimal]$v / 1024) } else { 'N/A' }")
                vram = r2.stdout.decode(errors='replace').strip()
                info['vram'] = (vram + ' GB') if vram and vram != 'N/A' else 'N/A'

                r3 = subprocess.run(['nvidia-smi', '--query-gpu=driver_version', '--format=csv,noheader'],
                                    capture_output=True, timeout=5, creationflags=self._NO_WIN)
                info['driver'] = r3.stdout.decode(errors='replace').strip() or 'N/A'
            else:
                info['gpu'] = 'Not detected'
                info['vram'] = 'N/A'
                info['driver'] = 'N/A'
        except Exception:
            info['gpu'] = 'N/A'
            info['vram'] = 'N/A'
            info['driver'] = 'N/A'

        try:
            r = subprocess.run(
                ['reg', 'query', r'HKLM\SYSTEM\CurrentControlSet\Control\FileSystem', '/v', 'LongPathsEnabled'],
                capture_output=True, timeout=5, creationflags=self._NO_WIN
            )
            info['long_paths'] = '0x1' in r.stdout.decode(errors='replace')
        except Exception:
            info['long_paths'] = False

        return info

    def check_output_folder(self):
        path = self._resolve_output_dir()
        return path or ""

    def get_frontend_versions(self):
        import urllib.request as _ur, json as _json, importlib.metadata as _im
        try:
            current = _im.version('comfyui-frontend-package')
        except Exception:
            current = None
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
        return {'current': current, 'versions': versions}

    def get_comfyui_required_frontend(self, tag):
        import re as _re
        try:
            r = subprocess.run(
                ['git', 'show', f'tags/{tag}:requirements.txt'],
                cwd=self.COMFY_DIR, capture_output=True, timeout=5, creationflags=self._NO_WIN
            )
            if r.returncode != 0:
                return None
            for line in r.stdout.decode(errors='replace').splitlines():
                line = line.strip()
                if line.lower().startswith('comfyui-frontend-package'):
                    m = _re.search(r'==\s*([^\s]+)', line)
                    if m:
                        return m.group(1)
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
        return {'current': current, 'versions': all_tags}

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
        self._println(f"\033[93m=== Stopping ComfyUI ===\033[0m")
        self._kill_running_proc()
        self._println(f"\033[93m=== Running {name} ===\033[0m")
        try:
            proc = subprocess.Popen(
                ['cmd', '/c', bat, 'NoPause'],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
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
        self._println(f"\033[92m=== {name} finished. Restarting ComfyUI... ===\033[0m")
        time.sleep(1)
        if hide_update_notice:
            self._safe_eval("document.getElementById('update-notice').style.display='none';")
        self._safe_eval("switchToConsole()")
        self._updating = False
        self._restart_comfy()


    def open_output_folder(self):
        path = self._resolve_output_dir()
        if not path:
            return
        try:
            subprocess.Popen(['explorer', path])
        except Exception as e:
            self._println(f"[Output] Could not open folder: {e}\n")
            
    def open_url(self, url):
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

    def screenshot(self, x, y, w, h):
        threading.Thread(target=self._do_screenshot, args=(x, y, w, h), daemon=True).start()

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
            hwnd = _get_hwnd(self._window)
            if not hwnd:
                return

            import ctypes.wintypes as wt
            user = ctypes.windll.user32

            class WINDOWPLACEMENT(ctypes.Structure):
                _fields_ = [("length", wt.UINT), ("flags", wt.UINT), ("showCmd", wt.UINT),
                            ("ptMinPosition", wt.POINT), ("ptMaxPosition", wt.POINT),
                            ("rcNormalPosition", wt.RECT)]
            wp = WINDOWPLACEMENT()
            wp.length = ctypes.sizeof(WINDOWPLACEMENT)
            user.GetWindowPlacement(hwnd, ctypes.byref(wp))

            saved_state = {
                "showCmd": wp.showCmd,
                "rcNormalPosition": [wp.rcNormalPosition.left, wp.rcNormalPosition.top, 
                                     wp.rcNormalPosition.right, wp.rcNormalPosition.bottom]
            }

            if self._settings.get("window_placement") != saved_state:
                self._settings["window_placement"] = saved_state
                _save_settings(self._settings)
        except Exception:
            pass

    def save_comfy_storage(self, storage_json):
        try:
            data = json.loads(storage_json)
            self._settings["comfy_storage"] = data
            _save_settings(self._settings)
        except Exception:
            pass

    def get_ui_settings(self):
        try:
            hide = self._settings.get("hide_deprecation_warnings", True)
            return json.dumps({"hideDeprecationWarnings": hide})
        except Exception:
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
                _save_settings(self._settings)
        except Exception:
            pass

    def get_comfy_storage(self):
        return self._settings.get("comfy_storage", None)

    def stop(self):
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
            py_flags = []
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

                m = re.search(r'python\.exe["\']?\s+(.*)', bat_content, re.IGNORECASE | re.DOTALL)
                if m:
                    raw_str = m.group(1)
                    raw_str = re.sub(r'\s*\^\s*\n\s*', ' ', raw_str)
                    raw_str = re.sub(r'[\n]+', ' ', raw_str)
                    raw_str = raw_str.strip()
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

                    needs_val = ['--input-directory', '--output-directory', '--user-directory',
                                 '--port', '--extra-model-paths-config']
                    i = 0
                    while i < len(post_script):
                        arg = post_script[i]
                        if arg in needs_val:
                            if i + 1 < len(post_script) and not post_script[i+1].startswith('--'):
                                val = post_script[i+1].strip('"\'')
                                extra_args.extend([arg, val])
                                env_dirs.pop(arg, None)
                                i += 2
                            else: i += 1
                        elif arg.startswith('--'):
                            if "auto-launch" not in arg: extra_args.append(arg)
                            i += 1
                        else: i += 1

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
            self._proc = subprocess.Popen(
                [self.PY_EXE] + final_args,
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
                    line = buf.decode('utf-8', errors='replace')
                    buf.clear()
                    if line:
                        prev_cr_line = line
                        self._print(line + '\r')
                elif chunk == b'\n':
                    line = buf.decode('utf-8', errors='replace')
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

    def _print(self, text):
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
    
    settings = _load_settings()
    p_port = find_free_port()
    c_port_h = [COMFY_PORT]
    storage_holder = [settings.get("comfy_storage")]

    loop = asyncio.new_event_loop()
    def start_proxy():
        asyncio.set_event_loop(loop)
        web.run_app(make_proxy_app(c_port_h, storage_holder), host='127.0.0.1', port=p_port, print=None)

    threading.Thread(target=start_proxy, daemon=True).start()

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

    api = Api(p_port, c_port_h, settings, storage_holder)
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
                api._window.evaluate_js("""
                    (function() {
                        try {
                            var mo = document.getElementById('modal-overlay');
                            if (mo) mo.classList.remove('active');
                            var co = document.getElementById('crop-overlay');
                            if (co) co.classList.remove('active');
                        } catch(e) {}
                        try {
                            var w = document.getElementById('ui-frame').contentWindow;
                            if (!w || !w.app || !w.app.extensionManager || !w.app.extensionManager.dialog) {
                                pywebview.api.confirm_close();
                                return;
                            }
                            if (!showingUI) toggle();
                            w.app.extensionManager.dialog.confirm({
                                title: 'Close ComfyUI?',
                                message: 'ComfyUI will be stopped and the window will close.'
                            }).then(function(ok) {
                                if (ok) pywebview.api.confirm_close();
                            });
                        } catch(e) { pywebview.api.confirm_close(); }
                    })();
                """)
            except Exception:
                api._confirm_close = True
                try: api._window.destroy()
                except Exception: pass
        threading.Thread(target=_ask, daemon=True).start()
        return False
    window.events.closing += _on_closing

    def _restore_on_shown():
        try:
            hwnd = _get_hwnd(window)
            if not hwnd:
                return
            
            wp_data = settings.get("window_placement")
            if not wp_data or not isinstance(wp_data, dict):
                return

            import ctypes.wintypes as wt
            user = ctypes.windll.user32

            class WINDOWPLACEMENT(ctypes.Structure):
                _fields_ = [("length", wt.UINT), ("flags", wt.UINT), ("showCmd", wt.UINT),
                            ("ptMinPosition", wt.POINT), ("ptMaxPosition", wt.POINT),
                            ("rcNormalPosition", wt.RECT)]

            wp = WINDOWPLACEMENT()
            wp.length = ctypes.sizeof(WINDOWPLACEMENT)
            
            show_cmd = wp_data.get("showCmd", 1)
            wp.showCmd = 3 if show_cmd == 3 else 1
            
            rc_data = wp_data.get("rcNormalPosition")
            if rc_data and len(rc_data) == 4:
                wp.rcNormalPosition = wt.RECT(rc_data[0], rc_data[1], rc_data[2], rc_data[3])
            else:
                return

            user.SetWindowPlacement(hwnd, ctypes.byref(wp))
        except Exception:
            pass

    window.events.shown += _restore_on_shown

    webview.start()