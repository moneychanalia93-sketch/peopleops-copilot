"""Command line: `python -m peopleops <command>`.

  demo         seed data, send a signed hire webhook, chat, run eval, open the dashboard
  serve        start the dashboard + webhook server on http://127.0.0.1:8765
  seed         (re)create the synthetic company in var/peopleops.db
  eval         run the golden set; exit code 1 if escalation recall < 100%
  chat "..."   ask the agent one question  (--as E006 to choose who is asking)
  approvals    list the queue;  approvals approve 3 --as E002;  approvals reject 3 --as E002
  audit        show the audit log;  audit --verify checks the hash chain
  sample-hire  POST a signed sample hire event to a running server
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

from . import adapters, agent, approvals, audit, config, db, evaluate, seed
from .context import Ctx
from .tools import decide_approval


def _conn():
    return db.connect(config.db_path())


def cmd_seed(args):
    path = config.db_path()
    if args.fresh:
        for suffix in ("", "-wal", "-shm"):
            try:
                import os
                os.remove(path + suffix)
            except FileNotFoundError:
                pass
    conn = _conn()
    if conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]:
        print("Database already has data. Use `seed --fresh` to recreate it.")
        return 0
    print("Seeded:", seed.seed(conn), "->", path)
    return 0


def cmd_chat(args):
    conn = _conn()
    out = agent.handle_message(Ctx.for_user(conn, args.as_user, adapters.build(conn)), args.message)
    print(f"[{out['route'].upper()}] {out['text']}")
    if out["citations"]:
        print("Sources:", ", ".join(out["citations"]))
    return 0


def cmd_approvals(args):
    conn = _conn()
    if args.action in ("approve", "reject"):
        ctx = Ctx.for_user(conn, args.as_user, adapters.build(conn))
        print(json.dumps(decide_approval(ctx, args.id, args.action == "approve", args.reason or ""), indent=2))
        return 0
    for a in approvals.list_all(conn):
        print(f"#{a['id']:<3} {a['status']:<9} {a['tool']:<18} by {a['requested_by']:<7} {a['summary'][:70]}")
    return 0


def cmd_audit(args):
    conn = _conn()
    if args.verify:
        print(audit.verify_chain(conn))
        return 0
    for r in reversed(audit.recent(conn, args.limit)):
        print(f"{r['id']:>4} {r['ts']} {r['actor']:<8} {r['action']:<24} {r['detail'][:90]}")
    return 0


def cmd_sample_hire(args):
    from . import webhook
    raw, headers = webhook.signed_request(webhook.sample_hire_event(event_id=args.event_id), config.webhook_secret())
    req = urllib.request.Request(f"http://{config.HOST}:{config.port()}/webhooks/ashby", data=raw, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(resp.status, resp.read().decode())
    except urllib.error.HTTPError as e:
        print(e.code, e.read().decode())
        return 1
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):  # Windows consoles may not be UTF-8 by default
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="peopleops", description="PeopleOps Copilot (synthetic data, local only)")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="one-command demo")
    d.add_argument("--no-browser", action="store_true", help="do not open the dashboard in a browser")
    d.add_argument("--no-serve", action="store_true", help="exit after the demo output instead of keeping the server running")
    sub.add_parser("serve", help="start the server")
    s = sub.add_parser("seed")
    s.add_argument("--fresh", action="store_true", help="delete and recreate the database")
    sub.add_parser("eval", help="run the evaluation harness")
    c = sub.add_parser("chat")
    c.add_argument("message")
    c.add_argument("--as", dest="as_user", default="E006")
    a = sub.add_parser("approvals")
    a.add_argument("action", nargs="?", default="list", choices=["list", "approve", "reject"])
    a.add_argument("id", nargs="?", type=int)
    a.add_argument("--as", dest="as_user", default="E002")
    a.add_argument("--reason")
    au = sub.add_parser("audit")
    au.add_argument("--verify", action="store_true")
    au.add_argument("--limit", type=int, default=30)
    sh = sub.add_parser("sample-hire")
    sh.add_argument("--event-id", default="evt-hire-live-1")
    args = p.parse_args(argv)

    if args.cmd == "eval":
        return evaluate.main()
    if args.cmd == "demo":
        from . import demo
        return demo.run(open_browser=not args.no_browser, keep_serving=not args.no_serve)
    if args.cmd == "serve":
        from . import server
        srv = server.create_server()
        print(f"Serving on http://{config.HOST}:{srv.server_address[1]}  (Ctrl+C to stop)")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    return {"seed": cmd_seed, "chat": cmd_chat, "approvals": cmd_approvals, "audit": cmd_audit,
            "sample-hire": cmd_sample_hire}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
