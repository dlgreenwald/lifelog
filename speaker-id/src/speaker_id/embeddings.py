import numpy as np
from speechbrain.inference.speaker import EncoderClassifier

from speaker_id.config import settings


class SpeakerEncoder:
    def __init__(self):
        self.encoder = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            run_opts={"device": settings.device},
        )

    def extract_embedding(self, audio_bytes: bytes) -> np.ndarray:
        """Extract ECAPA-TDNN embedding from audio segment."""
        import tempfile

        # Convert to wav if needed
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            f.flush()
            wav_path = f.name

        embeddings = self.encoder.encode_batch(wav_path)
        return embeddings.squeeze().cpu().numpy()


encoder = SpeakerEncoder()
