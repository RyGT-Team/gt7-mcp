"""gt7-mcp: a small MCP server (stdio, JSON-RPC, no dependencies beyond Pillow) to drive GT7 in the shared
GT Sport/GT7 folder: launch it with the RyGT launcher's settings, look at it, press its buttons, read its log.

Input goes to the game window as keyboard keys, through the bindings in user\\input_config\\default.ini (the
runtime maps them to the PS4 pad). The window is brought to the front first; keys are sent with SendInput as
scan codes. Screenshots grab the window's area of the screen (it must not be minimised or covered).
"""
import base64
import ctypes
import io
import json
import os
import re
import subprocess
import sys
import time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
# The shared GT Sport/GT7 game folder: GT7_ROOT, else the folder next to this repository's.
ROOT = os.environ.get('GT7_ROOT') or os.path.join(os.path.dirname(HERE), 'GTSport-Ryty-shadGT-2026-10-16-4')
LAUNCH = os.environ.get('GT7_LAUNCH') or os.path.join(HERE, 'launch', 'gt7-direct.ps1')
LOGS = os.path.join(ROOT, 'logs', 'CUSA24769')
INI = os.path.join(ROOT, 'user', 'input_config', 'default.ini')
EXE = 'GT7.exe'

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # real pixel coordinates for the window rectangle
except Exception:
    pass

# ---------------------------------------------------------------------------------------------- windows


def gt7_pids():
    out = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {EXE}', '/FO', 'CSV', '/NH'],
                         capture_output=True, text=True).stdout
    return [int(m) for m in re.findall(r'"' + re.escape(EXE) + r'","(\d+)"', out)]


EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def gt7_window():
    pids = set(gt7_pids())
    if not pids:
        return None
    found = []

    def cb(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(hwnd):
            r = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(r))
            if r.right - r.left >= 320:
                found.append((r.right * r.bottom, hwnd))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return max(found)[1] if found else None


def bring_to_front(hwnd):
    SW_RESTORE = 9
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    fg = user32.GetForegroundWindow()
    if fg == hwnd:
        return True
    cur = kernel32.GetCurrentThreadId()
    fg_thread = user32.GetWindowThreadProcessId(fg, None)
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    user32.AttachThreadInput(cur, fg_thread, True)
    user32.AttachThreadInput(cur, target_thread, True)
    # An Alt tap lets this process take the foreground (Windows refuses SetForegroundWindow otherwise).
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(cur, fg_thread, False)
    user32.AttachThreadInput(cur, target_thread, False)
    time.sleep(0.15)
    return user32.GetForegroundWindow() == hwnd


def client_rect_on_screen(hwnd):
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, pt.x + r.right, pt.y + r.bottom

# ---------------------------------------------------------------------------------------------- keys


VK = {'enter': 0x0D, 'space': 0x20, 'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27,
      'escape': 0x1B, 'tab': 0x09, 'backspace': 0x08,
      'kp0': 0x60, 'kp1': 0x61, 'kp2': 0x62, 'kp3': 0x63, 'kp4': 0x64, 'kp5': 0x65, 'kp6': 0x66,
      'kp7': 0x67, 'kp8': 0x68, 'kp9': 0x69}
EXTENDED = {0x25, 0x26, 0x27, 0x28}


def key_vk(name):
    name = name.lower()
    if name in VK:
        return VK[name]
    if len(name) == 1 and name.isalnum():
        return ord(name.upper())
    raise ValueError(f'no key code for {name!r}')


def load_bindings():
    """button -> keyboard key, from the keyboard part of default.ini (the last binding of a button wins)."""
    binds = {}
    try:
        text = open(INI, encoding='utf-8', errors='replace').read()
    except OSError:
        text = ''
    keyboard = text.split('# Controller bindings')[0]
    for line in keyboard.splitlines():
        m = re.match(r'\s*([a-z0-9_]+)\s*=\s*(\S+)', line)
        if m:
            binds[m[1]] = m[2]
    return binds


BUTTON_ALIASES = {'x': 'cross', 'o': 'circle', 'start': 'options', 'up': 'pad_up', 'down': 'pad_down',
                  'left': 'pad_left', 'right': 'pad_right', 'touchpad': 'touchpad_center',
                  'throttle': 'r2', 'brake': 'l2', 'steer_left': 'axis_left_x_minus',
                  'steer_right': 'axis_left_x_plus', 'stick_up': 'axis_left_y_minus',
                  'stick_down': 'axis_left_y_plus'}


def button_key(button):
    b = BUTTON_ALIASES.get(button.lower(), button.lower())
    binds = load_bindings()
    if b not in binds:
        raise ValueError(f'unknown button {button!r}; known: {sorted(set(binds) | set(BUTTON_ALIASES))}')
    return key_vk(binds[b])


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD), ('dwFlags', wintypes.DWORD),
                ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [('ki', KEYBDINPUT), ('pad', ctypes.c_byte * 32)]
    _anonymous_ = ('u',)
    _fields_ = [('type', wintypes.DWORD), ('u', _U)]


def send_key(vk, up):
    KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 1, 2, 8
    scan = user32.MapVirtualKeyW(vk, 0)
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED else 0)
    inp = INPUT(type=1)
    inp.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def press(vks, hold_ms):
    for vk in vks:
        send_key(vk, False)
    time.sleep(hold_ms / 1000)
    for vk in reversed(vks):
        send_key(vk, True)

# ---------------------------------------------------------------------------------------------- logs


def log_tail(name, pattern=None, last=20):
    path = os.path.join(LOGS, name)
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            lines = f.read().splitlines()
    except OSError as e:
        return [f'({path}: {e})']
    if pattern:
        rx = re.compile(pattern)
        lines = [l for l in lines if rx.search(l)]
    return [l[:400] for l in lines[-last:]]


def race_state():
    lines = log_tail('stderr.log', r'GAME-00[26]', 3)
    return lines[-1] if lines else '(no race state line yet)'

# ---------------------------------------------------------------------------------------------- tools


def tool_status(_):
    pids = gt7_pids()
    hwnd = gt7_window()
    fg = user32.GetForegroundWindow()
    return [text(json.dumps({'running': bool(pids), 'pids': pids, 'window': bool(hwnd),
                             'window_in_front': bool(hwnd) and hwnd == fg,
                             'race_state': race_state()}, indent=1))]


def tool_screenshot(args):
    from PIL import ImageGrab
    hwnd = gt7_window()
    if not hwnd:
        return [text('GT7 is not running (no window).')]
    bring_to_front(hwnd)
    box = client_rect_on_screen(hwnd)
    img = ImageGrab.grab(bbox=box, all_screens=True)
    width = int(args.get('width', 960))
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)))
    buf = io.BytesIO()
    img.convert('RGB').save(buf, format='JPEG', quality=80)
    return [{'type': 'image', 'data': base64.b64encode(buf.getvalue()).decode(), 'mimeType': 'image/jpeg'},
            text(f'window {box[2] - box[0]}x{box[3] - box[1]}; {race_state()}')]


def grab_frame(width):
    from PIL import ImageGrab
    hwnd = gt7_window()
    if not hwnd:
        return None
    img = ImageGrab.grab(bbox=client_rect_on_screen(hwnd), all_screens=True).convert('RGB')
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)))
    return img


def tool_clip(args):
    """Several frames over a short time, tiled into one image (MCP has no streaming results)."""
    from PIL import Image, ImageDraw
    hwnd = gt7_window()
    if not hwnd:
        return [text('GT7 is not running (no window).')]
    bring_to_front(hwnd)
    frames = max(2, min(12, int(args.get('frames', 6))))
    interval = max(50, min(5000, int(args.get('interval_ms', 500))))
    width = max(160, min(960, int(args.get('frame_width', 480))))
    shots = []
    start = time.time()
    for i in range(frames):
        img = grab_frame(width)
        if img is None:
            break
        ImageDraw.Draw(img).text((6, 4), f'{time.time() - start:.1f}s', fill=(255, 255, 0))
        shots.append(img)
        time.sleep(interval / 1000)
    cols = 3 if len(shots) > 4 else 2
    rows = (len(shots) + cols - 1) // cols
    w, h = shots[0].size
    sheet = Image.new('RGB', (cols * w, rows * h))
    for i, img in enumerate(shots):
        sheet.paste(img, ((i % cols) * w, (i // cols) * h))
    buf = io.BytesIO()
    sheet.save(buf, format='JPEG', quality=75)
    return [{'type': 'image', 'data': base64.b64encode(buf.getvalue()).decode(), 'mimeType': 'image/jpeg'},
            text(f'{len(shots)} frames, {interval} ms apart, left to right then down; {race_state()}')]


STREAM = {'server': None, 'port': None}


def tool_stream(args):
    """A live MJPEG view of the window for a browser on this PC (localhost only)."""
    import http.server
    import threading
    if args.get('stop'):
        if STREAM['server']:
            STREAM['server'].shutdown()
            STREAM['server'] = None
        return [text('stream stopped')]
    if STREAM['server']:
        return [text(f'already streaming at http://127.0.0.1:{STREAM["port"]}/')]
    fps = max(1, min(30, int(args.get('fps', 10))))
    width = max(320, min(1920, int(args.get('width', 960))))
    port = int(args.get('port', 8765))

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path != '/':
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            self.end_headers()
            try:
                while STREAM['server']:
                    img = grab_frame(width)
                    if img is not None:
                        buf = io.BytesIO()
                        img.save(buf, format='JPEG', quality=70)
                        self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' +
                                         str(buf.tell()).encode() + b'\r\n\r\n' + buf.getvalue() + b'\r\n')
                    time.sleep(1 / fps)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    srv = http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler)
    srv.daemon_threads = True
    STREAM.update(server=srv, port=port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return [text(f'streaming the GT7 window at http://127.0.0.1:{port}/ ({fps} fps, {width} px wide); '
                 'the window must stay uncovered. gt7_stream with stop=true ends it.')]


def tool_press(args):
    hwnd = gt7_window()
    if not hwnd:
        return [text('GT7 is not running (no window).')]
    front = bring_to_front(hwnd)
    buttons = args['buttons'] if isinstance(args.get('buttons'), list) else [args.get('button', 'cross')]
    vks = [button_key(b) for b in buttons]
    times = max(1, min(50, int(args.get('times', 1))))
    hold = max(20, min(30000, int(args.get('hold_ms', 100))))
    gap = max(0, min(10000, int(args.get('gap_ms', 250))))
    for i in range(times):
        press(vks, hold)
        if i + 1 < times:
            time.sleep(gap / 1000)
    time.sleep(float(args.get('settle_ms', 300)) / 1000)
    return [text(f'pressed {"+".join(buttons)} x{times} ({hold} ms each)'
                 f'{"" if front else "; WARNING: the game window did not come to the front"}')]


def tool_launch(args):
    if gt7_pids():
        return [text('GT7 is already running; close it first (gt7_close).')]
    env = dict(os.environ, GT7_ROOT=ROOT)
    switches = args.get('switches') or {}
    script = open(LAUNCH, encoding='utf-8-sig').read()
    extra = ''.join(f"$env:{k} = '{v}'\n" for k, v in switches.items()
                    if re.fullmatch(r'[A-Z0-9_]+', k) and re.fullmatch(r'[^\'\r\n]*', str(v)))
    script = script.replace('Set-Location $root', extra + 'Set-Location $root')
    tmp = os.path.join(os.environ.get('TEMP', '.'), 'gt7-mcp-launch.ps1')
    open(tmp, 'w', encoding='utf-8').write(script)
    subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', tmp], env=env,
                   capture_output=True, timeout=60)
    for _ in range(30):
        if gt7_window():
            break
        time.sleep(1)
    return [text(f'launched; running={bool(gt7_pids())}, window={bool(gt7_window())}; switches {switches or "none"}')]


def tool_close(_):
    pids = gt7_pids()
    for pid in pids:
        subprocess.run(['taskkill', '/PID', str(pid)], capture_output=True)
    for _ in range(20):
        if not gt7_pids():
            break
        time.sleep(0.5)
    left = gt7_pids()
    for pid in left:
        subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True)
    return [text(f'closed {pids}' + (f' (forced {left})' if left else ''))]


def tool_log(args):
    name = 'stdout.log' if args.get('file', 'stderr') == 'stdout' else 'stderr.log'
    return [text('\n'.join(log_tail(name, args.get('pattern'), int(args.get('last', 30)))))]


def text(s):
    return {'type': 'text', 'text': s}


BUTTONS_DOC = ('cross (x), circle (o), triangle, square, options (start), up, down, left, right, l1, r1, l2 (brake), '
               'r2 (throttle), l3, r3, touchpad, steer_left, steer_right, stick_up, stick_down')
TOOLS = {
    'gt7_status': (tool_status, 'Whether GT7 runs, whether its window is in front, and its last race-state line.',
                   {'type': 'object', 'properties': {}}),
    'gt7_screenshot': (tool_screenshot, 'A JPEG of the GT7 window (brought to the front first) and its race state.',
                       {'type': 'object', 'properties': {'width': {'type': 'integer', 'description': 'width to scale to (default 960)'}}}),
    'gt7_clip': (tool_clip, 'A short clip of the GT7 window: several frames over time tiled into one image, '
                 'with each frame time printed in its corner.',
                 {'type': 'object', 'properties': {
                     'frames': {'type': 'integer', 'description': '2-12 (default 6)'},
                     'interval_ms': {'type': 'integer', 'description': 'time between frames (default 500)'},
                     'frame_width': {'type': 'integer', 'description': 'width of each frame (default 480)'}}}),
    'gt7_stream': (tool_stream, 'Start (or stop with stop=true) a live MJPEG view of the GT7 window for a browser '
                   'on this PC at http://127.0.0.1:PORT/ (localhost only).',
                   {'type': 'object', 'properties': {'fps': {'type': 'integer'}, 'width': {'type': 'integer'},
                                                     'port': {'type': 'integer'}, 'stop': {'type': 'boolean'}}}),
    'gt7_press': (tool_press, 'Press GT7 pad buttons (sent as the keyboard keys default.ini binds to them). '
                  'Several buttons are held together. Buttons: ' + BUTTONS_DOC + '.',
                  {'type': 'object', 'properties': {
                      'buttons': {'type': 'array', 'items': {'type': 'string'}},
                      'times': {'type': 'integer', 'description': 'presses (default 1)'},
                      'hold_ms': {'type': 'integer', 'description': 'how long each press is held (default 100; up to 30000 to drive)'},
                      'gap_ms': {'type': 'integer', 'description': 'pause between presses (default 250)'},
                      'settle_ms': {'type': 'integer', 'description': 'wait after the last press (default 300)'}},
                   'required': ['buttons']}),
    'gt7_launch': (tool_launch, "Start GT7.exe with the RyGT launcher's settings (gt7-direct.ps1: PS4 Pro mode 1080p, "
                   'in-place ranges); optional extra environment switches.',
                   {'type': 'object', 'properties': {'switches': {'type': 'object', 'additionalProperties': {'type': 'string'}}}}),
    'gt7_close': (tool_close, 'Close GT7 (asks first, then forces it after 10 s).', {'type': 'object', 'properties': {}}),
    'gt7_log': (tool_log, "Lines of GT7's stderr.log (default) or stdout.log, optionally filtered by a regex.",
                {'type': 'object', 'properties': {'file': {'type': 'string', 'enum': ['stderr', 'stdout']},
                                                  'pattern': {'type': 'string'}, 'last': {'type': 'integer'}}}),
}

# ---------------------------------------------------------------------------------------------- JSON-RPC


def reply(msg_id, result=None, error=None):
    out = {'jsonrpc': '2.0', 'id': msg_id}
    if error is not None:
        out['error'] = error
    else:
        out['result'] = result
    sys.stdout.write(json.dumps(out) + '\n')
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method, msg_id, params = msg.get('method'), msg.get('id'), msg.get('params') or {}
        if msg_id is None:
            continue  # notifications (initialized, cancelled)
        if method == 'initialize':
            reply(msg_id, {'protocolVersion': params.get('protocolVersion', '2025-06-18'),
                           'capabilities': {'tools': {}},
                           'serverInfo': {'name': 'gt7', 'version': '0.1.0'}})
        elif method == 'tools/list':
            reply(msg_id, {'tools': [{'name': n, 'description': d, 'inputSchema': s} for n, (_, d, s) in TOOLS.items()]})
        elif method == 'tools/call':
            name = params.get('name')
            if name not in TOOLS:
                reply(msg_id, error={'code': -32602, 'message': f'unknown tool {name}'})
                continue
            try:
                content = TOOLS[name][0](params.get('arguments') or {})
                reply(msg_id, {'content': content})
            except Exception as e:  # report to the caller rather than dying
                reply(msg_id, {'content': [text(f'{type(e).__name__}: {e}')], 'isError': True})
        elif method == 'ping':
            reply(msg_id, {})
        else:
            reply(msg_id, error={'code': -32601, 'message': f'unknown method {method}'})


if __name__ == '__main__':
    main()
