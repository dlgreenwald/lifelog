"""Utterance slicer — splits a meeting WAV by speaker segments from AMI NITE XML."""

from __future__ import annotations

import os
import random
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from pydub import AudioSegment


@dataclass
class UtteranceSlice:
    index: int
    wav_path: str
    opus_path: str
    start_s: float
    end_s: float
    speaker_id: str
    transcript: str
    session_id: int
    is_silence: bool = False


NITE_NS = "{http://nite.sourceforge.net/}"
PAD_MS = 300


def _parse_info_xml(path: str) -> dict[int, str]:
    import xml.etree.ElementTree as ET

    mapping: dict[int, str] = {}
    tree = ET.parse(path)
    root = tree.getroot()
    for person in root.findall("person"):
        cid = int(person.attrib["id"]) - 1
        mapping[cid] = person.attrib["name"]
    return mapping


def _iter_segments(
    annotations_zip: zipfile.ZipFile,
    meeting_id: str,
    channel: int | None = None,
) -> Iterator:
    import xml.etree.ElementTree as ET

    names = sorted(
        n for n in annotations_zip.namelist()
        if f"/{meeting_id}." in n and n.endswith(".segments.xml")
    )
    for name in names:
        content = annotations_zip.read(name).decode("utf-8", errors="replace")
        root = ET.fromstring(content)
        for seg in root.findall(".//segment"):
            ch = int(seg.attrib["channel"])
            if channel is not None and ch != channel:
                continue
            start_s = float(seg.attrib["transcriber_start"])
            end_s = float(seg.attrib["transcriber_end"])
            word_refs: list[str] = []
            for child in seg:
                if child.tag == f"{NITE_NS}child":
                    href = child.attrib.get("href", "")
                    if "#id(" in href:
                        id_section = href.split("#id(")[1]
                        for id_part in id_section.split(".."):
                            wid = id_part.rstrip(")").split("(")[-1]
                            if wid:
                                word_refs.append(wid)
            yield ch, start_s, end_s, word_refs


def _get_words(annotations_zip: zipfile.ZipFile, meeting_id: str) -> dict[str, str]:
    import xml.etree.ElementTree as ET

    words: dict[str, str] = {}
    word_files = sorted(
        n for n in annotations_zip.namelist()
        if f"/{meeting_id}." in n and n.endswith(".words.xml")
    )
    for name in word_files:
        content = annotations_zip.read(name).decode("ISO-8859-1", errors="replace")
        root = ET.fromstring(content)
        for w_elem in root.findall(".//w"):
            wid = w_elem.attrib.get(f"{NITE_NS}id", "")
            text = (w_elem.text or "").strip()
            if wid and text:
                words[wid] = text
    return words


def _build_utterances(
    wav_path: str,
    annotation_zip_path: str,
    meeting_id: str,
    headset_channel: int | None = None,
) -> list[tuple[int, str, float, float, str, int]]:
    info_path = str(Path(wav_path).parent / f"{meeting_id}.info.xml")
    speaker_map = _parse_info_xml(info_path) if Path(info_path).exists() else {}

    with zipfile.ZipFile(annotation_zip_path, "r") as zf:
        words = _get_words(zf, meeting_id)
        all_segs: list[tuple[int, str, float, float, str]] = []

        for ch, start_s, end_s, word_refs in _iter_segments(zf, meeting_id, channel=headset_channel):
            speaker = speaker_map.get(ch, f"CH{ch}")
            text = " ".join(words[ref] for ref in word_refs if ref in words)
            all_segs.append((ch, speaker, start_s, end_s, text))

    all_segs.sort(key=lambda x: x[2])

    utterances: list[tuple[int, str, float, float, str, int]] = []
    session_id = 0
    cur_speaker = ""
    cur_start = 0.0
    cur_end = 0.0
    cur_text = ""
    utt_idx = 0

    for _ch, speaker, start, end, transcript in all_segs:
        gap = start - cur_end
        new_session = gap >= 2.0
        new_utt = new_session or (speaker != cur_speaker and cur_speaker != "")

        if new_utt:
            if cur_speaker != "":
                utterances.append((utt_idx, cur_speaker, cur_start, cur_end, cur_text.strip(), session_id))
                utt_idx += 1
            if new_session:
                session_id += 1
            cur_speaker = speaker
            cur_start = start
            cur_end = end
            cur_text = transcript
        else:
            cur_end = end
            cur_text += " " + transcript

    if cur_speaker != "":
        utterances.append((utt_idx, cur_speaker, cur_start, cur_end, cur_text.strip(), session_id))

    return utterances


def slice_meeting(
    wav_path: str,
    annotation_zip_path: str,
    output_dir: str,
    max_utterances: int = 0,
    meeting_id: str | None = None,
) -> list[UtteranceSlice]:
    os.makedirs(output_dir, exist_ok=True)

    if meeting_id is None:
        meeting_id = Path(wav_path).stem

    audio = AudioSegment.from_wav(wav_path)
    if audio.frame_rate != 16000:
        audio = audio.set_frame_rate(16000)
    if audio.channels != 1:
        audio = audio.set_channels(1)

    headset_channel_str = os.environ.get("HEADSET_CHANNEL", "")
    headset_channel: int | None = int(headset_channel_str) if headset_channel_str.isdigit() else None
    utterances = _build_utterances(wav_path, annotation_zip_path, meeting_id, headset_channel=headset_channel)

    if max_utterances > 0:
        utterances = utterances[:max_utterances]

    min_utt_dur = float(os.environ.get("MIN_UTTERANCE_DURATION", "20"))
    silence_insert_every = int(os.environ.get("SILENCE_INSERT_EVERY", "0"))
    silence_insert_prob = float(os.environ.get("SILENCE_INSERT_PROBABILITY", "0.5"))

    slices: list[UtteranceSlice] = []
    real_counter = 0

    for idx, (_utt_idx, speaker, start_s, end_s, transcript, session_key) in enumerate(utterances):
        duration_s = end_s - start_s
        if duration_s < min_utt_dur:
            continue

        pad_ms = PAD_MS
        start_pad = max(0, start_s * 1000 - pad_ms)
        end_pad = min(len(audio), end_s * 1000 + pad_ms)
        chunk = audio[start_pad:end_pad]

        out_wav = os.path.join(output_dir, f"utterance_{idx:04d}.wav")
        chunk.export(out_wav, format="wav")

        slices.append(UtteranceSlice(
            index=idx,
            wav_path=out_wav,
            opus_path="",
            start_s=start_s,
            end_s=end_s,
            speaker_id=speaker,
            transcript=transcript,
            session_id=session_key,
            is_silence=False,
        ))
        real_counter += 1

        if silence_insert_every > 0 and real_counter % silence_insert_every == 0 and random.random() < silence_insert_prob:
            dur_s = random.uniform(1.5, 4.0)
            silence_wav = os.path.join(output_dir, f"utterance_{idx:04d}_silence.wav")
            silent = AudioSegment.silent(duration=int(dur_s * 1000), frame_rate=16000)
            silent = silent.set_frame_rate(16000).set_channels(1)
            silent.export(silence_wav, format="wav")
            slices.append(UtteranceSlice(
                index=idx + 0.5,
                wav_path=silence_wav,
                opus_path="",
                start_s=end_s,
                end_s=end_s + dur_s,
                speaker_id="UNKNOWN",
                transcript="",
                session_id=session_key,
                is_silence=True,
            ))

    return slices
