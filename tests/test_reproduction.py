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
        self.assertEqual(result["extended/supplemental"]["scored"], 2880)
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

    def test_extended_execution_with_all_saved_responses(self):
        config = json.loads((ROOT / "configs/extended.json").read_text())
        checked = 0
        for cohort in ("original", "supplemental"):
            lookup = {
                (r["model"], r["id"], r["method"]): r
                for r in records(ROOT, "extended", cohort)
            }
            for model in config["models"]:
                for record in dataset(ROOT, cohort):
                    initial = None
                    for method in METHODS:
                        expected = lookup[model, record["id"], method]
                        test = self

                        class Replay:
                            base = "unused"

                            def __init__(self):
                                self.calls = iter(expected["transport"])
                                self.observed = []

                            def __call__(self, model, prompt, url, timeout):
                                saved = next(self.calls)
                                test.assertEqual(
                                    hashlib.sha256(prompt.encode()).hexdigest(),
                                    saved["prompt_sha256"],
                                )
                                self.observed.append(saved)
                                return (
                                    saved["raw"],
                                    saved["elapsed"],
                                    dict(saved["metadata"]),
                                )

                        transport = Replay()
                        actual = execute_one(
                            record, method, model, config, transport, initial
                        )
                        self.assertEqual(
                            len(transport.observed), len(expected["transport"])
                        )
                        self.assertEqual(
                            hashlib.sha256(
                                canonical(actual["final"]).encode()
                            ).hexdigest(),
                            expected["validation_sha256"],
                        )
                        for field, value in expected["final"].items():
                            self.assertEqual(actual["final"][field], value)
                        self.assertEqual(actual["metrics"], expected["metrics"])
                        if method == "localintent":
                            initial = actual
                        checked += 1
        self.assertEqual(checked, 5360)

    def test_matrix_stop_and_resume(self):
        plan, data = make_plan(ROOT, "extended", "original", ["gemma2:2b"], limit=1)
        saved = [
            r
            for r in records(ROOT, "extended", "original")
            if r["model"] == "gemma2:2b" and r["id"] == data[0]["id"]
        ]
        responses = {c["prompt_sha256"]: c for r in saved for c in r["transport"]}
        performed = []

        def generate(model, prompt, base, settings):
            self.assertNotIn(prompt, performed)
            performed.append(prompt)
            response = responses[hashlib.sha256(prompt.encode()).hexdigest()]
            return response["raw"], response["elapsed"], response["metadata"]

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
                repeated = run(ROOT, destination, plan, data)
                self.assertEqual(repeated["completed"], 4)
                changed = {**plan, "api_base": "different"}
                with self.assertRaises(IntegrityError):
                    run(ROOT, destination, changed, data)
            self.assertEqual(len(performed), 5)
            self.assertEqual(
                json.loads((destination / "status.json").read_text())["status"],
                "complete",
            )

    def test_configuration_distinguishes_experiments(self):
        paper, _ = make_plan(ROOT, "paper", "original")
        extended, _ = make_plan(ROOT, "extended", "supplemental")
        self.assertEqual(paper["evaluations"], 2480)
        self.assertEqual(extended["evaluations"], 2880)
        self.assertFalse(paper["config"]["shared_initial"])
        self.assertTrue(extended["config"]["shared_initial"])
        with self.assertRaises(ValueError):
            make_plan(ROOT, "paper", "supplemental")


if __name__ == "__main__":
    unittest.main()
