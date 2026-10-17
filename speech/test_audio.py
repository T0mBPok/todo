import unittest
import numpy as np
from audio import split_audio, SAMPLE_RATE

class AudioChunksTest(unittest.TestCase):
    def test_long_audio_preserves_every_sample(self):
        audio=np.ones(65*SAMPLE_RATE,dtype=np.float32)
        audio[20*SAMPLE_RATE:21*SAMPLE_RATE]=0
        chunks=list(split_audio(audio))
        self.assertGreater(len(chunks),1)
        self.assertTrue(all(len(chunk)<=22*SAMPLE_RATE for chunk in chunks))
        np.testing.assert_array_equal(np.concatenate(chunks),audio)

    def test_short_and_empty_audio(self):
        self.assertEqual(list(split_audio(np.array([],dtype=np.float32))),[])
        audio=np.ones(100,dtype=np.float32)
        self.assertEqual(len(list(split_audio(audio))),1)
