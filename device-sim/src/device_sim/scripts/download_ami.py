"""Download AMI Meeting Corpus audio and annotations for a given meeting ID."""

import os
import sys
from pathlib import Path

import requests

BASE_URL = "https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus"
ANNOTATION_BASE = "https://groups.inf.ed.ac.uk/ami/AMICorpusAnnotations"
ANNOTATION_ZIP = f"{ANNOTATION_BASE}/ami_public_manual_1.6.2.zip"
RETRIES = 3
TIMEOUT = 60


def get_meeting_id() -> str:
    return os.environ.get("MEETING_ID", "EN2001a")


def get_data_dir() -> Path:
    script_dir = Path(__file__).parent.parent.parent.parent
    return script_dir / "data"


def download_with_retry(url: str, dest: Path, timeout: int = TIMEOUT) -> Path:
    """Download a URL to dest, retrying up to RETRIES times on failure."""
    for attempt in range(RETRIES):
        try:
            resp = requests.get(url, timeout=timeout, stream=True)
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)
            return dest
        except requests.RequestException as exc:
            print(f"  Attempt {attempt + 1}/{RETRIES} failed: {exc}", file=sys.stderr)
            if attempt == RETRIES - 1:
                raise
    return dest  # unreachable


def download_audio(meeting_id: str, data_dir: Path) -> Path:
    """Download the pre-mixed headset WAV for a meeting ID."""
    wav_path = data_dir / meeting_id / f"{meeting_id}.headset.wav"

    if wav_path.exists():
        print(f"[skip] {wav_path} already exists")
        return wav_path

    print(f"Downloading headset mix for {meeting_id} (~160 MB)...")
    url = f"{BASE_URL}/{meeting_id}/audio/{meeting_id}.Mix-Headset.wav"
    download_with_retry(url, wav_path, timeout=300)

    if not wav_path.exists():
        raise RuntimeError(f"Expected {wav_path} not found after download")
    return wav_path


def download_info(meeting_id: str, data_dir: Path) -> Path:
    """Download the meeting info XML which maps channels to person IDs."""
    info_path = data_dir / meeting_id / f"{meeting_id}.info.xml"

    if info_path.exists():
        print(f"[skip] {info_path} already exists")
        return info_path

    print(f"Downloading meeting info for {meeting_id}...")
    url = f"{BASE_URL}/{meeting_id}/info.xml"
    download_with_retry(url, info_path, timeout=30)
    return info_path


def download_annotations(meeting_id: str, data_dir: Path) -> Path:
    """Download the annotations zip (cached after first download)."""
    annotation_zip = data_dir / meeting_id / "annotations.zip"

    if annotation_zip.exists():
        print("[skip] annotations zip already cached")
    else:
        print("Downloading AMI annotations zip (one-time, ~60 MB)...")
        download_with_retry(ANNOTATION_ZIP, annotation_zip, timeout=120)

    return annotation_zip


def main() -> None:
    meeting_id = get_meeting_id()
    data_dir = get_data_dir()
    print(f"Meeting: {meeting_id}  |  Data dir: {data_dir}")

    wav_path = download_audio(meeting_id, data_dir)
    info_path = download_info(meeting_id, data_dir)
    ann_zip = download_annotations(meeting_id, data_dir)

    print("\nDone. Files:")
    print(f"  Audio:  {wav_path}")
    print(f"  Info:   {info_path}")
    print(f"  Annot:  {ann_zip}")
    print("\n  Annotation parsing is handled by device_sim.slicer at runtime.")


if __name__ == "__main__":
    main()
