"""Which recording device the tray switch picks. No Windows calls are made."""

from __future__ import annotations

import unittest

from soundcore_diag.cable import is_standard_cable_output
from soundcore_diag.mic_switch import Endpoint, Mics

CABLE = Endpoint("cable", "CABLE Output (VB-Audio Virtual Cable)")
ARRAY = Endpoint("array", "麦克风阵列 (适用于数字麦克风的英特尔® 智音技术)")
HEADSET = Endpoint("headset", "耳机麦克风 (USB Audio)")


class MicSwitchTests(unittest.TestCase):
    def test_only_the_standard_cable_output_is_the_bean(self) -> None:
        self.assertTrue(is_standard_cable_output("CABLE Output (VB-Audio Virtual Cable)"))
        self.assertTrue(is_standard_cable_output("CABLE Output"))
        self.assertFalse(is_standard_cable_output("CABLE Input (VB-Audio Virtual Cable)"))
        self.assertFalse(is_standard_cable_output("CABLE-A Output (VB-Audio Cable A)"))
        self.assertFalse(is_standard_cable_output("麦克风阵列"))

    def test_current(self) -> None:
        self.assertEqual(Mics("cable", (CABLE, ARRAY)).current, "bean")
        self.assertEqual(Mics("array", (CABLE, ARRAY)).current, "system")
        self.assertEqual(Mics("", (CABLE, ARRAY)).current, "")

    def test_going_back_prefers_the_microphone_used_before(self) -> None:
        mics = Mics("cable", (CABLE, ARRAY, HEADSET))
        self.assertEqual(mics.system("headset"), HEADSET)
        self.assertEqual(mics.system("gone"), ARRAY)
        self.assertEqual(Mics("headset", (CABLE, ARRAY, HEADSET)).system(), HEADSET)

    def test_missing_devices(self) -> None:
        self.assertIsNone(Mics("array", (ARRAY,)).bean)
        self.assertIsNone(Mics("cable", (CABLE,)).system())
        two = Endpoint("cable2", "CABLE Output (VB-Audio Virtual Cable)")
        self.assertIsNone(Mics("array", (CABLE, two, ARRAY)).bean)


if __name__ == "__main__":
    unittest.main()
