import unittest
import numpy as np
from audio import split_audio, trim_silence, SAMPLE_RATE

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


class SilencePreparationTest(unittest.TestCase):
    def test_long_edges_are_skipped_with_padding(self):
        speech=np.full(3*SAMPLE_RATE,0.05,dtype=np.float32)
        audio=np.concatenate([np.zeros(25*SAMPLE_RATE),speech,np.zeros(25*SAMPLE_RATE)])
        result=trim_silence(audio)
        self.assertEqual(len(result),int(3.6*SAMPLE_RATE))
        np.testing.assert_array_equal(result[int(.3*SAMPLE_RATE):-int(.3*SAMPLE_RATE)],speech)

    def test_long_internal_pause_is_compressed_without_losing_speech(self):
        first=np.full(SAMPLE_RATE,.05,dtype=np.float32)
        second=np.full(SAMPLE_RATE,-.03,dtype=np.float32)
        result=trim_silence(np.concatenate([first,np.zeros(20*SAMPLE_RATE),second]))
        self.assertEqual(len(result),int(2.6*SAMPLE_RATE))
        np.testing.assert_array_equal(result[:SAMPLE_RATE],first)
        np.testing.assert_array_equal(result[-SAMPLE_RATE:],second)

    def test_short_pauses_and_quiet_speech_are_retained(self):
        audio=np.concatenate([np.full(SAMPLE_RATE,.05),np.zeros(SAMPLE_RATE//2),np.full(SAMPLE_RATE,.0001)])
        np.testing.assert_array_equal(trim_silence(audio),audio)

    def test_empty_and_all_silent_audio_stays_unchanged(self):
        for audio in [np.array([],dtype=np.float32),np.zeros(5*SAMPLE_RATE)]:
            np.testing.assert_array_equal(trim_silence(audio),audio)
