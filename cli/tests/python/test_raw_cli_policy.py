#!/usr/bin/env python3
"""Regression coverage for the read-only raw helper-CLI policy."""

from __future__ import annotations

import unittest

from gms_mcp.server.raw_cli_policy import evaluate_gm_cli_args, raw_cli_blocked_result


class TestRawCLIReadOnlyPolicy(unittest.TestCase):
    def test_allows_explicit_read_only_commands(self):
        cases = {
            ("--help",): (),
            ("event", "list", "o_player"): ("event", "list"),
            ("event", "validate", "o_player"): ("event", "validate"),
            ("maintenance", "validate-json"): ("maintenance", "validate-json"),
            ("room", "ops", "list"): ("room", "ops", "list"),
            ("texture-groups", "show", "Default"): ("texture-groups", "show"),
        }

        for args, command_path in cases.items():
            with self.subTest(args=args):
                decision = evaluate_gm_cli_args(list(args))
                self.assertTrue(decision.allowed)
                self.assertEqual(decision.command_path, command_path)

    def test_blocks_mutating_or_non_allowlisted_commands(self):
        cases = (
            ["asset", "delete", "script", "scr_unsafe"],
            ["maintenance", "auto", "--fix"],
            ["run", "compile"],
            ["telemetry", "enable"],
            ["doc", "cache", "clear"],
            ["skills", "install", "--project"],
        )

        for args in cases:
            with self.subTest(args=args):
                self.assertFalse(evaluate_gm_cli_args(args).allowed)

    def test_blocks_raw_global_options_and_malformed_args(self):
        for option in ("--project-root=../other", "--project-ro=../other", "--telemet=on"):
            with self.subTest(option=option):
                global_option = evaluate_gm_cli_args(["event", "list", "o_player", option])
                self.assertFalse(global_option.allowed)
                self.assertIn("global CLI options", global_option.reason)

        for args in ([], "event list", ["event", ""], ["event", 1]):
            with self.subTest(args=args):
                self.assertFalse(evaluate_gm_cli_args(args).allowed)

    def test_blocked_result_is_structured_without_echoing_raw_arguments(self):
        decision = evaluate_gm_cli_args(["asset", "delete", "script", "scr_secret"])
        result = raw_cli_blocked_result(decision)

        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked_by_policy"])
        self.assertEqual(result["policy"], "gm_cli_read_only")
        self.assertNotIn("args", result)
        self.assertNotIn("scr_secret", str(result))


if __name__ == "__main__":
    unittest.main()
