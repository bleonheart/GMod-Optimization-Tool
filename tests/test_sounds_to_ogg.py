import unittest
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sound_compression.sounds_to_ogg import ensure_supported_ogg_sample_rate, resample_oggs, sounds_to_ogg


class SoundsToOggTests(unittest.TestCase):
    def test_returns_zero_tuple_for_empty_folder(self):
        with TemporaryDirectory() as tmp_dir:
            result = sounds_to_ogg(tmp_dir)

        self.assertEqual(result, (0, 0))

    def test_converts_wav_without_cue_chunk(self):
        with TemporaryDirectory() as tmp_dir:
            wav_path = Path(tmp_dir) / 'custom.wav'
            wav_path.write_bytes(b'RIFFmock')

            class FakeSound:
                def set_frame_rate(self, rate):
                    self.rate = rate
                    return self

                def export(self, output_path, format='ogg'):
                    Path(output_path).write_bytes(b'OggSmock')

            with mock.patch('sound_compression.sounds_to_ogg.WavInfoReader', return_value=SimpleNamespace(cues=None, smpl=None)), \
                 mock.patch('sound_compression.sounds_to_ogg.pydub.AudioSegment.from_wav', return_value=FakeSound()), \
                 mock.patch('sound_compression.sounds_to_ogg.subprocess.run', return_value=SimpleNamespace(returncode=1)), \
                 mock.patch('sound_compression.trim_empty.trim_single_audio_file'):
                result = sounds_to_ogg(tmp_dir)
                ogg_path = Path(tmp_dir) / 'custom.ogg'
                wav_exists = wav_path.exists()
                ogg_exists = ogg_path.exists()

        self.assertEqual(result[1], 1)
        self.assertFalse(wav_exists)
        self.assertTrue(ogg_exists)

    def test_skips_wav_with_cues(self):
        with TemporaryDirectory() as tmp_dir:
            wav_path = Path(tmp_dir) / 'looped.wav'
            wav_path.write_bytes(b'RIFFmock')
            wav_info = SimpleNamespace(cues=SimpleNamespace(cues=[object()]), smpl=None)

            with mock.patch('sound_compression.sounds_to_ogg.WavInfoReader', return_value=wav_info), \
                 mock.patch('sound_compression.sounds_to_ogg.pydub.AudioSegment.from_wav') as from_wav:
                result = sounds_to_ogg(tmp_dir)

        self.assertEqual(result, (0, 0))
        from_wav.assert_not_called()

    def test_resamples_unsupported_ogg_rate(self):
        with TemporaryDirectory() as tmp_dir:
            ogg_path = Path(tmp_dir) / 'voice.ogg'
            ogg_path.write_bytes(b'OggSmock')

            with mock.patch('sound_compression.sounds_to_ogg._detect_ogg_sample_rate', return_value=24000), \
                 mock.patch('sound_compression.sounds_to_ogg.subprocess.run', return_value=SimpleNamespace(returncode=0)), \
                 mock.patch('sound_compression.sounds_to_ogg.os.replace') as replace_mock:
                tmp_resampled = Path(str(ogg_path) + '.resample.tmp.ogg')
                tmp_resampled.write_bytes(b'OggSresampled')

                changed = ensure_supported_ogg_sample_rate(str(ogg_path))

        self.assertTrue(changed)
        replace_mock.assert_called_once_with(str(tmp_resampled), str(ogg_path))

    def test_resample_oggs_skips_gmod_supported_rates(self):
        with TemporaryDirectory() as tmp_dir:
            ogg_path = Path(tmp_dir) / 'voice.ogg'
            ogg_path.write_bytes(b'OggSmock')

            with mock.patch('sound_compression.sounds_to_ogg._detect_ogg_sample_rate', return_value=22050), \
                 mock.patch('sound_compression.sounds_to_ogg.subprocess.run') as run_mock:
                result = resample_oggs(tmp_dir)

        self.assertEqual(result, (0, 0))
        run_mock.assert_not_called()


if __name__ == '__main__':
    unittest.main()
