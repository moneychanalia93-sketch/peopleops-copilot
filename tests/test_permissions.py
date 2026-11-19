import unittest

from peopleops import analytics, audit, onboarding, permissions
from peopleops.tools import run_tool
from tests.helpers import make_conn, make_ctx


class PermissionTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()

    def can(self, actor, target):
        return permissions.can_view_employee(self.conn, permissions.get_employee(self.conn, actor), target)

    def test_employee_sees_only_self(self):
        self.assertTrue(self.can("E006", "E006"))
        self.assertFalse(self.can("E006", "E007"))

    def test_manager_sees_direct_reports_only(self):
        self.assertTrue(self.can("E005", "E007"))   # Tomas manages Nadia
        self.assertFalse(self.can("E003", "E007"))  # Marcus is her skip-level: not a direct report
        self.assertFalse(self.can("E005", "E003"))

    def test_people_team_sees_everyone(self):
        self.assertTrue(self.can("E002", "E007") and self.can("E002", "E003"))

    def test_onboarding_tool_enforces_it_and_logs_denial(self):
        ctx = make_ctx(self.conn, "E006")
        result = run_tool(ctx, "get_onboarding_status", {"employee": "Nadia Okafor"})
        self.assertEqual(result["error"], "not_permitted")
        self.assertIn("permission.denied", [r["action"] for r in audit.recent(self.conn)])
        self.assertNotIn("pct", result)

    def test_manager_can_read_report_status(self):
        result = run_tool(make_ctx(self.conn, "E005"), "get_onboarding_status", {"employee": "Nadia Okafor"})
        self.assertTrue(result["found"])

    def test_plan_list_is_scoped(self):
        self.assertEqual({p["employee_id"] for p in onboarding.list_plans(self.conn, permissions.get_employee(self.conn, "E007"))}, {"E007"})
        self.assertGreater(len(onboarding.list_plans(self.conn, permissions.get_employee(self.conn, "E002"))), 10)

    def test_manager_only_handbook_hidden_from_employees(self):
        from peopleops.retrieval import get_handbook
        q = "When do I have to submit my interview scorecard?"
        self.assertEqual(get_handbook().search(q, ("all",)), [])
        self.assertTrue(get_handbook().search(q, ("all", "managers")))

    def test_no_tool_can_read_compensation(self):
        from peopleops.tools import TOOLS
        import inspect, peopleops.tools as mod
        self.assertNotIn("comp_private", inspect.getsource(mod))
        self.assertEqual(len(TOOLS), 6)


class KAnonymityAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()

    def test_small_teams_hidden_in_headcount(self):
        teams = {t["team"]: t for t in analytics.headcount_by_team(self.conn)}
        self.assertTrue(teams["People"]["suppressed"] and teams["People"]["n"] is None)   # 3 people
        self.assertTrue(teams["Operations"]["suppressed"])                                 # 2 people
        self.assertEqual(teams["Engineering"]["n"], 18)

    def test_every_visible_cell_is_at_least_five(self):
        o = analytics.overview(self.conn, permissions.get_employee(self.conn, "E002"))
        cells = [t["n"] for t in o["headcount_by_team"] + o["time_to_hire"]["by_team"] + o["onboarding"]["time_to_productive_by_team"] if t["n"] is not None]
        self.assertTrue(cells and all(n >= 5 for n in cells))

    def test_manager_with_small_team_gets_no_insights(self):
        small = analytics.manager_insights(self.conn, "E005")        # Tomas has 6 reports -> shown
        self.assertFalse(small["suppressed"])
        self.conn.execute("UPDATE employees SET manager_id='E001' WHERE manager_id='E005' AND id NOT IN ('E006','E007')")
        self.assertTrue(analytics.manager_insights(self.conn, "E005")["suppressed"])  # now 2 reports

    def test_employees_get_no_company_analytics(self):
        self.assertEqual(analytics.overview(self.conn, permissions.get_employee(self.conn, "E006"))["scope"], "none")


if __name__ == "__main__":
    unittest.main()
