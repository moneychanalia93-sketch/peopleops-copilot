import contextlib
import io
import unittest
import unittest.mock

from peopleops import evaluate
from peopleops.llm import MockModel


class EvalGateTests(unittest.TestCase):
    def test_golden_set_is_big_enough_and_covers_every_route(self):
        cases = evaluate.load_cases()
        self.assertGreaterEqual(len(cases), 40)
        self.assertEqual({c["expected_route"] for c in cases}, {"answer", "action", "escalate", "block"})
        self.assertEqual({c["sensitive_category"] for c in cases if c["sensitive_category"]},
                         {"compensation", "immigration", "medical_leave", "harassment_complaint", "termination_performance", "legal"})
        self.assertGreaterEqual(sum("adversarial" in c["tags"] for c in cases), 10)

    def test_shipped_system_passes_the_gate(self):
        report = evaluate.run_eval(model=MockModel())
        s = report["summary"]["all"]
        self.assertEqual(s["escalation_recall_pct"], 100.0)
        self.assertEqual(s["sensitive_answered_by_ai"], 0)
        self.assertTrue(evaluate.passes_gate(report))

    def test_gate_fails_when_recall_drops(self):
        report = evaluate.run_eval(model=MockModel())
        report["summary"]["all"]["escalation_recall_pct"] = 97.5
        self.assertFalse(evaluate.passes_gate(report))

    def test_gate_fails_when_ai_answers_a_sensitive_case(self):
        report = evaluate.run_eval(model=MockModel())
        report["summary"]["all"]["sensitive_answered_by_ai"] = 1
        self.assertFalse(evaluate.passes_gate(report))

    def test_main_returns_zero_for_the_shipped_system(self):
        self.assertEqual(evaluate.main(write_report=False), 0)

    def test_main_exits_nonzero_when_the_gate_fails(self):
        """What a CI pipeline sees: a failing gate gives exit code 1."""
        bad = evaluate.run_eval(model=MockModel())
        bad["summary"]["all"]["escalation_recall_pct"] = 98.0
        with unittest.mock.patch("peopleops.evaluate.run_eval", return_value=bad), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(evaluate.main(write_report=False), 1)


if __name__ == "__main__":
    unittest.main()
