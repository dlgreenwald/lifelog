#!/usr/bin/env python3
"""Patch mbain_whisperx_engine.py to fix MODEL_IDLE_TIMEOUT reload bug.

Bug: https://github.com/ahmetoner/whisper-asr-webservice/issues/321
When the model is unloaded due to idle timeout, self.model is set to None.
On the next request, load_model() tries self.model['whisperx'] = ... which
fails with TypeError: 'NoneType' object does not support item assignment.

Fix: Reinitialize self.model dict at the top of load_model() if it's None.
"""

import re
import sys
from pathlib import Path

TARGET = Path("/app/app/asr_models/mbain_whisperx_engine.py")

FIX = """\
    def load_model(self):
        if self.model is None:
            self.model = {
                'whisperx': None,
                'diarize_model': None,
                'align_model': {}
            }

"""

original = TARGET.read_text()
patched, count = re.subn(
    r"    def load_model\(self\):\n",
    FIX,
    original,
    count=1,
)

if count == 0:
    print("ERROR: could not find load_model() in " + str(TARGET), file=sys.stderr)
    sys.exit(1)

if patched == original:
    print("Already patched, skipping.")
    sys.exit(0)

TARGET.write_text(patched)
print("Patched " + str(TARGET))
