"""gt7-drive.py SECONDS [--out TRACE] [--ref REF] [--alat 9]

Drives GT7 by feel from the [haptics] telemetry lines the renderer writes to stderr.log with
SHADGT_HAPTICS_LOG=<n> (DIAG-SGT-050 builds add position/heading; 6 = about 10 lines a second).

- Throttle held; shifts up at 92% of the rev limit, down below 50% (cross / square; the car is MT).
- Without --ref it only drives straight, shifts and unsticks (steering blind), and records its path.
- With --ref (a previous TRACE, or several joined): pure pursuit on that line. Heading comes from the
  change in position; which way the left key turns is calibrated with one pulse at the start.
  Speed target from the line's curvature ahead: v = sqrt(alat * radius); brakes above it.
TRACE lines: t x y z speed gear knock
"""
import argparse, math, os, re, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import server  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('seconds', type=float)
ap.add_argument('--out')
ap.add_argument('--ref')
ap.add_argument('--alat', type=float, default=9.0)
ap.add_argument('--log', help='human-readable log (default stdout)')
a = ap.parse_args()
say = open(a.log, 'w') if a.log else sys.stdout
trace = open(a.out, 'w') if a.out else None

RX = re.compile(r'\[haptics\] dt [\d.]+ speed ([\d.]+) rpm (\d+)/(\d+) gear (\d+) thr (\d+).*?accel ([\d.]+)'
                r' \| knock ([\d.]+)/([\d.]+)(?:.*?\| pos (\S+) (\S+) (\S+) rot \S+ \S+ \S+ north (\S+) lap (-?\d+))?')
K = {b: server.button_key(b) for b in ('r2', 'l2', 'cross', 'square', 'steer_left', 'steer_right')}


def load_ref(path):
    pts = []
    for line in open(path):
        f = line.split()
        if len(f) >= 5 and float(f[4]) > 5:
            pts.append((float(f[1]), float(f[3])))
    # resample every 2 m, then smooth
    out = [pts[0]]
    for p in pts[1:]:
        if math.dist(p, out[-1]) >= 2:
            out.append(p)
    sm = []
    for i in range(len(out)):
        w = out[max(0, i - 3):i + 4]
        sm.append((sum(p[0] for p in w) / len(w), sum(p[1] for p in w) / len(w)))
    return sm


ref = load_ref(a.ref) if a.ref else None


def nearest(p, hint):
    if hint is None:
        rng = range(len(ref))
    else:
        rng = [(hint + d) % len(ref) for d in range(-20, 120)]
    return min(rng, key=lambda i: math.dist(ref[i], p))


def radius_at(i):
    a_, b_, c_ = ref[i], ref[(i + 8) % len(ref)], ref[(i + 16) % len(ref)]
    ab, bc, ca = math.dist(a_, b_), math.dist(b_, c_), math.dist(c_, a_)
    area2 = abs((b_[0] - a_[0]) * (c_[1] - a_[1]) - (b_[1] - a_[1]) * (c_[0] - a_[0]))
    return 1e9 if area2 < 1e-6 else ab * bc * ca / (2 * area2)


hwnd = server.gt7_window()
if not hwnd:
    sys.exit('no GT7 window')
server.bring_to_front(hwnd)
f = open(os.path.join(server.LOGS, 'stderr.log'), encoding='utf-8', errors='replace')
f.seek(0, 2)
buf = ''
start = last_shift = last_front = time.time()
slow_since = None
side = 0
prev = None            # previous (x, z)
heading = None
left_sign = None       # +1 if steer_left increases atan2 heading, -1 if it decreases
calib = None           # (heading before, time) during calibration
hint = None
stats = dict(samples=0, up=0, down=0, unstick=0, brakes=0)
speeds = []
server.send_key(K['r2'], False)
throttle_on = True
try:
    while time.time() - start < a.seconds:
        now = time.time()
        if now - last_front > 1.0:
            if server.user32.GetForegroundWindow() != hwnd:
                server.bring_to_front(hwnd)
            if throttle_on:
                server.send_key(K['r2'], False)
            last_front = now
        buf += f.read()
        lines = buf.split('\n')
        buf = lines.pop()
        for line in lines:
            m = RX.search(line)
            if not m:
                continue
            speed, rpm, limit, gear = float(m[1]), int(m[2]), int(m[3]), int(m[4])
            knock = max(float(m[7]), float(m[8]))
            pos = (float(m[9]), float(m[11])) if m[9] else None
            stats['samples'] += 1
            speeds.append(speed)
            act = []
            if trace and pos:
                print(f'{now - start:.2f} {m[9]} {m[10]} {m[11]} {speed:.1f} {gear} {knock:.2f}', file=trace, flush=True)
            if pos and prev and math.dist(pos, prev) > 0.5:
                heading = math.atan2(pos[1] - prev[1], pos[0] - prev[0])
            if pos:
                prev = pos
            # shifting
            if now - last_shift > 0.5 and limit:
                if rpm > 0.92 * limit:
                    server.press([K['cross']], 60); stats['up'] += 1; last_shift = now; act.append('UP')
                elif rpm < 0.50 * limit and gear > 2:
                    server.press([K['square']], 60); stats['down'] += 1; last_shift = now; act.append('DOWN')
            steer_ms = 0; steer_key = None
            if ref and pos and heading is not None and speed > 8:
                if left_sign is None and calib is None and now - start > 3:
                    calib = (heading, now)
                    server.press([K['steer_left']], 250)
                    act.append('CALIB')
                elif calib and left_sign is None and now - calib[1] > 0.4:
                    d = math.remainder(heading - calib[0], 2 * math.pi)
                    left_sign = 1 if d > 0 else -1
                    act.append(f'left={left_sign:+d} ({d:+.3f})')
                elif left_sign is not None:
                    hint = nearest(pos, hint)
                    look = max(12.0, min(70.0, speed * 0.9))
                    j = (hint + int(look / 2)) % len(ref)
                    tgt = ref[j]
                    want = math.atan2(tgt[1] - pos[1], tgt[0] - pos[0])
                    err = math.remainder(want - heading, 2 * math.pi)  # + = target to the +heading side
                    steer_left = (err > 0) == (left_sign > 0)
                    steer_ms = int(min(90, abs(err) * 300))
                    if steer_ms >= 10:
                        steer_key = K['steer_left' if steer_left else 'steer_right']
                    r = min(radius_at((hint + k) % len(ref)) for k in range(0, max(1, int(speed * 1.5 / 2)), 4))
                    vmax = math.sqrt(a.alat * r)
                    if speed > vmax + 2:
                        server.send_key(K['r2'], True); throttle_on = False
                        server.press([K['l2']], 90); stats['brakes'] += 1; act.append(f'BRAKE v>{vmax:.0f}')
                    elif not throttle_on:
                        server.send_key(K['r2'], False); throttle_on = True
                    act.append(f'off {math.dist(ref[hint], pos):.1f}m err {math.degrees(err):+.0f}')
            if steer_key:
                server.press([steer_key], steer_ms)
            if speed < 3:
                slow_since = slow_since or now
                if now - slow_since > 2:
                    server.send_key(K['r2'], True)
                    steer = K['steer_left' if side % 2 == 0 else 'steer_right']
                    server.press([steer, K['r2']], 1500)
                    server.send_key(K['r2'], False); throttle_on = True
                    side += 1; stats['unstick'] += 1; slow_since = None; act.append('UNSTICK')
            else:
                slow_since = None
            p = f'pos {pos[0]:8.1f} {pos[1]:8.1f}' if pos else ''
            print(f'{now - start:6.1f}s v {speed:5.1f} rpm {rpm:5d}/{limit} g{gear} knock {knock:.2f} {p} '
                  f'{" ".join(act)}', file=say, flush=True)
        time.sleep(0.02)
finally:
    server.send_key(K['r2'], True)
    if speeds:
        s = sorted(speeds)
        print(f'summary: speed median {s[len(s) // 2]:.1f} m/s max {s[-1]:.1f}; {stats}', file=say, flush=True)
