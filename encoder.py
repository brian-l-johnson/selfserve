import json
import re

ESCAPE_CHAR = '%'
STRUCT_CHARS = ['{', '}', '[', ']', ':', ',', '"']
STRUCT_RE = re.compile(r'[{}\[\]:,\"]')
entries = [(char, f'{ESCAPE_CHAR}{i}') for i, char in enumerate(STRUCT_CHARS)]
escape_map = dict(entries)

def escape_json(s):
    return STRUCT_RE.sub(lambda m: escape_map[m.group(0)], s)

def is_escapable(s):
    # Only allow alphanumeric and a few special chars after escaping
    escaped = escape_json(s)
    return re.fullmatch(r'[0-9A-Z $%*+\-./:]*', escaped) is not None

def encode_compact(order):
    version = 1
    cc = order.get('cc')
    p = order.get('p')
    if isinstance(p, str):
        p = p.upper()
    i = order.get('i')
    txn = order.get('txn')
    if not isinstance(i, list):
        raise ValueError("Invalid order structure")
    if not i:  # Empty items list
        raise ValueError("Compact format requires at least one item")
    items = ';'.join(f"{item['v']}:{item['q']}" for item in i)
    compact = f"{version}:{cc}:{p}:{items}"
    if txn is not None:
        compact += f":{txn}"
    return compact

# Encoder: automatic tier selection
def encode(input_):
    parsed = input_
    if isinstance(input_, str):
        try:
            parsed = json.loads(input_)
        except Exception:
            pass  # malformed input
    try:
        if (
            isinstance(parsed, dict) and
            isinstance(parsed.get('cc'), int) and
            isinstance(parsed.get('p'), str) and
            isinstance(parsed.get('i'), list) and
            all(isinstance(e.get('v'), int) and isinstance(e.get('q'), int) for e in parsed['i'])
        ):
            return encode_compact(parsed)  # Tier 1
        minified = json.dumps(parsed, separators=(',', ':'))
        escaped = escape_json(minified)
        if is_escapable(escaped):
            return escaped  # Tier 2
        return minified  # Tier 3
    except Exception:
        return input_ if isinstance(input_, str) else json.dumps(input_) 