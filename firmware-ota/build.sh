#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Build firmware
pio run -e xiao_esp32s3

# Pack esp-sr models into srmodels.bin for the model partition (0x610000)
# Pipeline: NS(nsnet2) + VAD(vadnet1_medium)
MODEL_DIR=".pio/libdeps/xiao_esp32s3/esp-sr/model"
OUT_PATH="$MODEL_DIR/srmodels.bin"
python3 -c "
import struct, os, sys

MODEL_DIR = sys.argv[1]
OUT_PATH = sys.argv[2]
STR_LEN = 32

def pack_string(s):
    b = s.encode('utf-8')[:STR_LEN]
    return b + b'\x00' * (STR_LEN - len(b))

needed = {
    'nsnet2': os.path.join(MODEL_DIR, 'nsnet_model/nsnet2'),
    'vadnet1_medium': os.path.join(MODEL_DIR, 'vadnet_model/vadnet1_medium'),
}

models = {}
for name, path in needed.items():
    files = {}
    for f in sorted(os.listdir(path)):
        fp = os.path.join(path, f)
        if os.path.isfile(fp):
            with open(fp, 'rb') as fh:
                files[f] = fh.read()
    if files:
        models[name] = files

file_count = sum(len(v) for v in models.values())
header_size = 4 + len(models) * (STR_LEN + 4) + file_count * (STR_LEN + 4 + 4)
data_offsets = {}
current_offset = header_size
for name in sorted(models.keys()):
    for fname in sorted(models[name].keys()):
        data_offsets[(name, fname)] = current_offset
        current_offset += len(models[name][fname])

out = struct.pack('I', len(models))
for name in sorted(models.keys()):
    out += pack_string(name)
    out += struct.pack('I', len(models[name]))
    for fname in sorted(models[name].keys()):
        out += pack_string(fname)
        out += struct.pack('I', data_offsets[(name, fname)])
        out += struct.pack('I', len(models[name][fname]))
for name in sorted(models.keys()):
    for fname in sorted(models[name].keys()):
        out += models[name][fname]

with open(OUT_PATH, 'wb') as f:
    f.write(out)
print(f'Packed {len(out)/1024:.0f} KB ({len(out)} bytes) to {OUT_PATH}')
" "$MODEL_DIR" "$OUT_PATH"

# Native tests
pio test -e test
