#!/usr/bin/env python3
"""Keeps this Mac lean between Claude sessions: worktrees, branches, dev servers, compose stacks.

For web repos that
squash-merge pull requests: merge detection also asks GitHub, tracked local-only files such as
.env.local do not count as changes, and dev servers / compose stacks are tied to their worktree.
Simulator handling is left out on purpose: its ownership state is per repo, so another repo's
simulators would look unclaimed here.

Hooks call it; people and Claude can too:
  start    SessionStart: report waiting items and machine strain, then refresh in the background
  end      SessionEnd: sweep in the background
  load     Stop: one-line warning when the machine is strained (throttled)
  sweep    classify everything; clean what is provably safe, queue the rest for the user
  report   print the queue        apply <id>...   do queued items      keep <id>...   never ask again
  enable / disable                turn the automatic cleaning on or off (off = dry run)

Provably safe, done without asking once enabled: stale worktree locks whose agent process is gone,
clean worktrees with nothing running in them whose tip is in main (or is the head of a merged PR),
the local branches of those, and nothing touched in the last day. Everything else is queued.
A branch is never deleted unless its tip is merged; unmerged branches are only ever asked about.
"""

import calendar
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time

DAY = 86400
QUIET_SECONDS = DAY
BRANCH_ASK_AGE = 14 * DAY
IDLE_CLAUDE_SECONDS = 2 * DAY
SWEEP_EVERY = 30 * 60
NOTIFY_EVERY = 6 * 3600
LOAD_WARN_EVERY = 30 * 60
MAX_LOAD = int(os.environ.get("SLOT_MAX_LOAD", "120"))
MAX_PRESSURE = int(os.environ.get("SLOT_MAX_PRESSURE", "2"))
MIN_FREE_GB = int(os.environ.get("SLOT_MIN_FREE_GB", "30"))
PROTECTED_BRANCHES = re.compile(os.environ.get("CLEANUP_PROTECTED_BRANCHES", r"^(main|master|develop)$"))
LOCAL_ONLY_TRACKED = set(os.environ.get("CLEANUP_LOCAL_FILES", ".env.local").split(","))
DISPOSABLE_IGNORED = re.compile(
    r"(^|/)(node_modules|\.next|build|dist|\.turbo|coverage|test-results[^/]*|playwright-report|"
    r"\.venv|__pycache__|\.DS_Store|\.pytest_cache|tsconfig\.tsbuildinfo|[^/]*\.log|next-env\.d\.ts|"
    r"e2e/\.auth|\.temp|\.tmp|\.claude/\.cross-review|\.claude/worktrees)/?$"
)
DEV_SERVER = re.compile(r"next dev|next-server|next start|scripts/dev\.ts|playwright|vitest|turbo|vite|"
                        r"bun (run )?(start|dev|web)|turbopack|storybook")
IDLE_CPU_RATE = 0.02


def sh(*args, cwd=None, timeout=60):
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def out(*args, cwd=None, timeout=60):
    return sh(*args, cwd=cwd, timeout=timeout)[1].strip()


def repo_root():
    start = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    common = out("git", "rev-parse", "--path-format=absolute", "--git-common-dir", cwd=start)
    if not common:
        sys.exit(0)
    return os.path.dirname(common), common


ROOT, GIT_DIR = repo_root()
STATE = os.path.join(GIT_DIR, "claude-cleanup")
os.makedirs(STATE, exist_ok=True)


def load_json(name, default):
    try:
        with open(os.path.join(STATE, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(name, data):
    path = os.path.join(STATE, name)
    with open(path + ".tmp", "w") as f:
        json.dump(data, f, indent=1)
    os.replace(path + ".tmp", path)


def git(*args):
    return sh("git", *args, cwd=ROOT)


def enabled():
    return os.path.exists(os.path.join(STATE, "enabled"))


def inside(path, roots):
    return any(path == r or path.startswith(r + "/") for r in roots)


def owning_tree(path, trees):
    best = None
    for t in trees:
        if inside(path, [t]) and (best is None or len(t) > len(best)):
            best = t
    return best


def ps_table():
    rows = {}
    for line in out("ps", "-axo", "pid=,ppid=,etime=,time=,%cpu=,rss=,comm=").splitlines():
        parts = line.split(None, 6)
        if len(parts) == 7:
            pid, ppid, etime, cpu, pcpu, rss, comm = parts
            rows[int(pid)] = dict(ppid=int(ppid), etime=parse_etime(etime), cpu=parse_etime(cpu),
                                  pcpu=float(pcpu), rss_mb=int(rss) // 1024, comm=comm)
    return rows


def parse_etime(s):
    days, _, rest = s.rpartition("-")
    nums = [float(x) for x in rest.split(":")]
    while len(nums) < 3:
        nums.insert(0, 0)
    return int((int(days) if days else 0) * DAY + nums[0] * 3600 + nums[1] * 60 + nums[2])


def args_of(pid):
    return out("ps", "-o", "args=", "-p", str(pid))


def cwds(pids=None):
    cmd = ["lsof", "-a", "-d", "cwd", "-Fpn"]
    if pids:
        cmd += ["-p", ",".join(str(p) for p in pids)]
    result, pid = {}, None
    for line in sh(*cmd, timeout=30)[1].splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("n") and pid:
            result[pid] = line[1:]
    return result


def is_claude(row):
    return os.path.basename(row["comm"]) == "claude" or re.fullmatch(r"\d+\.\d+\.\d+", os.path.basename(row["comm"]))


def claude_pids(table):
    return {pid for pid, row in table.items() if is_claude(row)}


def my_claude_pid(table):
    pid = os.getppid()
    while pid > 1 and pid in table:
        if is_claude(table[pid]):
            return pid
        pid = table[pid]["ppid"]
    return None


def start_epoch(pid):
    stamp = out("ps", "-o", "lstart=", "-p", str(pid))
    try:
        return time.mktime(time.strptime(stamp, "%a %b %d %H:%M:%S %Y"))
    except ValueError:
        return None


def alive(pid, started=None):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    if started is None:
        return True
    actual = start_epoch(pid)
    return actual is not None and abs(actual - started) < 120


def machine():
    load = float(out("sysctl", "-n", "vm.loadavg").strip("{} ").split()[0] or 0)
    pressure = int(out("sysctl", "-n", "kern.memorystatus_vm_pressure_level") or 1)
    df = out("df", "-g", os.path.expanduser("~")).splitlines()
    free = int(df[1].split()[3]) if len(df) > 1 else 999
    reasons = []
    if load >= MAX_LOAD:
        reasons.append(f"load {load:.0f} (limit {MAX_LOAD})")
    if pressure >= MAX_PRESSURE:
        reasons.append(f"memory pressure {pressure} (limit {MAX_PRESSURE})")
    if free < MIN_FREE_GB:
        reasons.append(f"{free} GB free (min {MIN_FREE_GB})")
    return dict(load=load, pressure=pressure, free_gb=free, strained=reasons)


def compose_stacks():
    code, text, _ = sh("docker", "ps", "-a", "--format",
                       '{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.project.working_dir"}}\t{{.State}}',
                       timeout=20)
    stacks = {}
    if code:
        return stacks
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0]:
            s = stacks.setdefault(parts[0], dict(dir=parts[1], running=0, total=0))
            s["total"] += 1
            s["running"] += parts[2] == "running"
    return stacks


def stack_down(project):
    return sh("docker", "compose", "-p", project, "down", "-v", timeout=180)[0] == 0


def worktrees():
    items, cur = [], None
    for line in git("worktree", "list", "--porcelain")[1].splitlines():
        if line.startswith("worktree "):
            cur = dict(path=line[9:], branch=None, locked=None)
            items.append(cur)
        elif line.startswith("HEAD "):
            cur["head"] = line[5:]
        elif line.startswith("branch "):
            cur["branch"] = line[7:].removeprefix("refs/heads/")
        elif line.startswith("locked"):
            cur["locked"] = line[7:] or "locked"
    return items


def lock_is_stale(reason):
    m = re.search(r"pid (\d+) start (.+?)\)", reason or "")
    if not m:
        return False
    try:
        started = calendar.timegm(time.strptime(m.group(2), "%a %b %d %H:%M:%S %Y"))
    except ValueError:
        return False
    return not alive(int(m.group(1)), started)


def main_refs():
    return [r for r in ("origin/main", "main") if git("rev-parse", "--verify", "-q", r)[0] == 0]


_merged_heads = None


def merged_pr_heads():
    global _merged_heads
    if _merged_heads is None:
        code, text, _ = sh("gh", "pr", "list", "--state", "merged", "--limit", "1000",
                           "--json", "number,headRefOid", cwd=ROOT, timeout=60)
        heads = {}
        if code == 0:
            try:
                heads = {p["headRefOid"]: p["number"] for p in json.loads(text)}
            except ValueError:
                heads = {}
        _merged_heads = heads
    return _merged_heads


def sha_of(rev):
    return out("git", "rev-parse", "--verify", "-q", rev + "^{commit}", cwd=ROOT)


def in_main(rev, refs):
    for ref in refs:
        if git("merge-base", "--is-ancestor", rev, ref)[0] == 0:
            return True
    if refs:
        code, text, _ = git("cherry", refs[0], rev)
        if code == 0 and text.strip() and all(l.startswith("-") for l in text.splitlines()):
            return True
    return sha_of(rev) in merged_pr_heads()


def unmerged_count(rev, refs):
    if not refs:
        return "?"
    return out("git", "rev-list", "--count", rev, "--not", *refs, cwd=ROOT) or "?"


def unpushed_count(rev):
    return out("git", "rev-list", "--count", rev, "--not", "--remotes", cwd=ROOT) or "?"


def last_touched(path):
    gitfile = os.path.join(path, ".git")
    try:
        with open(gitfile) as f:
            admin = f.read().split("gitdir:", 1)[1].strip()
    except (OSError, IndexError):
        admin = gitfile
    stamps = [os.path.getmtime(p) for p in (os.path.join(admin, "logs", "HEAD"), os.path.join(admin, "index"), path)
              if os.path.exists(p)]
    return max(stamps) if stamps else 0


def same_as_main(path, rel):
    mine, main = os.path.join(path, rel), os.path.join(ROOT, rel)
    if not (os.path.isfile(mine) and os.path.isfile(main)):
        return False
    with open(mine, "rb") as a, open(main, "rb") as b:
        return a.read() == b.read()


def precious_ignored(path):
    text = sh("git", "--no-optional-locks", "status", "--porcelain", "--ignored", cwd=path, timeout=60)[1]
    return [l[3:] for l in text.splitlines() if l.startswith("!!")
            and not DISPOSABLE_IGNORED.search(l[3:].rstrip("/")) and not same_as_main(path, l[3:])]


def real_changes(path):
    text = sh("git", "--no-optional-locks", "status", "--porcelain", cwd=path)[1]
    return [l for l in text.splitlines()
            if not (l.startswith("?? ") and os.path.islink(os.path.join(path, l[3:].rstrip("/"))))
            and not (l[:2].strip() == "M" and l[3:] in LOCAL_ONLY_TRACKED)]


def sweep_git(table, where, stacks, auto, ask):
    git("fetch", "--quiet", "origin", "main")
    refs = main_refs()
    trees = worktrees()
    paths = [t["path"] for t in trees]
    checked_out = {t["branch"] for t in trees if t["branch"]}
    claudes = claude_pids(table)
    now = time.time()
    for t in trees[1:]:
        path, name = t["path"], os.path.basename(t["path"])
        if t["locked"]:
            if lock_is_stale(t["locked"]):
                auto.append(dict(id=f"lock:{name}", kind="unlock", target=path,
                                 detail=f"unlock {name} (the agent that locked it has exited)"))
            continue
        if not os.path.isdir(path):
            auto.append(dict(id=f"wt:{name}", kind="prune", target=path, detail=f"prune missing worktree {name}"))
            continue
        here = [pid for pid, d in where.items() if owning_tree(d, paths) == path and pid != os.getpid()]
        if any(pid in claudes for pid in here):
            continue
        procs = [pid for pid in here if DEV_SERVER.search(args_of(pid))]
        if len(procs) != len(here):
            continue
        mine_stacks = [p for p, s in stacks.items() if s["dir"] and owning_tree(s["dir"], paths) == path]
        if now - last_touched(path) < QUIET_SECONDS:
            continue
        dirty = real_changes(path)
        rev = t["branch"] or t["head"]
        merged = in_main(rev, refs)
        keepers = precious_ignored(path) if not dirty else []
        days = int((now - last_touched(path)) / DAY)
        label = f"worktree {name} [{t['branch'] or 'detached'}] (idle {days}d)"
        item = dict(id=f"wt:{name}", kind="worktree", target=path, branch=t["branch"] if merged else None,
                    procs=[[p, start_epoch(p)] for p in procs], stacks=mine_stacks)
        running = []
        if procs:
            running.append(f"stops {len(procs)} dev process(es) {', '.join(map(str, procs[:4]))}")
        if mine_stacks:
            running.append("tears down compose stack " + ", ".join(mine_stacks))
        if merged and not dirty and not keepers and not procs:
            auto.append(dict(item, detail=f"remove {label}: clean and already in main"
                                          + ("; " + "; ".join(running) if running else "")))
            continue
        why = []
        if dirty:
            why.append(f"{len(dirty)} uncommitted change(s)")
        if not merged:
            why.append(f"{unmerged_count(rev, refs)} commit(s) not in main, {unpushed_count(rev)} not on any remote branch")
        if keepers:
            why.append("ignored files that may matter: " + ", ".join(keepers[:3]))
        if not why:
            why.append("merged and clean")
        tail = "its branch is deleted" if merged and t["branch"] else "its branch is kept"
        ask.append(dict(item, force=True, detail=f"remove {label} ({tail}); it has " + "; ".join(why)
                                                 + ("; " + "; ".join(running) if running else "")))
    for project, s in stacks.items():
        d = s["dir"]
        if d and not os.path.isdir(d) and (inside(d, [ROOT]) or d.startswith(ROOT + "-")):
            ask.append(dict(id=f"stack:{project}", kind="stack", target=project,
                            detail=f"tear down compose stack {project} ({s['running']}/{s['total']} running; "
                                   f"its folder {d} is gone) and its volumes"))
    for line in git("for-each-ref", "--format=%(refname:short) %(committerdate:unix)", "refs/heads")[1].splitlines():
        branch, stamp = line.rsplit(" ", 1)
        if branch in checked_out or PROTECTED_BRANCHES.match(branch):
            continue
        if now - int(stamp) < QUIET_SECONDS:
            continue
        if in_main(branch, refs):
            auto.append(dict(id=f"br:{branch}", kind="branch", target=branch,
                             detail=f"delete local branch {branch}: already in main"))
        elif now - int(stamp) > BRANCH_ASK_AGE:
            ask.append(dict(id=f"br:{branch}", kind="branch", target=branch, force=True,
                            detail=f"delete local branch {branch}: {unmerged_count(branch, refs)} commit(s) "
                                   f"not in main, {unpushed_count(branch)} not on any remote branch, "
                                   f"last commit {int((now - int(stamp)) / DAY)}d ago"))


def sweep_processes(table, where, trees, info, ask):
    me = my_claude_pid(table)
    claudes = claude_pids(table)
    for pid, row in table.items():
        if row["ppid"] != 1 or pid == os.getpid() or not inside(where.get(pid, ""), trees):
            continue
        if owning_tree(where[pid], trees) != ROOT:
            continue
        args = args_of(pid)
        if DEV_SERVER.search(args) and pid not in claudes:
            ask.append(dict(id=f"proc:{pid}", kind="kill", target=pid, started=start_epoch(pid),
                            detail=f"stop orphaned process {pid} ({args[:80]}), "
                                   f"up {row['etime'] // 3600}h, {row['rss_mb']} MB"))
    idle = load_json("claude-idle.json", {})
    seen = {}
    now = time.time()
    for pid in claudes:
        if pid == me or not inside(where.get(pid, ""), trees):
            continue
        row = table[pid]
        key = f"{pid}:{int(start_epoch(pid) or 0)}"
        prev = idle.get(key)
        quiet = prev and now > prev.get("at", now) and (row["cpu"] - prev["cpu"]) / (now - prev["at"]) < IDLE_CPU_RATE
        since = prev["since"] if quiet else now
        seen[key] = dict(cpu=row["cpu"], at=now, since=since)
        if row["etime"] > IDLE_CLAUDE_SECONDS and now - since > DAY:
            ask.append(dict(id=f"claude:{pid}", kind="kill", target=pid, started=start_epoch(pid),
                            detail=f"end Claude session {pid} in {where[pid]}: open "
                                   f"{row['etime'] // DAY}d, no activity for {int((now - since) / 3600)}h, "
                                   f"{row['rss_mb']} MB"))
    save_json("claude-idle.json", seen)
    if info["strained"]:
        by = "rss_mb" if info["pressure"] >= MAX_PRESSURE else "pcpu"
        heavy = sorted(table.items(), key=lambda kv: kv[1][by], reverse=True)[:5]
        info["top"] = [f"{pid} {os.path.basename(r['comm'])} {r['pcpu']:.0f}% cpu {r['rss_mb']} MB"
                       for pid, r in heavy]


def stop(pid, started):
    if alive(pid, started):
        os.kill(pid, signal.SIGTERM)


def act(item):
    kind, target = item["kind"], item["target"]
    if kind == "unlock":
        return git("worktree", "unlock", target)[0] == 0
    if kind == "prune":
        return git("worktree", "prune")[0] == 0
    if kind == "stack":
        return stack_down(target)
    if kind in ("worktree", "branch") and not item.get("force") and not still_safe(item):
        return False
    if kind == "worktree":
        for pid, started in item.get("procs", []):
            stop(pid, started)
        for project in item.get("stacks", []):
            stack_down(project)
        if not item.get("force") and os.path.isdir(target):
            unlink_untracked_links(target)
        if git("worktree", "remove", "--force", target)[0] != 0:
            return False
        branch = item.get("branch")
        if branch and not PROTECTED_BRANCHES.match(branch) and in_main(branch, main_refs()):
            git("branch", "-D", branch)
        return True
    if kind == "branch":
        return git("branch", "-D", target)[0] == 0
    if kind == "kill":
        stop(target, item.get("started"))
        return True
    return False


def unlink_untracked_links(path):
    text = sh("git", "--no-optional-locks", "status", "--porcelain", cwd=path)[1]
    for line in text.splitlines():
        link = os.path.join(path, line[3:].rstrip("/"))
        if line.startswith("?? ") and os.path.islink(link):
            os.unlink(link)


def still_safe(item):
    refs = main_refs()
    if item["kind"] == "branch":
        return in_main(item["target"], refs)
    path = item["target"]
    if not os.path.isdir(path):
        return True
    rev = item.get("branch") or out("git", "rev-parse", "HEAD", cwd=path)
    return (in_main(rev, refs) and not real_changes(path) and not precious_ignored(path)
            and time.time() - last_touched(path) >= QUIET_SECONDS)


def log(line):
    with open(os.path.join(STATE, "log.txt"), "a") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")


def sweep():
    lock = open(os.path.join(STATE, "lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return
    os.nice(10)
    table = ps_table()
    info = machine()
    trees = [t["path"] for t in worktrees()]
    where = {pid: d for pid, d in cwds().items() if inside(d, trees)}
    stacks = compose_stacks()
    auto, ask = [], []
    if info["load"] < MAX_LOAD:
        sweep_git(table, where, stacks, auto, ask)
    else:
        prev = load_json("pending.json", {})
        ask += [i for i in prev.get("ask", []) if i["kind"] in ("worktree", "branch", "stack")]
    sweep_processes(table, where, trees, info, ask)
    done = []
    if enabled():
        for item in auto:
            ok = act(item)
            log(("done " if ok else "FAILED ") + item["detail"])
            if ok:
                done.append(item["detail"])
    keep = set(load_json("keep.json", []))
    ask = [i for i in ask if i["id"] not in keep]
    save_json("pending.json", dict(at=time.time(), machine=info, ask=ask,
                                   would_auto=[] if enabled() else auto, done=done))


def spawn_sweep():
    with open(os.path.join(STATE, "sweep.out"), "a") as f:
        subprocess.Popen([sys.executable, __file__, "sweep"], cwd=ROOT, stdout=f, stderr=f,
                         stdin=subprocess.DEVNULL, start_new_session=True)


def waiting(p):
    return p.get("ask", []) + p.get("would_auto", [])


def summary(p):
    kinds = {}
    for i in waiting(p):
        k = i["id"].split(":")[0]
        kinds[k] = kinds.get(k, 0) + 1
    names = dict(wt="worktrees", br="branches", proc="orphaned processes", stack="compose stacks",
                 claude="idle Claude sessions", lock="locks")
    return ", ".join(f"{n} {names.get(k, k)}" for k, n in kinds.items())


def emit(event, message=None, context=None):
    body = {}
    if message:
        body["systemMessage"] = message
    if context:
        body["hookSpecificOutput"] = dict(hookEventName=event, additionalContext=context)
    if body:
        print(json.dumps(body))


def on_start():
    p = load_json("pending.json", {})
    marks = load_json("marks.json", {})
    now = time.time()
    if now - p.get("at", 0) > SWEEP_EVERY:
        spawn_sweep()
    info = machine()
    ask = waiting(p)
    if not ask and not info["strained"]:
        return
    if not info["strained"] and now - marks.get("notified", 0) < NOTIFY_EVERY:
        return
    marks["notified"] = now
    save_json("marks.json", marks)
    strain = f" The machine is strained ({'; '.join(info['strained'])})." if info["strained"] else ""
    context = (f"Machine cleanup is waiting on the user: {summary(p) or 'nothing queued yet'}.{strain} "
               "After you have handled the user's first request (do not interrupt it), offer to run the "
               "/cleanup skill, in one short line." + (" Offer it first, before other work, since the machine "
                                                         "is strained." if info["strained"] else ""))
    emit("SessionStart", f"Cleanup: {len(ask)} item(s) need your OK.{strain} Say /cleanup to review.", context)


def on_load():
    info = machine()
    if not info["strained"]:
        return
    marks = load_json("marks.json", {})
    if time.time() - marks.get("load_warned", 0) < LOAD_WARN_EVERY:
        return
    marks["load_warned"] = time.time()
    save_json("marks.json", marks)
    spawn_sweep()
    emit("Stop", f"Machine strained: {'; '.join(info['strained'])}. Say /cleanup to see what can be freed.")


def apply_ids(ids):
    p = load_json("pending.json", {})
    items = {i["id"]: i for i in p.get("ask", []) + p.get("would_auto", [])}
    for id_ in ids:
        item = items.get(id_)
        if not item:
            print(f"{id_}: not in the queue (run sweep again)")
            continue
        ok = act(item)
        log(("done " if ok else "FAILED ") + "(user approved) " + item["detail"])
        print(("done   " if ok else "FAILED ") + item["detail"])
        if ok:
            p["ask"] = [i for i in p.get("ask", []) if i["id"] != id_]
            p["would_auto"] = [i for i in p.get("would_auto", []) if i["id"] != id_]
    save_json("pending.json", p)


def report():
    p = load_json("pending.json", {})
    if not p:
        print(f"No sweep has run yet. Run: python3 {__file__} sweep")
        return
    m = p["machine"]
    print(f"Swept {int((time.time() - p['at']) / 60)} min ago. Load {m['load']:.0f}, memory pressure "
          f"{m['pressure']}, {m['free_gb']} GB free. Automatic cleaning is {'ON' if enabled() else 'OFF (dry run)'}.")
    if m.get("strained"):
        print("STRAINED: " + "; ".join(m["strained"]) + "\nTop processes:\n  " + "\n  ".join(m.get("top", [])))
    if p.get("done"):
        print(f"\nCleaned automatically ({len(p['done'])}):\n  " + "\n  ".join(p["done"]))
    if p.get("would_auto"):
        print(f"\nWould clean automatically once enabled ({len(p['would_auto'])}):")
        for i in p["would_auto"]:
            print(f"  {i['id']}\t{i['detail']}")
    print(f"\nNeeds a yes ({len(p.get('ask', []))}):")
    for i in p.get("ask", []):
        print(f"  {i['id']}\t{i['detail']}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    payload = {}
    if cmd in ("start", "end", "load") and not sys.stdin.isatty():
        try:
            payload = json.load(sys.stdin)
        except ValueError:
            payload = {}
    if cmd == "start":
        on_start()
    elif cmd == "end":
        if payload.get("reason") != "clear":
            spawn_sweep()
    elif cmd == "load":
        on_load()
    elif cmd == "sweep":
        sweep()
    elif cmd == "apply":
        apply_ids(sys.argv[2:])
    elif cmd == "keep":
        save_json("keep.json", sorted(set(load_json("keep.json", [])) | set(sys.argv[2:])))
    elif cmd == "enable":
        open(os.path.join(STATE, "enabled"), "w").close()
        print("automatic cleaning ON")
    elif cmd == "disable":
        if enabled():
            os.remove(os.path.join(STATE, "enabled"))
        print("automatic cleaning OFF (dry run)")
    else:
        report()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        if len(sys.argv) > 1 and sys.argv[1] in ("start", "end", "load"):
            sys.exit(0)
        raise
