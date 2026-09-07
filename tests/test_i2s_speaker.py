import unittest
from unittest.mock import MagicMock, patch

from src.hardware.speaker.i2s_speaker import I2SSpeaker


class I2SSpeakerVolumeTests(unittest.TestCase):
    @patch("src.hardware.speaker.i2s_speaker.subprocess.Popen")
    @patch("src.hardware.speaker.i2s_speaker.Path.exists", return_value=True)
    def test_play_applies_default_full_volume(self, mock_exists, mock_popen):
        mock_popen.side_effect = [MagicMock(stdout=MagicMock()), MagicMock()]
        speaker = I2SSpeaker()

        speaker.play("sounds/test.mp3")

        ffmpeg_call_args = mock_popen.call_args_list[0][0][0]
        self.assertIn("-filter:a", ffmpeg_call_args)
        self.assertIn("volume=1.0", ffmpeg_call_args)

    @patch("src.hardware.speaker.i2s_speaker.subprocess.Popen")
    @patch("src.hardware.speaker.i2s_speaker.Path.exists", return_value=True)
    def test_play_applies_custom_volume(self, mock_exists, mock_popen):
        mock_popen.side_effect = [MagicMock(stdout=MagicMock()), MagicMock()]
        speaker = I2SSpeaker()

        speaker.play("sounds/test.mp3", volume=0.4)

        ffmpeg_call_args = mock_popen.call_args_list[0][0][0]
        self.assertIn("volume=0.4", ffmpeg_call_args)

    @patch("src.hardware.speaker.i2s_speaker.subprocess.Popen")
    @patch("src.hardware.speaker.i2s_speaker.Path.exists", return_value=True)
    def test_negative_volume_is_clamped_to_zero(self, mock_exists, mock_popen):
        mock_popen.side_effect = [MagicMock(stdout=MagicMock()), MagicMock()]
        speaker = I2SSpeaker()

        speaker.play("sounds/test.mp3", volume=-0.5)

        ffmpeg_call_args = mock_popen.call_args_list[0][0][0]
        self.assertIn("volume=0.0", ffmpeg_call_args)

    @patch("src.hardware.speaker.i2s_speaker.subprocess.Popen")
    @patch("src.hardware.speaker.i2s_speaker.Path.exists", return_value=True)
    def test_play_pipes_ffmpeg_decode_into_aplay(self, mock_exists, mock_popen):
        mock_popen.side_effect = [MagicMock(stdout=MagicMock()), MagicMock()]
        speaker = I2SSpeaker(alsa_device="plughw:CARD=sndrpihifiberry,DEV=0")

        speaker.play("sounds/test.mp3")

        self.assertEqual(mock_popen.call_count, 2)
        ffmpeg_call_args = mock_popen.call_args_list[0][0][0]
        aplay_call_args = mock_popen.call_args_list[1][0][0]
        self.assertEqual(ffmpeg_call_args[0], "ffmpeg")
        self.assertEqual(aplay_call_args[0], "aplay")
        self.assertIn("plughw:CARD=sndrpihifiberry,DEV=0", aplay_call_args)


if __name__ == "__main__":
    unittest.main()
