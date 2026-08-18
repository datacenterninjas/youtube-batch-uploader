import os
import subprocess
from pathlib import Path
import math
import wave
import struct
import numpy as np
import imageio_ffmpeg

MUSIC_DIR = Path("static/music")
MUSIC_DIR.mkdir(parents=True, exist_ok=True)

def get_ffmpeg():
    """Returns path to native Apple Silicon ffmpeg binary."""
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"

def generate_stock_music():
    """Generates built-in pleasant royalty-free ambient music loops if not already present."""
    tracks = {
        "lofi_chill.wav": ("Lo-Fi Chill Chords", [261.63, 329.63, 392.00, 493.88], [220.00, 261.63, 329.63, 392.00], 75),
        "ambient_travel.wav": ("Ambient Travel & Horizon", [196.00, 246.94, 293.66, 370.00], [164.81, 196.00, 246.94, 293.66], 85),
        "upbeat_vlog.wav": ("Upbeat Vlog Acoustic Rhythm", [329.63, 392.00, 493.88, 587.33], [261.63, 329.63, 392.00, 523.25], 110)
    }

    sample_rate = 44100
    duration_secs = 16.0 # 16 second seamless loop

    for filename, (title, chord1, chord2, bpm) in tracks.items():
        out_path = MUSIC_DIR / filename
        if out_path.exists():
            continue

        num_samples = int(sample_rate * duration_secs)
        samples = np.zeros(num_samples, dtype=np.float32)
        t = np.linspace(0, duration_secs, num_samples, endpoint=False)

        # 4-measure harmony progression
        bar_len = duration_secs / 4.0
        for i in range(4):
            chord = chord1 if i % 2 == 0 else chord2
            start_idx = int(i * bar_len * sample_rate)
            end_idx = int((i + 1) * bar_len * sample_rate)
            t_seg = t[start_idx:end_idx] - (i * bar_len)
            
            # Synthesize warm layered harmonics
            seg_wave = np.zeros(len(t_seg), dtype=np.float32)
            for freq in chord:
                # Fundamental + gentle 2nd and 3rd harmonics
                wave_harm = 0.4 * np.sin(2 * np.pi * freq * t_seg) + \
                            0.2 * np.sin(2 * np.pi * (freq * 2) * t_seg) + \
                            0.1 * np.sin(2 * np.pi * (freq * 3) * t_seg)
                # Apply soft attack & release envelope
                env = np.clip(t_seg / 0.15, 0, 1) * np.clip((bar_len - t_seg) / 0.2, 0, 1)
                seg_wave += wave_harm * env
            
            # Subtle rhythmic acoustic pulse
            pulse = 0.08 * np.sin(2 * np.pi * (bpm / 60.0 * 2) * t_seg)
            seg_wave = (seg_wave / len(chord)) + pulse
            samples[start_idx:end_idx] = seg_wave

        # Normalize and apply master envelope
        samples = samples / (np.max(np.abs(samples)) + 1e-6) * 0.7
        int_samples = (samples * 32767).astype(np.int16)

        # Save Stereo WAV
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            stereo_data = np.column_stack((int_samples, int_samples)).flatten()
            wf.writeframes(stereo_data.tobytes())

        print(f"🎵 Generated stock royalty-free music track: {filename} ({title})")

# Generate on import
generate_stock_music()

def get_available_tracks():
    """Returns list of available background music tracks."""
    generate_stock_music()
    preset_names = {
        "lofi_chill.wav": "☕ Lo-Fi Chill (Warm relaxing chords)",
        "ambient_travel.wav": "🌄 Ambient Travel (Cinematic nature & horizon)",
        "upbeat_vlog.wav": "✨ Upbeat Vlog (Acoustic bright rhythm)"
    }
    tracks = []
    for f in MUSIC_DIR.glob("*.wav"):
        tracks.append({
            "filename": f.name,
            "title": preset_names.get(f.name, f.stem.replace("_", " ").title()),
            "path": f"/static/music/{f.name}"
        })
    return tracks

def enhance_speech_and_denoise(input_video_path, output_video_path=None):
    """
    Cleans up microphone audio using noise reduction (afftdn), highpass/lowpass filters,
    and EBU R128 loudnorm standard broadcast voice leveling.
    Preserves video track with fast -c:v copy.
    """
    input_p = Path(input_video_path)
    if not output_video_path:
        out_p = input_p.parent / f"{input_p.stem}_enhanced{input_p.suffix}"
    else:
        out_p = Path(output_video_path)

    ffmpeg = get_ffmpeg()
    
    # High-quality speech clarity DSP chain:
    # 1. afftdn: FFT adaptive background noise reduction
    # 2. highpass/lowpass: removes microphone desk rumbles and harsh high hiss
    # 3. loudnorm: broadcast speech loudness normalization (-16 LUFS)
    audio_filter = "afftdn=nf=-24:tn=1,highpass=f=75,lowpass=f=12000,loudnorm=I=-16:TP=-1.5:LRA=11"

    cmd = [
        ffmpeg, "-y",
        "-i", str(input_p),
        "-c:v", "copy",
        "-af", audio_filter,
        "-c:a", "aac",
        "-b:a", "192k",
        str(out_p)
    ]

    print(f"🎙️ Enhancing audio clarity for '{input_p.name}'...")
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg audio enhancement failed: {res.stderr}")

    return str(out_p)

def mix_background_music(input_video_path, music_filename, output_video_path=None, music_volume=0.20, auto_ducking=True):
    """
    Mixes royalty-free background music with video audio.
    Supports smart auto-ducking (lowers music when voice is spoken).
    Preserves video track with fast -c:v copy.
    """
    input_p = Path(input_video_path)
    music_p = MUSIC_DIR / music_filename
    if not music_p.exists():
        # Check if full path passed
        music_p = Path(music_filename)
    if not music_p.exists():
        raise FileNotFoundError(f"Music track not found: {music_filename}")

    if not output_video_path:
        out_p = input_p.parent / f"{input_p.stem}_music{input_p.suffix}"
    else:
        out_p = Path(output_video_path)

    ffmpeg = get_ffmpeg()

    # Audio Filter Graph:
    # [1:a] loop music seamlessly, adjust volume
    # [0:a] original audio
    # Auto-ducking: sidechaincompress lowers [1:a] whenever [0:a] voice is present
    if auto_ducking:
        filter_complex = (
            f"[1:a]aloop=loop=-1:size=2e+09,volume={music_volume}[music];"
            f"[music][0:a]sidechaincompress=threshold=0.1:ratio=4:attack=20:release=300[ducked_music];"
            f"[0:a][ducked_music]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
    else:
        filter_complex = (
            f"[1:a]aloop=loop=-1:size=2e+09,volume={music_volume}[music];"
            f"[0:a][music]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )

    cmd = [
        ffmpeg, "-y",
        "-i", str(input_p),
        "-i", str(music_p),
        "-filter_complex", filter_complex,
        "-map", "0:v:0",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(out_p)
    ]

    print(f"🎵 Mixing background music '{music_p.name}' into '{input_p.name}' (auto-ducking={auto_ducking})...")
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg music mixing failed: {res.stderr}")

    return str(out_p)
