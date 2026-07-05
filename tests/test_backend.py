import datetime
import os
import tempfile
import unittest
from unittest import mock

# pylint: disable=no-value-for-parameter


_TEST_DIR = tempfile.mkdtemp(prefix="kali_glass_tests_")
os.environ["KALI_GLASS_CONFIG"] = os.path.join(_TEST_DIR, "config.json")
os.environ["KALI_GLASS_LOG"] = os.path.join(_TEST_DIR, "kali_glass.log")

import kali_glass as kg  # noqa: E402


def make_settings(**overrides):
    data = {
        "brightness": 100,
        "contrast": 50,
        "gamma": 100,
        "temp": 6500,
        "r": 100,
        "g": 100,
        "b": 100,
        "vib": 0,
        "hue": 0,
        "monitor": None,
        "reset": False,
    }
    data.update(overrides)
    return kg.DisplaySettings(**data)


def gamma_values(gamma_str):
    return [float(part) for part in gamma_str.split(":")]


class BackendMathTests(unittest.TestCase):
    def test_brightness_percent_maps_directly_to_xrandr_value(self):
        for percent, expected in ((100, 1.0), (50, 0.5), (10, 0.1), (1, 0.05)):
            brightness, gamma = kg.DisplayEngine._compute_gamma(
                make_settings(brightness=percent)
            )
            self.assertAlmostEqual(brightness, expected)
            self.assertEqual(gamma, "1.000:1.000:1.000")

    def test_gamma_values_are_clamped_to_safe_xrandr_range(self):
        _, high_gamma = kg.DisplayEngine._compute_gamma(
            make_settings(gamma=200, contrast=100)
        )
        self.assertEqual(high_gamma, "3.000:3.000:3.000")

        _, low_gamma = kg.DisplayEngine._compute_gamma(
            make_settings(gamma=50, contrast=1, temp=1000, r=10, g=10, b=10)
        )
        self.assertEqual(low_gamma, "0.300:0.300:0.300")

    def test_rgb_channels_independently_affect_gamma(self):
        _, gamma = kg.DisplayEngine._compute_gamma(
            make_settings(r=50, g=100, b=25)
        )
        red, green, blue = gamma_values(gamma)
        self.assertLess(red, green)
        self.assertLessEqual(blue, red)
        self.assertGreaterEqual(min(red, green, blue), kg.GAMMA_XRANDR_MIN)


class BackendParsingTests(unittest.TestCase):
    def test_connected_output_parsing_from_xrandr_query(self):
        sample = """
Screen 0: minimum 8 x 8, current 1680 x 1050, maximum 32767 x 32767
DVI-D-0 disconnected (normal left inverted right x axis y axis)
HDMI-0 connected 1680x1050+0+0 (normal left inverted right x axis y axis)
DP-0 disconnected (normal left inverted right x axis y axis)
eDP-1 connected primary 1920x1080+1680+0 (normal left inverted right x axis y axis)
"""
        self.assertEqual(kg.parse_xrandr_outputs(sample), ["HDMI-0", "eDP-1"])

    def test_wayland_warning_behavior(self):
        wayland_env = {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}
        self.assertIn(
            "Wayland",
            kg.display_unavailable_reason(wayland_env, "/usr/bin/xrandr"),
        )

        x11_env = {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}
        self.assertEqual(
            kg.display_unavailable_reason(x11_env, "/usr/bin/xrandr"),
            "",
        )

    def test_brightnessctl_fallback_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.mkdir(os.path.join(tmp, "intel_backlight"))
            self.assertTrue(kg.brightnessctl_available("/usr/bin/brightnessctl", tmp))
            with mock.patch.object(kg.shutil, "which", return_value=None):
                self.assertFalse(kg.brightnessctl_available(None, tmp))

    def test_stop_disable_user_service_stops_enabled_redshift_service(self):
        calls = []

        def fake_run(cmd, *args, **kwargs):
            calls.append(cmd)
            if cmd[2] == "show":
                return True, "ActiveState=active\nSubState=running\nUnitFileState=enabled\n", ""
            return True, "", ""

        with mock.patch.object(kg, "run_cmd", side_effect=fake_run):
            result = kg.stop_disable_user_service(
                "redshift.service", "/usr/bin/systemctl"
            )

        self.assertTrue(result["stop_ok"])
        self.assertTrue(result["disable_ok"])
        self.assertIn(
            ["/usr/bin/systemctl", "--user", "stop", "redshift.service"],
            calls,
        )
        self.assertIn(
            ["/usr/bin/systemctl", "--user", "disable", "redshift.service"],
            calls,
        )


class BackendDispatchTests(unittest.TestCase):
    def test_latest_settings_queue_prevents_overlapping_dispatch(self):
        engine = kg.DisplayEngine.__new__(kg.DisplayEngine)
        engine._proc_busy = True
        engine._pending_settings = "old"
        calls = []
        engine._dispatch = lambda snap: calls.append(snap)

        self.assertFalse(kg.DisplayEngine._queue_or_dispatch(engine, "new"))
        self.assertEqual(engine._pending_settings, "new")
        self.assertEqual(calls, [])

        engine._proc_busy = False
        self.assertTrue(kg.DisplayEngine._queue_or_dispatch(engine, "run"))
        self.assertEqual(calls, ["run"])

    def test_reset_command_generation(self):
        engine = kg.DisplayEngine.__new__(kg.DisplayEngine)
        self.assertEqual(
            kg.DisplayEngine._build_reset_xrandr_args(engine, ["HDMI-0"]),
            ["--output", "HDMI-0", "--brightness", "1.0", "--gamma", "1:1:1"],
        )

    def test_unchanged_successful_command_is_not_dispatched_again(self):
        class FakeStatus:
            def __init__(self):
                self.ok_messages = []

            def set_ok(self, message):
                self.ok_messages.append(message)

        class FakeUi:
            def __init__(self):
                self.status = FakeStatus()

        engine = kg.DisplayEngine.__new__(kg.DisplayEngine)
        engine.xrandr_path = "/usr/bin/xrandr"
        engine.ui = FakeUi()
        engine._last_successful_cmd_str = (
            "/usr/bin/xrandr --output HDMI-0 --brightness 1.000 "
            "--gamma 1.000:1.000:1.000"
        )
        engine._last_cmd_str = ""
        engine._last_applied_info = None
        engine._apply_had_error = False
        engine._proc_busy = False

        kg.DisplayEngine._dispatch(engine, make_settings(monitor="HDMI-0"))

        self.assertFalse(engine._proc_busy)
        self.assertEqual(engine._last_cmd_str, engine._last_successful_cmd_str)
        self.assertEqual(len(engine.ui.status.ok_messages), 1)

    def test_external_color_services_are_suppressed_once_only(self):
        engine = kg.DisplayEngine.__new__(kg.DisplayEngine)
        engine._external_color_suppressed = False
        engine.redshift_path = "/usr/bin/redshift"
        engine.systemctl_path = "/usr/bin/systemctl"
        service_calls = []
        redshift_calls = []
        terminated = []

        def fake_run(cmd, *args, **kwargs):
            redshift_calls.append((cmd, kwargs))
            return True, "", ""

        def fake_stop_disable(service, systemctl_path):
            service_calls.append((service, systemctl_path))
            return {
                "service": service,
                "available": True,
                "before": {"ActiveState": "active", "UnitFileState": "enabled"},
                "stop_ok": True,
                "disable_ok": True,
                "after": {"ActiveState": "inactive", "UnitFileState": "disabled"},
            }

        def fake_terminate(process_name):
            terminated.append(process_name)
            return [1234] if process_name == "redshift" else []

        with mock.patch.object(kg, "run_cmd", side_effect=fake_run), \
             mock.patch.object(kg, "stop_disable_user_service", side_effect=fake_stop_disable), \
             mock.patch.object(kg, "terminate_processes_by_name", side_effect=fake_terminate):
            kg.DisplayEngine._suppress_external_color_once(engine)
            kg.DisplayEngine._suppress_external_color_once(engine)

        self.assertEqual(len(service_calls), len(kg.EXTERNAL_COLOR_SERVICES))
        self.assertEqual(redshift_calls, [(["/usr/bin/redshift", "-x"], {"silent": False})])
        self.assertEqual(terminated, list(kg.EXTERNAL_COLOR_PROCESSES))

    def test_quit_keeps_current_display_settings(self):
        class FakeApp:
            def __init__(self):
                self.quit_called = False

            def quit(self):
                self.quit_called = True

        engine = kg.DisplayEngine.__new__(kg.DisplayEngine)
        engine._pending_settings = "pending"
        stop_calls = []
        save_calls = []
        fake_app = FakeApp()
        engine._stop_proc_cleanly = lambda: stop_calls.append(True)
        engine.save_settings = lambda: save_calls.append(True)

        with mock.patch.object(kg.QApplication, "instance", return_value=fake_app), \
             mock.patch.object(kg, "run_cmd") as run_cmd:
            kg.DisplayEngine._quit_cleanly(engine)

        self.assertIsNone(engine._pending_settings)
        self.assertEqual(stop_calls, [True])
        self.assertEqual(save_calls, [True])
        self.assertTrue(fake_app.quit_called)
        run_cmd.assert_not_called()


class ScheduleTests(unittest.TestCase):
    def test_auto_schedule_applies_configured_night_temperature(self):
        class FakeCheck:
            def isChecked(self):
                return True

        class FakeTimeEdit:
            def __init__(self, hour, minute):
                self._time = kg.QTime(hour, minute)

            def time(self):
                return self._time

        class FakeSlider:
            def __init__(self):
                self.values = []

            def set_value(self, value):
                self.values.append(value)

        class FakeUi:
            def __init__(self):
                self.check_auto = FakeCheck()
                self.time_on = FakeTimeEdit(17, 0)
                self.time_off = FakeTimeEdit(6, 0)
                self.sl_temp = FakeSlider()
                self.sl_bright = FakeSlider()
                self.night_status = []

            def set_night_status(self, active):
                self.night_status.append(active)

        class FixedDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 1, 1, 18, 0, tzinfo=tz)

        engine = kg.DisplayEngine.__new__(kg.DisplayEngine)
        engine.ui = FakeUi()
        engine._last_schedule_state = None
        apply_calls = []
        engine.apply_settings = lambda: apply_calls.append(True)

        with mock.patch.object(kg.datetime, "datetime", FixedDatetime):
            kg.DisplayEngine._check_auto_schedule(engine, force=True)

        self.assertEqual(engine.ui.sl_temp.values, [kg.NIGHT_TEMP_DEF])
        self.assertEqual(engine.ui.sl_bright.values, [70])
        self.assertEqual(engine.ui.night_status, [True])
        self.assertEqual(apply_calls, [True])


if __name__ == "__main__":
    unittest.main()
