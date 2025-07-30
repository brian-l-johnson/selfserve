import json
import re

#COMPACT_RE = re.compile(r'^\d+:\d+:[A-Z0-9]+:\d+:\d+(;\d+:\d+)*(?::\d+)?$')
COMPACT_RE = re.compile(r'^\d+:\d+:[A-Z0-9]+:\d+:\d+(;\d+:\d+)*(?::[A-Z]+-\d+)?$')
ESCAPE_RE = re.compile(r'%[0-6]')
entries = [(char, f'%{i}') for i, char in enumerate(['{', '}', '[', ']', ':', ',', '"'])]
unescape_map = {v: k for k, v in entries}

def unescape_json(s):
    return ESCAPE_RE.sub(lambda m: unescape_map[m.group(0)], s)

def is_compact(s):
    return COMPACT_RE.fullmatch(s) is not None

def is_escaped(s):
    return ESCAPE_RE.search(s) is not None

def decode_compact(s):
    parts = s.split(':')
    version = parts[0]
    if version != '1':
        raise ValueError("Unsupported version")
    cc = int(parts[1])
    p = parts[2]
    rest = parts[3:]
    print(rest)
    # Find the last semicolon, which separates items from optional txn
    joined = ':'.join(rest)
    print(joined)

    items = joined.split(";")
    txn_part = ""
    if len(items[-1].split(":")) == 3:
        last = items.pop()
        lastsplit = last.split(":")
        items.append(f"{lastsplit[0]}:{lastsplit[1]}")
        txn_part = lastsplit[2]

    i = []
    print(items)
    for pair in items:
        print(f"pair: {pair}")
        if pair:
            v, q = map(int, pair.split(':'))
            i.append({'v': v, 'q': q})
    order = {'cc': cc, 'p': p, 'i': i}
    order['txn'] = txn_part
    return order

# Decoder: auto-detect format
def decode(s):
    # Try compact first
    print("in decode")
    print("checking if is_compact")
    if is_compact(s):
        try:
            return decode_compact(s)
        except Exception as e:
            print("is not compact")
            print(e)
            pass
    # Try unescaping JSON
    print("checking if is_escaped")
    if is_escaped(s):
        try:
            return json.loads(unescape_json(s))
        except Exception:
            pass
    # Try raw JSON
    print("checking if is json")
    try:
        return json.loads(s)
    except Exception:
        pass
    raise ValueError("Unable to decode input") 