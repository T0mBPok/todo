import numpy as np

SAMPLE_RATE = 16000

def split_audio(audio):
    """At most 22 seconds per chunk; prefer a quiet 200ms boundary."""
    offset=0
    while len(audio)-offset > 22*SAMPLE_RATE:
        candidates=range(offset+18*SAMPLE_RATE, offset+22*SAMPLE_RATE, SAMPLE_RATE//5)
        cut=min(candidates, key=lambda i: float(np.mean(audio[i:i+SAMPLE_RATE//5] ** 2)))
        cut += SAMPLE_RATE//10
        yield audio[offset:cut]
        offset=cut
    if offset<len(audio):
        yield audio[offset:]


def trim_silence(audio):
    """Remove long near-silent gaps; retain 300ms around every audible region.

    This conservative energy gate only skips quiet audio. It never changes
    sample values, playback rate, or the order of the retained speech.
    """
    frame = SAMPLE_RATE // 50  # 20ms
    count = (len(audio) + frame - 1) // frame
    if count < 2:
        return audio
    padded = np.pad(audio, (0, count * frame - len(audio)))
    rms = np.sqrt(np.mean(padded.reshape(count, frame) ** 2, axis=1))
    threshold = 0.00001  # below one PCM16 step; do not classify quiet words as silence
    active = np.flatnonzero(rms > threshold)
    if not len(active):
        return audio
    # Separate regions only at gaps over 1.2s; short pauses stay intact.
    splits = np.flatnonzero(np.diff(active) > 60) + 1
    regions = np.split(active, splits)
    padding = int(0.3 * SAMPLE_RATE)
    spans = [(max(0, int(r[0]) * frame - padding),
              min(len(audio), (int(r[-1]) + 1) * frame + padding)) for r in regions]
    if len(spans) == 1 and spans[0] == (0, len(audio)):
        return audio
    return np.concatenate([audio[start:end] for start, end in spans])
