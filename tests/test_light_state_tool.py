import unittest

from tools.harmonize_light_state import parser


class LightStateToolTests(unittest.TestCase):
    def test_mutating_action_requires_separate_area_confirmation_option(self):
        args = parser().parse_args(
            ["restore", "--confirm-area", "TV area", "--allow-stale"]
        )
        self.assertEqual(args.action, "restore")
        self.assertEqual(args.confirm_area, "TV area")
        self.assertTrue(args.allow_stale)

    def test_inspect_is_available_without_mutation_flags(self):
        args = parser().parse_args(["inspect"])
        self.assertEqual(args.action, "inspect")
        self.assertIsNone(args.confirm_area)
        self.assertFalse(args.allow_stale)


if __name__ == "__main__":
    unittest.main()
