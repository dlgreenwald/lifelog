FROM onerahmet/openai-whisper-asr-webservice:v1.10.0-gpu

# v1.10.0 ships torch compiled against CUDA 12.6, which lacks kernels for
# Blackwell GPUs (RTX 50xx, sm_120). The image's CUDA runtime is 12.9.2,
# so we reinstall torch+cu128 which includes Blackwell support.
# Also applies the TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 workaround for the
# lightning 2.6 / pyannote weights-loading issue (issue #383).

RUN /app/.venv/bin/pip install --no-cache-dir \
    torch==2.7.1+cu128 torchaudio==2.7.1+cu128 \
    --index-url https://download.pytorch.org/whl/cu128

# Add /health endpoint (upstream image doesn't have one)
COPY health.py /app/health.py
COPY patch-model-reload.py /tmp/patch-model-reload.py
RUN /app/.venv/bin/python /tmp/patch-model-reload.py && rm /tmp/patch-model-reload.py

ENV ASR_ENGINE=whisperx \
    ASR_MODEL=large-v3 \
    ASR_DEVICE=cuda \
    TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1

# Wrapper imports health.py (registers /health on the app) then starts the server
ENTRYPOINT ["/bin/bash", "-c", "exec /app/.venv/bin/python -c 'import health; from app.webservice import start; start()'"]
