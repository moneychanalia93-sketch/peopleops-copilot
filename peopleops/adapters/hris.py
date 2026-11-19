"""HR system of record: BambooHR.

Interface:
  create_employee(name, email, team, title, manager_id, location, start_date) -> employee id
  get_employee(employee_id) -> dict or None
"""
from .http import basic_auth, call_json


class MockBambooHR:
    """Writes to the local `employees` table with status 'pre-start' until their start date."""

    def __init__(self, conn):
        self.conn = conn

    def create_employee(self, name, email, team, title, manager_id, location, start_date):
        n = self.conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        emp_id = f"E{n + 1:03d}"
        self.conn.execute(
            "INSERT INTO employees (id,name,email,team,title,manager_id,location,start_date,status,role) "
            "VALUES (?,?,?,?,?,?,?,?,'pre-start','employee')",
            (emp_id, name, email, team, title, manager_id, location, start_date))
        return emp_id

    def get_employee(self, employee_id):
        row = self.conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
        return dict(row) if row else None


class BambooHRAPI:
    """REAL stub.
      Base:   https://api.bamboohr.com/api/gateway.php/{subdomain}/v1
      Auth:   HTTP Basic, API key as username, any string as password.
      Create: POST {base}/employees/   body {"firstName","lastName","workEmail","department","jobTitle","hireDate","location"}
              BambooHR returns the new id in the `Location` response HEADER. `call_json` only returns the body,
              so a live version must also read that header. Known gap, listed in the README.
      Read:   GET  {base}/employees/{id}?fields=firstName,lastName,department,jobTitle
    Docs: https://documentation.bamboohr.com/reference.  NOT run against a live account.
    """

    def __init__(self, subdomain, api_key):
        self.base = f"https://api.bamboohr.com/api/gateway.php/{subdomain}/v1"
        self.headers = {"Authorization": basic_auth(api_key, "x")}

    def create_employee(self, name, email, team, title, manager_id, location, start_date):
        first, _, last = name.partition(" ")
        body = {"firstName": first, "lastName": last, "workEmail": email, "department": team,
                "jobTitle": title, "hireDate": start_date, "location": location}
        reply = call_json("POST", f"{self.base}/employees/", self.headers, body)
        return str(reply.get("id", ""))

    def get_employee(self, employee_id):
        return call_json("GET", f"{self.base}/employees/{employee_id}?fields=firstName,lastName,department,jobTitle",
                         self.headers)
