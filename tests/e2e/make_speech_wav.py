"""Writes a 20 s speech-like WAV for Chrome's fake microphone.

Chrome's default fake mic is a pure beep that WebRTC noise suppression filters
out, so the speaking indicator never fires. This synthetic "voice" survives it.

    python tests/e2e/make_speech_wav.py speech.wav
"""
import math
import random
import struct
import sys
import wave

random.seed(1)
RATE = 48000
frames = bytearray()
for i in range(RATE * 20):
    t = i / RATE
    # Harmonic stack around 140 Hz with a syllable-rate envelope and pauses.
    env = max(0.0, math.sin(2 * math.pi * 3.2 * t)) ** 2 * (1 if (t % 2.5) < 1.9 else 0)
    f0 = 140 + 25 * math.sin(2 * math.pi * 0.7 * t)
    s = sum(math.sin(2 * math.pi * f0 * k * t) / k for k in range(1, 8))
    s += 0.15 * random.uniform(-1, 1)
    frames += struct.pack("<h", int(max(-1, min(1, 0.35 * env * s)) * 32767))

with wave.open(sys.argv[1] if len(sys.argv) > 1 else "speech.wav", "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(RATE)
    w.writeframes(bytes(frames))
