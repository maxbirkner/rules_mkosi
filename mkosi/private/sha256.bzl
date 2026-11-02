"""SHA-256 for repository rules, which have no built-in content hash function."""

_MASK = 0xffffffff

_ROUND_CONSTANTS = [
    0x428a2f98,
    0x71374491,
    0xb5c0fbcf,
    0xe9b5dba5,
    0x3956c25b,
    0x59f111f1,
    0x923f82a4,
    0xab1c5ed5,
    0xd807aa98,
    0x12835b01,
    0x243185be,
    0x550c7dc3,
    0x72be5d74,
    0x80deb1fe,
    0x9bdc06a7,
    0xc19bf174,
    0xe49b69c1,
    0xefbe4786,
    0x0fc19dc6,
    0x240ca1cc,
    0x2de92c6f,
    0x4a7484aa,
    0x5cb0a9dc,
    0x76f988da,
    0x983e5152,
    0xa831c66d,
    0xb00327c8,
    0xbf597fc7,
    0xc6e00bf3,
    0xd5a79147,
    0x06ca6351,
    0x14292967,
    0x27b70a85,
    0x2e1b2138,
    0x4d2c6dfc,
    0x53380d13,
    0x650a7354,
    0x766a0abb,
    0x81c2c92e,
    0x92722c85,
    0xa2bfe8a1,
    0xa81a664b,
    0xc24b8b70,
    0xc76c51a3,
    0xd192e819,
    0xd6990624,
    0xf40e3585,
    0x106aa070,
    0x19a4c116,
    0x1e376c08,
    0x2748774c,
    0x34b0bcb5,
    0x391c0cb3,
    0x4ed8aa4a,
    0x5b9cca4f,
    0x682e6ff3,
    0x748f82ee,
    0x78a5636f,
    0x84c87814,
    0x8cc70208,
    0x90befffa,
    0xa4506ceb,
    0xbef9a3f7,
    0xc67178f2,
]

_INITIAL_STATE = [
    0x6a09e667,
    0xbb67ae85,
    0x3c6ef372,
    0xa54ff53a,
    0x510e527f,
    0x9b05688c,
    0x1f83d9ab,
    0x5be0cd19,
]

# Bazel Starlark has no ord(); repository files are read as Latin-1, so each
# character of a file's content is one of these 256 byte values.
_BYTES = (
    "\000\001\002\003\004\005\006\007\010\011\012\013\014\015\016\017" +
    "\020\021\022\023\024\025\026\027\030\031\032\033\034\035\036\037" +
    "\040\041\042\043\044\045\046\047\050\051\052\053\054\055\056\057" +
    "\060\061\062\063\064\065\066\067\070\071\072\073\074\075\076\077" +
    "\100\101\102\103\104\105\106\107\110\111\112\113\114\115\116\117" +
    "\120\121\122\123\124\125\126\127\130\131\132\133\134\135\136\137" +
    "\140\141\142\143\144\145\146\147\150\151\152\153\154\155\156\157" +
    "\160\161\162\163\164\165\166\167\170\171\172\173\174\175\176\177" +
    "\200\201\202\203\204\205\206\207\210\211\212\213\214\215\216\217" +
    "\220\221\222\223\224\225\226\227\230\231\232\233\234\235\236\237" +
    "\240\241\242\243\244\245\246\247\250\251\252\253\254\255\256\257" +
    "\260\261\262\263\264\265\266\267\270\271\272\273\274\275\276\277" +
    "\300\301\302\303\304\305\306\307\310\311\312\313\314\315\316\317" +
    "\320\321\322\323\324\325\326\327\330\331\332\333\334\335\336\337" +
    "\340\341\342\343\344\345\346\347\350\351\352\353\354\355\356\357" +
    "\360\361\362\363\364\365\366\367\370\371\372\373\374\375\376\377"
)
_BYTE_VALUES = {character: value for value, character in enumerate(_BYTES.elems())}

_HEX_DIGITS = "0123456789abcdef"

def _hex32(value):
    return "".join([_HEX_DIGITS[(value >> shift) & 0xf] for shift in range(28, -4, -4)])

def _rotate_right(value, count):
    return ((value >> count) | (value << (32 - count))) & _MASK

def sha256_hex(data):
    """Returns the lowercase hexadecimal SHA-256 digest of a byte string.

    Bazel reads repository files as Latin-1, so every character of `data`
    represents one byte. Fails on characters outside that byte range.

    Args:
      data: File content as returned by `repository_ctx.read`.

    Returns:
      The 64-character lowercase hexadecimal digest.
    """
    message = []
    for character in data.elems():
        if character not in _BYTE_VALUES:
            fail("sha256_hex input must be a byte string")
        message.append(_BYTE_VALUES[character])
    bit_length = len(message) * 8
    message.append(0x80)
    message.extend([0] * ((56 - len(message) % 64) % 64))
    message.extend([(bit_length >> shift) & 0xff for shift in range(56, -8, -8)])

    state = list(_INITIAL_STATE)
    for offset in range(0, len(message), 64):
        schedule = [
            (message[offset + 4 * index] << 24) |
            (message[offset + 4 * index + 1] << 16) |
            (message[offset + 4 * index + 2] << 8) |
            message[offset + 4 * index + 3]
            for index in range(16)
        ]
        for index in range(16, 64):
            previous = schedule[index - 15]
            recent = schedule[index - 2]
            sigma0 = _rotate_right(previous, 7) ^ _rotate_right(previous, 18) ^ (previous >> 3)
            sigma1 = _rotate_right(recent, 17) ^ _rotate_right(recent, 19) ^ (recent >> 10)
            schedule.append((schedule[index - 16] + sigma0 + schedule[index - 7] + sigma1) & _MASK)
        a, b, c, d, e, f, g, h = state
        for index in range(64):
            sum1 = _rotate_right(e, 6) ^ _rotate_right(e, 11) ^ _rotate_right(e, 25)
            choice = (e & f) ^ (~e & _MASK & g)
            first = (h + sum1 + choice + _ROUND_CONSTANTS[index] + schedule[index]) & _MASK
            sum0 = _rotate_right(a, 2) ^ _rotate_right(a, 13) ^ _rotate_right(a, 22)
            majority = (a & b) ^ (a & c) ^ (b & c)
            second = (sum0 + majority) & _MASK
            h = g
            g = f
            f = e
            e = (d + first) & _MASK
            d = c
            c = b
            b = a
            a = (first + second) & _MASK
        state = [
            (value + update) & _MASK
            for value, update in zip(state, [a, b, c, d, e, f, g, h])
        ]
    return "".join([_hex32(value) for value in state])
