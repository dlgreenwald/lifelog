import logging
import threading
import time

import numpy as np
from speechbrain.inference.speaker import EncoderClassifier

from speaker_id.config import settings

logger = logging.getLogger(__name__)

IDLE_TIMEOUT = 300  # 5 minutes
WATCHDOG_INTERVAL = 30  # Check every 30 seconds


class SpeakerEncoder:
    """ECAPA-TDNN speaker encoder (kept for backward compatibility with tests)."""

    def __init__(self):
        self.encoder = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            run_opts={"device": settings.device},
        )

    def extract_embedding(self, audio_bytes: bytes) -> np.ndarray:
        """Extract ECAPA-TDNN embedding from audio segment."""
        import tempfile, os, soundfile

        # Write to temp file and load with soundfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            f.flush()
            wav_path = f.name

        try:
            waveform, sample_rate = soundfile.read(wav_path, dtype="float32")
        finally:
            os.unlink(wav_path)

        # Ensure mono: average channels if stereo
        if waveform.ndim > 1:
            waveform = waveform.mean(axis=1)

        # Resample to 16000 Hz if needed
        if sample_rate != 16000:
            import scipy.signal
            num_samples = int(len(waveform) * 16000 / sample_rate)
            waveform = scipy.signal.resample(waveform, num_samples)
            sample_rate = 16000

        # Convert to torch tensor [batch, time]
        import torch
        waveform_tensor = torch.from_numpy(waveform).unsqueeze(0)  # [1, time]

        embeddings = self.encoder.encode_batch(waveform_tensor)
        return embeddings.squeeze().cpu().numpy()


class ModelManager:
    """Manages lazy loading and idle unloading of the ECAPA-TDNN model."""

    def __init__(self):
        self._encoder = None
        self._lock = threading.Lock()
        self._last_access = 0.0
        self._watchdog_thread = None
        self._stop_event = threading.Event()
        self._start_watchdog()

    def _start_watchdog(self):
        """Start the background watchdog thread."""
        def watchdog_loop():
            while not self._stop_event.wait(WATCHDOG_INTERVAL):
                self._check_idle()

        self._watchdog_thread = threading.Thread(
            target=watchdog_loop,
            daemon=True,
            name="model-watchdog"
        )
        self._watchdog_thread.start()
        logger.info("Model watchdog started (check interval: %ds, idle timeout: %ds)",
                    WATCHDOG_INTERVAL, IDLE_TIMEOUT)

    def _check_idle(self):
        """Check if model has been idle too long and unload it."""
        if self._encoder is None:
            return

        idle_time = time.time() - self._last_access
        if idle_time >= IDLE_TIMEOUT:
            with self._lock:
                # Re-check after acquiring lock — another thread may have accessed
                idle_time = time.time() - self._last_access
                if self._encoder is not None and idle_time >= IDLE_TIMEOUT:
                    logger.info("Model idle for %.1fs (timeout: %ds), unloading to free GPU memory",
                               idle_time, IDLE_TIMEOUT)
                    del self._encoder
                    self._encoder = None
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    logger.info("Model unloaded and GPU memory cleared")

    def _load_model(self) -> SpeakerEncoder:
        """Load the ECAPA-TDNN model."""
        logger.info("Loading ECAPA-TDNN model on device: %s", settings.device)
        speaker_encoder = SpeakerEncoder()
        logger.info("ECAPA-TDNN model loaded successfully")
        return speaker_encoder

    def get_encoder(self):
        """Get the encoder, loading if necessary. Thread-safe."""
        with self._lock:
            self._last_access = time.time()
            if self._encoder is None:
                self._encoder = self._load_model()
            return self._encoder

    def extract_embedding(self, audio_bytes: bytes) -> np.ndarray:
        """Extract ECAPA-TDNN embedding from audio segment."""
        speaker_encoder = self.get_encoder()
        return speaker_encoder.extract_embedding(audio_bytes)

    def shutdown(self):
        """Stop the watchdog thread and unload model."""
        self._stop_event.set()
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=5)
        with self._lock:
            if self._encoder is not None:
                del self._encoder
                self._encoder = None
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
        logger.info("Model manager shut down")


# Singleton instance
encoder = ModelManager()
