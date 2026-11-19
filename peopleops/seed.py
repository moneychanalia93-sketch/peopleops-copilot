"""Synthetic data for a fictional 60-person company, "Lumen Harbor Labs".

Nothing here is real. Names come from a made-up pool, the random generator uses a
fixed seed so every run produces the same company, and emails use the reserved
".example" domain.
"""
import random
import unicodedata
from datetime import date, timedelta
from itertools import product

from . import onboarding

FIRST = ["Aiden", "Beatriz", "Callum", "Deepa", "Elias", "Farah", "Gideon", "Hana", "Idris", "June",
         "Kofi", "Lena", "Mateo", "Noor", "Oskar", "Petra", "Quinn", "Rohan", "Saoirse", "Takeo",
         "Uma", "Viktor", "Wren", "Ximena", "Yusuf", "Zara", "Anders", "Bianca", "Cyrus", "Delia",
         "Emeka", "Freya", "Gus", "Helena", "Ivo", "Jada", "Kenji", "Leila", "Milo", "Nia"]
LAST = ["Abara", "Brandt", "Castillo", "Desai", "Eriksen", "Fontaine", "Gallagher", "Haddad", "Ito", "Jovanovic",
        "Kowalski", "Laurent", "Mbeki", "Novak", "Okonkwo", "Petrov", "Quigley", "Rossi", "Sato", "Tanaka",
        "Underwood", "Vasquez", "Wei", "Xu", "Yilmaz", "Zielinski", "Ahmed", "Bauer", "Chopra", "Dube",
        "Engel", "Fischer", "Gomez", "Holm", "Iyer", "Jensen", "Kaur", "Lindgren", "Moreau", "Nguyen"]

TEAM_SIZES = {"Engineering": 18, "Product": 6, "Design": 4, "Sales": 9, "Customer Success": 6,
              "Marketing": 5, "People": 3, "Finance": 4, "IT & Security": 3, "Operations": 2}
LEAD_TITLE = {"Product": "Director of Product", "Design": "Head of Design", "Customer Success": "Head of Customer Success",
              "Marketing": "Head of Marketing", "Finance": "Head of Finance", "IT & Security": "Head of IT & Security",
              "Operations": "Operations Manager"}
IC_TITLES = {"Engineering": ["Software Engineer", "Senior Software Engineer", "Site Reliability Engineer", "Data Engineer"],
             "Product": ["Product Manager", "Senior Product Manager"], "Design": ["Product Designer", "UX Researcher"],
             "Sales": ["Account Executive", "Sales Development Rep"], "Customer Success": ["Customer Success Manager", "Support Engineer"],
             "Marketing": ["Content Marketer", "Demand Generation Lead"], "People": ["People Partner", "Recruiter"],
             "Finance": ["Accountant", "Financial Analyst"], "IT & Security": ["IT Specialist", "Security Engineer"],
             "Operations": ["Operations Associate"]}
LOCATIONS = ["US-Remote"] * 8 + ["New York"] * 4 + ["London"] * 5 + ["Toronto"] * 3
JOB_TEAM_WEIGHTS = {"Engineering": 40, "Sales": 20, "Customer Success": 10, "Product": 8, "Marketing": 7,
                    "Design": 5, "Finance": 4, "People": 3, "IT & Security": 3}
STAGES = ["Applied", "Phone screen", "Onsite", "Offer", "Hired"]


def _email(name):
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return plain.replace(" ", ".").replace("'", "") + "@lumenharbor.example"


def _quarter_ends(today, n):
    """The last n calendar quarter-end dates on or before today, oldest first."""
    ends, y, q = [], today.year, (today.month - 1) // 3 + 1
    while len(ends) < n:
        month = q * 3
        last_day = date(y + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
        if last_day <= today:
            ends.append(last_day)
        q -= 1
        if q == 0:
            q, y = 4, y - 1
    return sorted(ends)


def _build_people(rng, today):
    """Return a list of employee dicts. Fixed 'cast' first, so ids E001-E007 are stable."""
    pool = list(product(FIRST, LAST))
    rng.shuffle(pool)
    people = []

    def add(name, team, title, mgr, role="employee", start=None):
        i = len(people) + 1
        people.append({"id": f"E{i:03d}", "name": name, "email": _email(name), "team": team, "title": title,
                       "manager_id": mgr, "location": rng.choice(LOCATIONS), "role": role,
                       "start_date": start or today - timedelta(days=rng.randint(150, 1500)),
                       "end_date": None, "status": "active"})
        return people[-1]["id"]

    def gen():
        first, last = pool.pop()
        return f"{first} {last}"

    ceo = add("Avery Lindqvist", "Operations", "CEO", None, "manager", today - timedelta(days=2000))
    dana = add("Dana Whitfield", "People", "Head of People", ceo, "people", today - timedelta(days=1500))
    marcus = add("Marcus Hale", "Engineering", "VP Engineering", ceo, "manager", today - timedelta(days=1700))
    priya = add("Priya Nair", "Sales", "Sales Director", ceo, "manager", today - timedelta(days=1400))
    tomas = add("Tomás Reyes", "Engineering", "Engineering Manager", marcus, "manager", today - timedelta(days=1100))
    add("Jordan Ellis", "Engineering", "Software Engineer", tomas, "employee", today - timedelta(days=700))
    add("Nadia Okafor", "Engineering", "Software Engineer", tomas, "employee", today - timedelta(days=20))

    # Engineering: second manager, then ICs split 4 -> Tomas, 6 -> manager 2, 3 -> Marcus
    mgr2 = add(gen(), "Engineering", "Engineering Manager", marcus, "manager")
    for mgr, count in ((tomas, 4), (mgr2, 6), (marcus, 3)):
        for _ in range(count):
            add(gen(), "Engineering", rng.choice(IC_TITLES["Engineering"]), mgr)
    # Everyone else: one lead reporting to the CEO, the rest report to the lead
    add(gen(), "Operations", "Operations Associate", ceo)
    for _ in range(2):
        add(gen(), "People", "People Partner", dana, "people")
    for _ in range(8):
        add(gen(), "Sales", rng.choice(IC_TITLES["Sales"]), priya)
    for team in ("Product", "Design", "Customer Success", "Marketing", "Finance", "IT & Security"):
        lead = add(gen(), team, LEAD_TITLE[team], ceo, "manager")
        for _ in range(TEAM_SIZES[team] - 1):
            add(gen(), team, rng.choice(IC_TITLES[team]), lead)
    assert len(people) == 60, len(people)

    # Make 14 generated individual contributors recent hires (started in the last 150 days)
    ics = [p for p in people[7:] if p["role"] == "employee"]
    for p in rng.sample(ics, 14):
        p["start_date"] = today - timedelta(days=rng.randint(6, 150))
    # Six former employees, so headcount history has leavers
    for i in range(6):
        team = rng.choice(["Engineering", "Sales", "Customer Success", "Marketing"])
        start = today - timedelta(days=rng.randint(500, 1400))
        e = {"id": f"E{61 + i:03d}", "name": gen(), "team": team, "title": rng.choice(IC_TITLES[team]),
             "manager_id": None, "location": rng.choice(LOCATIONS), "role": "employee", "start_date": start,
             "end_date": today - timedelta(days=rng.randint(30, 450)), "status": "terminated"}
        e["email"] = _email(e["name"])
        people.append(e)
    return people


def _simulate_plans(conn, rng, today):
    """Give every recent hire an onboarding plan, partly completed according to their start date."""
    rows = conn.execute("SELECT id, start_date FROM employees WHERE status='active' ORDER BY id").fetchall()
    for r in rows:
        start = date.fromisoformat(r["start_date"])
        if (today - start).days > 150:
            continue
        plan_id = onboarding.create_plan(conn, r["id"], start, today=start - timedelta(days=10))
        finished = (today - start).days >= 35
        for t in conn.execute("SELECT id, due_date FROM onboarding_tasks WHERE plan_id=?", (plan_id,)).fetchall():
            due = date.fromisoformat(t["due_date"])
            if finished or due <= today - timedelta(days=2):
                done = min(due + timedelta(days=rng.choice([-2, -1, 0, 0, 0, 0, 1, 3])), today)
                conn.execute("UPDATE onboarding_tasks SET status='done', completed_at=? WHERE id=?",
                             (done.isoformat(), t["id"]))
        if finished:
            conn.execute("UPDATE onboarding_plans SET productive_days=? WHERE id=?", (rng.randint(35, 80), plan_id))


def _seed_applications(conn, rng, today):
    titles = {t: IC_TITLES[t][0] for t in IC_TITLES}
    teams, weights = zip(*JOB_TEAM_WEIGHTS.items())
    for i in range(520):
        team = rng.choices(teams, weights)[0]
        applied = today - timedelta(days=rng.randint(3, 330))
        stage = rng.choices(range(5), [46, 27, 14, 7, 6])[0]
        hired_at, status = None, "rejected"
        if stage == 4:
            days = rng.randint(22, 58) + (8 if team == "Engineering" else 0)
            hired_at, status = min(applied + timedelta(days=days), today).isoformat(), "hired"
        elif applied > today - timedelta(days=45) and rng.random() < 0.6:
            status = "active"
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        conn.execute("INSERT INTO applications VALUES (?,?,?,?,?,?,?,?)",
                     (f"A{i + 1:04d}", name, titles[team], team, stage, status, applied.isoformat(), hired_at))


def seed(conn, today: date | None = None, rng_seed: int = 42):
    """Fill an EMPTY database with the synthetic company. Returns a short summary."""
    today = today or date.today()
    rng = random.Random(rng_seed)
    for p in _build_people(rng, today):
        conn.execute("INSERT INTO employees VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (p["id"], p["name"], p["email"], p["team"], p["title"], p["manager_id"], p["location"],
                      p["start_date"].isoformat(), p["end_date"].isoformat() if p["end_date"] else None,
                      p["status"], p["role"]))
        conn.execute("INSERT INTO comp_private VALUES (?,?)", (p["id"], rng.randint(70, 240) * 1000))
    _simulate_plans(conn, rng, today)
    _seed_applications(conn, rng, today)
    for i, q in enumerate(_quarter_ends(today, 8)):
        conn.execute("INSERT INTO arr_history VALUES (?,?)", (q.isoformat(), int(7_200_000 * 1.09 ** i + rng.randint(-60_000, 60_000))))
    n = conn.execute("SELECT COUNT(*) FROM employees WHERE status='active'").fetchone()[0]
    return {"employees": n, "applications": 520}
