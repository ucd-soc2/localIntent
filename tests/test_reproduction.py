"""Regression tests for recorded research outcomes and durable inference."""

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from localintent import core
from localintent.artifacts import METHODS, canonical, dataset, records
from localintent.evaluation.verify import verify_release
from localintent.experiments.checkpoints import IntegrityError, load, seal
from localintent.experiments.runner import execute_one, make_plan, run
from localintent.inference import Transport, TransportError


class ReproductionTests(unittest.TestCase):
    def test_complete_saved_experiments(self):
        result = verify_release(ROOT)
        self.assertEqual(result["paper/original"]["evaluations"], 2480)
        self.assertEqual(result["paper/original"]["scored"], 2479)
        self.assertEqual(
            result["paper_checker_counts"]["passed_with_metric_failure"], 282
        )

    def test_checkpoint_corruption_and_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "result.json"
            seal(path, {"value": 1}, {"model": "test"})
            self.assertEqual(load(path, {"model": "test"}), {"value": 1})
            with self.assertRaises(IntegrityError):
                load(path, {"model": "other"})
            changed = json.loads(path.read_text())
            changed["data"]["value"] = 2
            path.write_text(json.dumps(changed))
            with self.assertRaises(IntegrityError):
                load(path)

    def test_transport_resume_and_prompt_change(self):
        with tempfile.TemporaryDirectory() as temp:
            calls = []

            def generate(*args):
                calls.append(args)
                return "invalid model JSON", 0.1, {"done_reason": "stop"}

            identity = {"model": "test"}
            first = Transport(Path(temp), identity, "unused", {}, generate)
            first("test", "prompt", "unused", 1)
            resumed = Transport(Path(temp), identity, "unused", {}, generate)
            self.assertEqual(
                resumed("test", "prompt", "unused", 1)[0], "invalid model JSON"
            )
            self.assertEqual(len(calls), 1)
            changed = Transport(Path(temp), identity, "unused", {}, generate)
            with self.assertRaises(IntegrityError):
                changed("test", "different prompt", "unused", 1)

    def test_failed_transport_never_commits_result(self):
        with tempfile.TemporaryDirectory() as temp:
            calls = []

            def fail(*args):
                calls.append(args)
                raise TimeoutError("interrupted stream")

            transport = Transport(Path(temp), {"model": "test"}, "unused", {}, fail)
            with (
                patch("localintent.inference.time.sleep"),
                self.assertRaises(TransportError),
            ):
                transport("test", "prompt", "unused", 1)
            self.assertEqual(len(calls), 3)
            self.assertFalse((Path(temp) / "call_0.json").exists())

    def test_generation_excludes_reference(self):
        original = dataset(ROOT, "original")[0]
        altered = copy.deepcopy(original)
        altered["reference"] = {"secret_reference": "must never reach the model"}
        config = json.loads((ROOT / "configs/paper.json").read_text())
        response = json.dumps(original["reference"])

        class FakeTransport:
            base = "unused"
            observed = []

            def __init__(self):
                self.prompts = []

            def __call__(self, model, prompt, url, timeout):
                self.prompts.append(prompt)
                return (
                    ('{"mode": "ordinary"}' if len(self.prompts) == 1 else response),
                    0.1,
                    {"elapsed_time_sec": 0.1},
                )

        first = FakeTransport()
        second = FakeTransport()
        execute_one(original, "localintent", "test", config, first)
        # Replace only the scorer for an intentionally malformed reference.
        with patch("localintent.experiments.runner.score_output", return_value=None):
            execute_one(altered, "localintent", "test", config, second)
        self.assertEqual(first.prompts, second.prompts)
        self.assertNotIn("secret_reference", "".join(second.prompts))

    def test_paper_repair_executor_with_saved_responses(self):
        source = next(
            r
            for r in records(ROOT, "paper")
            if r["method"] == "semantic_repair" and not r["repair"]["triggered"]
        )
        record = next(r for r in dataset(ROOT, "original") if r["id"] == source["id"])
        responses = iter([source["gate_raw_response"], source["raw_output"]])

        class FakeTransport:
            base = "unused"
            observed = []

            def __call__(self, *args):
                return next(responses), 0.1, {"elapsed_time_sec": 0.1}

        config = json.loads((ROOT / "configs/paper.json").read_text())
        row = execute_one(
            record, "semantic_repair", source["model"], config, FakeTransport()
        )
        self.assertEqual(row["final"]["output"], source["final"]["output"])
        self.assertEqual(row["metrics"], source["metrics"])
        self.assertEqual(row["initial_raw_output"], source["raw_output"])

    def test_matrix_stop_and_resume(self):
        plan, data = make_plan(ROOT, "paper", "original", ["gemma2:2b"], limit=1)
        performed = []

        def generate(model, prompt, base, settings):
            performed.append(prompt)
            return '{}', 0.1, {"elapsed_time_sec": 0.1}

        def transport(directory, identity, base, settings):
            return Transport(directory, identity, base, settings, generate)

        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp)
            with (
                patch(
                    "localintent.experiments.runner.inspect_models",
                    return_value={"gemma2:2b": {"digest": "test"}},
                ),
                patch("localintent.experiments.runner.prepare_model"),
                patch(
                    "localintent.experiments.runner.Transport", side_effect=transport
                ),
                patch("localintent.experiments.runner.time.sleep"),
            ):
                partial = run(ROOT, destination, plan, data, max_new=2)
                self.assertEqual(partial["completed"], 2)
                resumed = run(ROOT, destination, plan, data)
                self.assertEqual(resumed["completed"], 4)
                calls_after_resume = len(performed)
                repeated = run(ROOT, destination, plan, data)
                self.assertEqual(len(performed), calls_after_resume)
                self.assertEqual(repeated["completed"], 4)
                changed = {**plan, "api_base": "different"}
                with self.assertRaises(IntegrityError):
                    run(ROOT, destination, changed, data)
            self.assertEqual(
                json.loads((destination / "status.json").read_text())["status"],
                "complete",
            )

    def test_paper_configuration(self):
        paper, _ = make_plan(ROOT, "paper", "original")
        self.assertEqual(paper["evaluations"], 2480)
        self.assertFalse(paper["config"]["shared_initial"])
        with self.assertRaises(ValueError):
            make_plan(ROOT, "paper", "unknown")


if __name__ == "__main__":
    unittest.main()
