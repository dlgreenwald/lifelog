"""TTS synthesis from YAML conversations.

Loads Piper voice models, synthesizes each line in script order,
and concatenates into a single interleaved conversation WAV.
Output is 16kHz mono to match firmware.
"""

import io
import wave
from pathlib import Path

from pydub import AudioSegment
import yaml


def _silence_wav(duration_s: float, sample_rate: int = 22050) -> bytes:
    """Generate silence as 16-bit PCM WAV bytes."""
    num_samples = int(sample_rate * duration_s)
    pcm_data = b"\x00\x00" * num_samples
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def _load_piper_voice(voice_name: str, voices_dir: str):
    """Load a Piper TTS voice model. Downloads on first run."""
    from piper import PiperVoice

    voice_dir = Path(voices_dir)
    voice_dir.mkdir(parents=True, exist_ok=True)

    onnx_path = voice_dir / f"{voice_name}.onnx"
    if not onnx_path.exists():
        print(f"Downloading voice: {voice_name}...")
        import subprocess
        subprocess.run(
            [
                "python3",
                "-m",
                "piper.download_voices",
                voice_name,
                "--download-dir", str(voice_dir),
            ],
            check=True,
        )

    voice = PiperVoice.load(str(onnx_path))
    return voice


def _synthesize_line(voice, text: str) -> bytes:
    """Synthesize a single line to WAV bytes at Piper's native sample rate."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        # synthesize_wav sets the format headers itself (22050 Hz mono)
        voice.synthesize_wav(text, wf)
    wav_bytes = buf.getvalue()

    # Log duration for debugging
    buf2 = io.BytesIO(wav_bytes)
    with wave.open(buf2, "rb") as wf:
        dur = wf.getnframes() / wf.getframerate()
        print(f"    Synthesized {len(text)} chars -> {dur:.2f}s @ {wf.getframerate()}Hz")

    return wav_bytes


def _wav_bytes_duration(wav_bytes: bytes) -> float:
    """Get duration in seconds from WAV bytes."""
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as wf:
        return wf.getnframes() / wf.getframerate()


def _concatenate_wav_segments(segments: list[bytes]) -> bytes:
    """Concatenate multiple WAV byte segments into one WAV.
    
    All segments must be same sample rate, channels, bit depth.
    """
    all_pcm = bytearray()
    sample_rate = None
    for seg_bytes in segments:
        buf = io.BytesIO(seg_bytes)
        with wave.open(buf, "rb") as wf:
            if sample_rate is None:
                sample_rate = wf.getframerate()
            all_pcm.extend(wf.readframes(wf.getnframes()))

    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(all_pcm))
    return out.getvalue()


def generate_conversation(yaml_path: str, voices_dir: str, output_path: str) -> str:
    """Generate a single interleaved conversation WAV from a YAML file.

    Output is resampled to 16kHz mono (matching firmware SAMPLE_RATE).
    Returns the output file path.
    """
    with open(yaml_path) as f:
        conv = yaml.safe_load(f)

    speakers = conv["speakers"]
    lines = conv["lines"]

    # Load voice models (one per speaker, cached by voice_name)
    loaded_voices = {}
    speaker_voices = {}
    for speaker_name, speaker_info in speakers.items():
        voice_name = speaker_info["voice"]
        if voice_name not in loaded_voices:
            loaded_voices[voice_name] = _load_piper_voice(voice_name, voices_dir)
        speaker_voices[speaker_name] = loaded_voices[voice_name]

    # Synthesize lines in script order
    segments = []
    for i, line in enumerate(lines):
        speaker = line["speaker"]
        text = line["text"]
        pause_after = line.get("pause_after", 0.3)

        print(f"  Line {i+1}/{len(lines)} [{speaker}]: {text[:50]}...")
        voice = speaker_voices[speaker]
        wav_bytes = _synthesize_line(voice, text)
        segments.append(wav_bytes)

        if pause_after > 0:
            silence = _silence_wav(pause_after)
            segments.append(silence)

    # Concatenate all segments (still at Piper's native 22050 Hz)
    conversation_wav = _concatenate_wav_segments(segments)

    # Log pre-resample duration
    native_dur = _wav_bytes_duration(conversation_wav)
    print(f"  Total (native 22050 Hz): {native_dur:.1f}s")

    # Resample to 16kHz mono (matching firmware)
    audio = AudioSegment.from_wav(io.BytesIO(conversation_wav))
    audio = audio.set_frame_rate(16000).set_channels(1)

    # Write final 16kHz WAV
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    audio.export(output_path, format="wav")

    final_dur = len(audio) / 1000.0
    print(f"  Final (16000 Hz): {final_dur:.1f}s -> {output_path}")
    return output_path
