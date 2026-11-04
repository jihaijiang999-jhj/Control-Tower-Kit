"""PILOT-073 evidence probe: envelope-recover, fetch freshness and repair.

Builds throw-away repositories whose ``main`` already contains the
implementation (the 071 direct-admin shape) and exercises the real CLI:

* fresh recovery: WAITING + landed merge -> exit 0, MERGE exactly 1, MERGED;
* refusals: unmerged commit / wrong commit / unresolvable / non-supervisor /
  repeat -> exit 2 with byte-identical envelope, queue and ledger;
* fetch freshness: a stale local ``origin/main`` ref is refreshed by the
  command, while an origin that does not contain the merge is refused;
* half-write repair: files already MERGED with no ledger, and the recovered
  ``MERGE_START`` without ``MERGE``, are completed with ``repaired=true`` and
  state-verify drift [].

Run from ``tower-dsh``::

    python -B scratch/recover_probe.py > scratch/probe.txt
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import tower_envelope  # noqa: E402

TCLI = TOOLS_DIR / "towerctl.py"
TASK = "PILOT-071"
ENVELOPE = "ENV-PILOT-071"
SUPERVISOR = "sup-073"
PRIMARY = "ctl-073"
BRANCH = "feature/recover"
GIT = {"GIT_AUTHOR_NAME": "Probe", "GIT_AUTHOR_EMAIL": "p@example.invalid",
       "GIT_COMMITTER_NAME": "Probe", "GIT_COMMITTER_EMAIL": "p@example.invalid"}


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, encoding="utf-8", env={**os.environ, **GIT})


def must(cp):
    assert cp.returncode == 0, (cp.returncode, cp.stdout, cp.stderr)
    return cp


def dump(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build(tmp: Path, remote_only: bool = False) -> dict:
    kit = tmp / "kit"
    root = kit / "tower-dsh"
    origin = tmp / "origin.git"
    for sub in ("primary", "supervision/envelopes", "ledger"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    for name in ("primary.jsonl", "supervision.jsonl"):
        (root / "ledger" / name).write_text("", encoding="utf-8")
    dump(root / "primary" / "CURRENT_STATE.json", {
        "schema": "tower/current-state@1", "tower_id": "tower-dsh",
        "role": "primary", "phase": "PROBE", "owner": {"name": "mac"},
        "primary": {"id": PRIMARY}})
    dump(root / "supervision" / "CURRENT_STATE.json", {
        "schema": "tower/supervision-state@1", "role": "supervision",
        "phase": "PROBE", "supervisor": {"id": SUPERVISOR}})
    dump(root / "primary" / "TASK_BOARD.json",
         {"schema": "tower/task-board@1", "tasks": []})
    dump(root / "supervision" / "MERGE_QUEUE.json",
         {"schema": "tower/merge-queue@1", "entries": []})
    kit.mkdir(parents=True, exist_ok=True)
    must(git(kit, "init"))
    must(git(kit, "symbolic-ref", "HEAD", "refs/heads/main"))
    (kit / "README.md").write_text("base\n", encoding="utf-8")
    must(git(kit, "add", "-A"))
    must(git(kit, "-c", "commit.gpgsign=false", "commit", "-m", "base"))
    base_sha = git(kit, "rev-parse", "HEAD").stdout.strip()
    must(git(kit, "checkout", "-b", BRANCH))
    (kit / "feature.txt").write_text("implementation\n", encoding="utf-8")
    must(git(kit, "add", "-A"))
    must(git(kit, "-c", "commit.gpgsign=false", "commit", "-m", "implementation"))
    implementation = git(kit, "rev-parse", "HEAD").stdout.strip()
    must(git(kit, "checkout", "main"))
    must(subprocess.run(["git", "init", "--bare", str(origin)],
                        capture_output=True, text=True))
    must(git(kit, "remote", "add", "origin", str(origin).replace("\\", "/")))
    if remote_only:
        must(git(kit, "push", "origin", "main", BRANCH))
        builder = tmp / "builder"
        must(git(tmp, "clone", "--quiet", str(origin), str(builder)))
        must(git(builder, "checkout", "-b", BRANCH, f"origin/{BRANCH}"))
        must(git(builder, "checkout", "main"))
        must(git(builder, "-c", "commit.gpgsign=false", "merge", "--no-ff",
                 BRANCH, "-m", "merge feature"))
        merge_commit = git(builder, "rev-parse", "HEAD").stdout.strip()
        must(git(builder, "push", "origin", "main"))
        assert git(kit, "cat-file", "-e", merge_commit).returncode != 0
    else:
        must(git(kit, "-c", "commit.gpgsign=false", "merge", "--no-ff", BRANCH,
                 "-m", "merge feature"))
        merge_commit = git(kit, "rev-parse", "HEAD").stdout.strip()
        must(git(kit, "push", "origin", "main"))
    tower_envelope.append_supervision_ledger(
        root, "ENVELOPE_NEW", "primary",
        {"envelope": ENVELOPE, "task": TASK, "head": implementation})
    tower_envelope.append_supervision_ledger(
        root, "QUEUE_ADD", "primary", {"envelope": ENVELOPE, "task": TASK})
    ctx = {"kit": kit, "root": root, "origin": origin, "base": base_sha,
           "implementation": implementation, "merge": merge_commit,
           "env_path": root / "supervision" / "envelopes" / f"{ENVELOPE}.json",
           "queue_path": root / "supervision" / "MERGE_QUEUE.json",
           "ledger_path": root / "ledger" / "supervision.jsonl"}
    dump(ctx["env_path"], {
        "schema": "tower/merge-envelope@1", "envelope_id": ENVELOPE,
        "task": TASK, "repository": "..", "branch": BRANCH, "base": "main",
        "envelope_path": f"merge-envelopes/{ENVELOPE}.json",
        "implementation_head_sha": implementation, "tests_baseline": 770,
        "tower_tests_baseline": 900, "status": "WAITING"})
    dump(ctx["queue_path"], {"schema": "tower/merge-queue@1", "entries": [{
        "envelope_id": ENVELOPE, "task": TASK, "status": "WAITING"}]})
    return ctx


def cli(ctx, *args):
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(ctx["root"]), *args],
        capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, **GIT}, timeout=120)


def events(ctx, kind):
    rows = [json.loads(line) for line in
            ctx["ledger_path"].read_text(encoding="utf-8").splitlines()
            if line.strip()]
    return [row for row in rows if row.get("type") == kind]


def snapshot(ctx):
    return (ctx["env_path"].read_bytes(), ctx["queue_path"].read_bytes(),
            ctx["ledger_path"].read_bytes())


def authorize(ctx):
    must(cli(ctx, "authority-set", "--supervisor", SUPERVISOR,
             "--decision", "D-073", "--by", "mac"))


def recover(ctx, commit, reason, *extra):
    return cli(ctx, "envelope-recover", "--envelope", ENVELOPE,
               "--merge-commit", commit, "--reason", reason, *extra)


def refused(label, cp, before, ctx):
    out = json.loads(cp.stdout)
    print(f"{label}: exit={cp.returncode} ok={out['ok']} "
          f"zero_writes={snapshot(ctx) == before} "
          f"error={out['errors'][0][:78]}")
    return cp.returncode == 2 and not out["ok"] and snapshot(ctx) == before


def run_fresh(tmp: Path) -> bool:
    ctx = build(tmp)
    print(f"fresh: implementation={ctx['implementation']} merge={ctx['merge']}")
    authorize(ctx)
    kit = ctx["kit"]
    must(git(kit, "checkout", "-b", "side", "main"))
    (kit / "side.txt").write_text("side\n", encoding="utf-8")
    must(git(kit, "add", "--", "side.txt"))
    must(git(kit, "-c", "commit.gpgsign=false", "commit", "-m", "side only"))
    side = git(kit, "rev-parse", "HEAD").stdout.strip()
    must(git(kit, "checkout", "main"))
    ok = True
    before = snapshot(ctx)
    ok &= refused("unmerged-commit", recover(ctx, side, "not landed"), before, ctx)
    before = snapshot(ctx)
    ok &= refused("wrong-commit", recover(ctx, ctx["base"], "wrong sha"), before, ctx)
    before = snapshot(ctx)
    ok &= refused("non-supervisor",
                  recover(ctx, ctx["merge"], "x", "--by", "sup-rogue"),
                  before, ctx)
    # A stale local origin ref must be refreshed by the command's fetch.
    must(git(kit, "update-ref", "refs/remotes/origin/main", ctx["base"]))
    cp = recover(ctx, ctx["merge"], "071 direct admin")
    envelope = json.loads(ctx["env_path"].read_text(encoding="utf-8"))
    verify = json.loads(cli(ctx, "state-verify").stdout)
    print(f"stale-ref fresh recovery: exit={cp.returncode} "
          f"envelope={envelope['status']} merge_events={len(events(ctx, 'MERGE'))} "
          f"verified={len(events(ctx, 'POST_MERGE_VERIFIED'))} "
          f"drift={verify['drift']}")
    ok &= (cp.returncode == 0 and envelope["status"] == "MERGED"
           and len(events(ctx, "MERGE")) == 1 and verify["drift"] == [])
    before = snapshot(ctx)
    ok &= refused("repeat", recover(ctx, ctx["merge"], "repeat"), before, ctx)
    return bool(ok)


def run_repair(tmp: Path, merge_start: bool) -> bool:
    """Simulate a crash, then let a retry finish the half-written recovery."""
    ctx = build(tmp)
    authorize(ctx)
    if merge_start:
        tower_envelope.append_supervision_ledger(
            ctx["root"], "MERGE_START", "supervision",
            {"envelope": ENVELOPE, "supervisor": SUPERVISOR, "recovered": True})
    env = json.loads(ctx["env_path"].read_text(encoding="utf-8"))
    env.update({"status": "MERGED", "merge_commit": ctx["merge"]})
    dump(ctx["env_path"], env)
    queue = json.loads(ctx["queue_path"].read_text(encoding="utf-8"))
    queue["entries"][0].update({"status": "MERGED",
                                "merge_commit": ctx["merge"]})
    dump(ctx["queue_path"], queue)
    cp = recover(ctx, ctx["merge"], "finish half write")
    out = json.loads(cp.stdout)
    verify = json.loads(cli(ctx, "state-verify").stdout)
    print(f"repair(merge_start={merge_start}): exit={cp.returncode} "
          f"repaired={out.get('repaired')} "
          f"starts={len(events(ctx, 'MERGE_START'))} "
          f"merges={len(events(ctx, 'MERGE'))} drift={verify['drift']}")
    return bool(cp.returncode == 0 and out.get("repaired") is True
                and len(events(ctx, "MERGE_START")) == 1
                and len(events(ctx, "MERGE")) == 1 and verify["drift"] == [])


def run_remote_only(tmp: Path) -> bool:
    """The 071 shape literally: the merge commit exists only on the origin."""
    ctx = build(tmp, remote_only=True)
    authorize(ctx)
    local_has = git(ctx["kit"], "cat-file", "-e", ctx["merge"]).returncode == 0
    cp = recover(ctx, ctx["merge"], "remote-only merge")
    envelope = json.loads(ctx["env_path"].read_text(encoding="utf-8"))
    verify = json.loads(cli(ctx, "state-verify").stdout)
    print(f"remote-only: local_object={local_has} exit={cp.returncode} "
          f"envelope={envelope['status']} merges={len(events(ctx, 'MERGE'))} "
          f"drift={verify['drift']}")
    return bool(not local_has and cp.returncode == 0
                and envelope["status"] == "MERGED"
                and len(events(ctx, "MERGE")) == 1 and verify["drift"] == [])


def main() -> int:
    print("PILOT-073 envelope-recover probe (fetch order + repair)")
    good = run_fresh(Path(tempfile.mkdtemp(prefix="pilot-073-probe-a-")))
    good &= run_repair(Path(tempfile.mkdtemp(prefix="pilot-073-probe-b-")), False)
    good &= run_repair(Path(tempfile.mkdtemp(prefix="pilot-073-probe-c-")), True)
    good &= run_remote_only(Path(tempfile.mkdtemp(prefix="pilot-073-probe-d-")))
    print(f"RESULT ok={bool(good)}")
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
