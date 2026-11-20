"""try_client.py [CALL...] - talks to server.py over stdio as an MCP client would. Each CALL is TOOL or
TOOL=JSON_ARGS; screenshots are saved next to this file as shot-N.jpg."""
import base64, json, os, subprocess, sys

here = os.path.dirname(os.path.abspath(__file__))
p = subprocess.Popen([sys.executable, '-I', os.path.join(here, 'server.py')], stdin=subprocess.PIPE,
                     stdout=subprocess.PIPE, text=True)


def call(i, method, params):
    p.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': i, 'method': method, 'params': params}) + '\n')
    p.stdin.flush()
    return json.loads(p.stdout.readline())


print(call(1, 'initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 't'}})['result']['serverInfo'])
p.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n')
print([t['name'] for t in call(2, 'tools/list', {})['result']['tools']])
shots = 0
for n, arg in enumerate(sys.argv[1:], 3):
    name, _, js = arg.partition('=')
    res = call(n, 'tools/call', {'name': name, 'arguments': json.loads(js) if js else {}})
    for c in res.get('result', {}).get('content', []):
        if c['type'] == 'image':
            shots += 1
            path = os.path.join(here, f'shot-{shots}.jpg')
            open(path, 'wb').write(base64.b64decode(c['data']))
            print(name, '-> image', path)
        else:
            print(name, '->', c['text'][:600])
    if 'error' in res:
        print(name, 'ERROR', res['error'])
p.stdin.close()
p.wait()
