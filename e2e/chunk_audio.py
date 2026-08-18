"""WAV to 5-second Opus chunks.

Splits a conversation WAV into 5-second segments matching the firmware's
recording format, then encodes each chunk as Opus via ffmpeg.
"""

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from pydub import AudioSegment


@dataclass
class AudioChunk:
    """A single 5-second Opus chunk."""
    index: int
    opus_path: str
    duration_s: float


def chunk_and_encode(
    wav_path: str,
    output_dir: str,
    chunk_duration_ms: int = 5000,
    sample_rate: int = 16000,
    opus_bitrate: str = "24k",
) -> list[AudioChunk]:
    """Split WAV into fixed-size chunks and encode as Opus.
    
    Returns list of AudioChunk with index, path, and duration.
    """
    audio = AudioSegment.from_wav(wav_path)
    
    # Ensure mono, correct sample rate
    audio = audio.set_channels(1).set_frame_rate(sample_rate)
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    chunks = []
    total_ms = len(audio)
    index = 0
    
    while index * chunk_duration_ms < total_ms:
        start_ms = index * chunk_duration_ms
        end_ms = min(start_ms + chunk_duration_ms, total_ms)
        
        chunk_audio = audio[start_ms:end_ms]
        
        # Write chunk WAV to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            chunk_audio.export(tmp.name, format="wav")
            tmp_wav = tmp.name
        
        # Encode to Opus via ffmpeg
        opus_filename = f"chunk_{index:04d}.opus"
        opus_path = str(output_path / opus_filename)
        
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", tmp_wav,
                "-c:a", "libopus",
                "-b:a", opus_bitrate,
                "-ar", str(sample_rate),
                "-ac", "1",
                "-application", "voip",
                opus_path,
            ],
            check=True,
            capture_output=True,
        )
        
        # Clean up temp WAV
        Path(tmp_wav).unlink()
        
        chunk_duration = (end_ms - start_ms) / 1000.0
        chunks.append(AudioChunk(
            index=index,
            opus_path=opus_path,
            duration_s=chunk_duration,
        ))
        
        index += 1
    
    print(f"Split into {len(chunks)} chunks ({chunk_duration_ms/1000:.1f}s each)")
    return chunks
