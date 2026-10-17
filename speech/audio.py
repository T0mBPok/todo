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
