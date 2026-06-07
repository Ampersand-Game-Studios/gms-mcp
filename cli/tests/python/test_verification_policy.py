import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gms_mcp.server.verification_policy import (
    clear_pending_compile_verification,
    current_verification_mode,
    decide_mutation_verification,
    flush_pending_compile_verification,
    get_pending_compile_verification,
    mark_compile_verification_pending,
)
from gms_helpers.transactions import compile_verify_project


class TestVerificationPolicy(unittest.TestCase):
    def test_default_mode_is_smart_when_env_is_absent(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GMS_MCP_POST_MUTATION_VERIFY", None)
            os.environ.pop("GMS_MCP_VERIFY_COMPILE_AFTER_MUTATION", None)

            self.assertEqual(current_verification_mode(), "smart")

    def test_explicit_off_keeps_post_mutation_compile_disabled(self):
        with patch.dict(os.environ, {"GMS_MCP_POST_MUTATION_VERIFY": "off"}, clear=False):
            decision = decide_mutation_verification("gm_create_script")

        self.assertEqual(decision.mode, "off")
        self.assertEqual(decision.action, "skip")

    def test_smart_mode_compiles_high_risk_and_defers_batchable_tools(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GMS_MCP_POST_MUTATION_VERIFY", None)
            os.environ.pop("GMS_MCP_VERIFY_COMPILE_AFTER_MUTATION", None)

            high_risk = decide_mutation_verification("gm_create_script")
            batchable = decide_mutation_verification("gm_sprite_add_frame")

        self.assertEqual(high_risk.mode, "smart")
        self.assertEqual(high_risk.action, "compile")
        self.assertEqual(batchable.mode, "smart")
        self.assertEqual(batchable.action, "defer")

    def test_pending_compile_state_round_trips_and_clears(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            decision = decide_mutation_verification("gm_sprite_add_frame")
            pending = mark_compile_verification_pending(
                root,
                tool_name="gm_sprite_add_frame",
                decision=decision,
                transaction={"changes": {"changed_count": 2}},
            )

            self.assertEqual(pending["operation_count"], 1)
            self.assertTrue(get_pending_compile_verification(root)["required"])

            cleared = clear_pending_compile_verification(root)

            self.assertEqual(cleared["operation_count"], 1)
            self.assertIsNone(get_pending_compile_verification(root))

    def test_flush_skips_when_no_pending_marker_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            result = flush_pending_compile_verification(root)

        self.assertTrue(result["ok"])
        self.assertFalse(result["compiled"])

    def test_compile_verify_accepts_completed_compile_stage_by_default(self):
        completed = subprocess.CompletedProcess(
            args=["gms"],
            returncode=1,
            stdout="Final Compile finished.\nSaving IFF file... game.ios\nIgor complete.\nrunner failed later",
            stderr="",
        )

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("gms_helpers.transactions.subprocess.run", return_value=completed),
        ):
            result = compile_verify_project(temp_dir, platform="macOS", runtime="VM", timeout_seconds=1)

        self.assertTrue(result["ok"])
        self.assertTrue(result["compile_stage_ok"])
        self.assertTrue(result["accepted_compile_stage_success"])
        self.assertEqual(result["exit_code"], 1)

    def test_compile_verify_can_require_process_success(self):
        completed = subprocess.CompletedProcess(
            args=["gms"],
            returncode=1,
            stdout="Final Compile finished.\nSaving IFF file... game.ios\nIgor complete.\nrunner failed later",
            stderr="",
        )

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.dict(os.environ, {"GMS_MCP_POST_MUTATION_ACCEPT_COMPILE_STAGE_SUCCESS": "off"}, clear=False),
            patch("gms_helpers.transactions.subprocess.run", return_value=completed),
        ):
            result = compile_verify_project(temp_dir, platform="macOS", runtime="VM", timeout_seconds=1)

        self.assertFalse(result["ok"])
        self.assertTrue(result["compile_stage_ok"])
        self.assertFalse(result["accepted_compile_stage_success"])
