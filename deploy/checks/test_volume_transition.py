import unittest

from check_volume_transition import assert_safe_transition


class VolumeTransitionTests(unittest.TestCase):
    def test_legacy_container_or_orphan_volume_blocks_startup(self):
        with self.assertRaises(RuntimeError):
            assert_safe_transition("new", [{"Destination": "/var/lib/postgresql", "Name": "old"}], ["old"])
        with self.assertRaises(RuntimeError):
            assert_safe_transition("new", [], ["old"])

    def test_fresh_or_already_transitioned_stack_is_allowed(self):
        assert_safe_transition("new", [], [])
        assert_safe_transition("new", [{"Destination": "/var/lib/postgresql", "Name": "new"}], ["old"])


if __name__ == "__main__":
    unittest.main()
