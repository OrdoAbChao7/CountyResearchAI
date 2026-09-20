"""Audio synthesis and BGM generator for CountyResearchAI video pipeline.

Provides royalty-free ambient cinematic soundtrack synthesis and sound effects
(whoosh, chime, impact) using pure Python standard library (wave, math, struct).
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path


def generate_ambient_cinematic_bgm(
    output_path: str | Path,
    duration_sec: float = 50.0,
    sample_rate: int = 44100,
) -> Path:
    """Synthesizes a warm, cinematic ambient drone soundtrack.
    
    Composed of deep root tones, warm fifths, gentle octave shimmers,
    and a slow breath-like LFO volume envelope suitable for documentaries.
    """
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    num_samples = int(duration_sec * sample_rate)
    
    # Frequencies for warm C-sus2 ambient chord:
    # C2 (65.41 Hz), G2 (98.0 Hz), C3 (130.81 Hz), G3 (196.0 Hz), D4 (293.66 Hz)
    freqs = [
        (65.41, 0.28, 0.0),    # deep sub root
        (98.00, 0.22, 0.5),    # fifth
        (130.81, 0.20, 1.0),   # mid root
        (196.00, 0.16, 1.5),   # mid fifth
        (293.66, 0.12, 2.0),   # gentle shimmer 9th
    ]

    with wave.open(str(out_file), "w") as wav:
        wav.setnchannels(2)  # Stereo
        wav.setsampwidth(2)  # 16-bit
        wav.setframerate(sample_rate)

        frames = bytearray()
        
        for i in range(num_samples):
            t = i / sample_rate
            
            # Overall fade in (3s) and fade out (4s)
            fade_in = min(1.0, t / 3.0)
            fade_out = min(1.0, (duration_sec - t) / 4.0) if t > duration_sec - 4.0 else 1.0
            master_env = fade_in * fade_out
            
            # Slow LFO breathing (0.12 Hz cycle ~ 8.3s)
            lfo = 0.85 + 0.15 * math.sin(2 * math.pi * 0.12 * t)

            left_sample = 0.0
            right_sample = 0.0

            for freq, amp, phase in freqs:
                # Subtle detune for stereo width
                left_sig = math.sin(2 * math.pi * freq * t + phase)
                right_sig = math.sin(2 * math.pi * (freq * 1.0015) * t + phase + 0.3)
                
                # Subtle harmonic shimmer
                shimmer = 0.1 * math.sin(2 * math.pi * (freq * 2) * t)
                
                left_sample += (left_sig + shimmer) * amp
                right_sample += (right_sig + shimmer) * amp

            # Apply envelopes
            left_val = int(max(-32767, min(32767, left_sample * master_env * lfo * 20000)))
            right_val = int(max(-32767, min(32767, right_sample * master_env * lfo * 20000)))

            frames.extend(struct.pack("<hh", left_val, right_val))

        wav.writeframes(frames)

    return out_file


def generate_sfx_impact(
    output_path: str | Path,
    duration_sec: float = 1.2,
    sample_rate: int = 44100,
) -> Path:
    """Generates a deep cinematic impact / hit sound effect for hook."""
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    num_samples = int(duration_sec * sample_rate)

    with wave.open(str(out_file), "w") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = bytearray()

        for i in range(num_samples):
            t = i / sample_rate
            # Pitch drops from 120Hz to 40Hz
            freq = max(35.0, 120.0 * math.exp(-6.0 * t))
            env = math.exp(-4.5 * t)
            sig = math.sin(2 * math.pi * freq * t) * env
            val = int(max(-32767, min(32767, sig * 28000)))
            frames.extend(struct.pack("<hh", val, val))

        wav.writeframes(frames)

    return out_file
