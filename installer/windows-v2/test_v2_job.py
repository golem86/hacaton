"""
test_v2_job.py — локальні runtime-тести ЕКСПЕРИМЕНТАЛЬНОГО v2_job_launcher.py (етап 2, J01–J20). Лише власні процеси
python поточного користувача й тимчасові job-и з іменами Local\\v2test-<guid>; служби, WinSW, сервер не використовуються.

Запуск:  python -I test_v2_job.py [--only J01,J05]
Код виходу: 0 — усі виконані тести PASS; 1 — є FAIL. Сценарії, які на цьому хості неможливі, — NOT RUN (не PASS).

Локальна адаптація (чесно): сканування за власником тут шукає процеси поточного користувача, а не віртуального акаунта
служби, і в режимі --unknown baseline не розглядає процеси, що існували до тесту (без прав адміністратора власник
чужих процесів невизначений). Production-режим --unknown block і SID служби — NOT RUN (потрібен тест-хост).
"""
import sys as _sys
_sys.dont_write_bytecode = True          # не лишати __pycache__ у каталозі комплекту
import ctypes
import ctypes.wintypes as w
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

for _st in (sys.stdout, sys.stderr):
    _st.reconfigure(encoding="utf-8", errors="backslashreplace")

HERE = os.path.dirname(os.path.abspath(__file__))
LAU = os.path.join(HERE, "v2_job_launcher.py")
CHILD = os.path.join(HERE, "job_child.py")
PY = sys.executable
spec = importlib.util.spec_from_file_location("v2_job_launcher", LAU)
L = importlib.util.module_from_spec(spec); sys.modules["v2_job_launcher"] = L; spec.loader.exec_module(L)
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.GetCurrentProcess.restype = w.HANDLE                       # псевдо-handle -1 — 64-бітний (без restype обрізався до 32 біт → J09.env хибно «не в job»)
k32.IsProcessInJob.argtypes = [w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)]
k32.OpenProcess.restype = w.HANDLE; k32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k32.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]; k32.WaitForSingleObject.restype = w.DWORD
k32.TerminateProcess.argtypes = [w.HANDLE, ctypes.c_uint]
k32.CloseHandle.argtypes = [w.HANDLE]
DETACHED = 0x00000008
ONLY = (sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None)
ME = L.my_sid()
# auditfix3 J09.env: якщо процес тесту не в job, набір перезапускається всередині зовнішнього job (KILL_ON_JOB_CLOSE, без breakaway) —
# усі J* виконуються вкладено детерміновано, а не залежно від середовища запуску.
_r = w.BOOL(); k32.IsProcessInJob(k32.GetCurrentProcess(), None, ctypes.byref(_r))
if not _r.value and "--in-outer-job" not in sys.argv:
    _oj = L.api.CreateJobObjectW(None, None)
    _li = L.EXTENDED_LIMIT(); _li.Basic.LimitFlags = L.REQUIRED_LIMITS
    if not _oj or not L.api.SetInformationJobObject(_oj, 9, ctypes.byref(_li), ctypes.sizeof(_li)):
        print("J09.env        FAIL    зовнішній job не створено", flush=True); sys.exit(1)
    _pi = L.spawn_in_job(_oj, [PY, "-I", os.path.abspath(__file__), "--in-outer-job"] + sys.argv[1:])
    L.api.WaitForSingleObject(_pi.hProcess, 0xFFFFFFFF)
    _code = w.DWORD(); L.api.GetExitCodeProcess(_pi.hProcess, ctypes.byref(_code))
    L.api.CloseHandle(_pi.hThread); L.api.CloseHandle(_pi.hProcess); L.api.CloseHandle(_oj)   # KILL_ON_JOB_CLOSE прибирає залишки
    sys.exit(L.exit_code(_code.value))
TMP = tempfile.mkdtemp(prefix="v2-job-tests-")
BASE = os.path.join(TMP, "baseline.json")
results = []
cleanup_pids = []


def add(tid, ok, desc, status=None):
    st = status or ("PASS" if ok else "FAIL")
    results.append((tid, st))
    print(f"{tid:<14} {st:<7} {desc}", flush=True)


def jname():
    return "Local\\v2test-" + uuid.uuid4().hex


def tf(name):
    return os.path.join(TMP, f"{uuid.uuid4().hex[:8]}-{name}")


def wait_file(p, t=15):
    end = time.time() + t
    while time.time() < end:
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    return json.load(f)
            except (ValueError, OSError):
                pass
        time.sleep(0.05)
    return None


def ph(pid):
    """handle процесу (SYNCHRONIZE | QUERY_LIMITED | TERMINATE) — для перевірки виходу без PID reuse."""
    return k32.OpenProcess(0x100000 | 0x1000 | 0x1, False, pid) if pid else None


def exited(h, t=0):
    return h is None or k32.WaitForSingleObject(h, int(t * 1000)) == 0


def kill_h(h):
    if h:
        k32.TerminateProcess(h, 9); k32.WaitForSingleObject(h, 5000)


BOOT = ("import importlib.util,sys,os,ctypes,json\nsys.dont_write_bytecode = True\n"
        f"spec=importlib.util.spec_from_file_location('v2_job_launcher', {LAU!r}); L=importlib.util.module_from_spec(spec)\n"
        "sys.modules['v2_job_launcher']=L; spec.loader.exec_module(L)\n")


def launch(job, mode, *cargs, pre=None, flags=DETACHED, state=None):
    """Запуск launcher-а (окремий процес). pre — код підміни/спостереження в процесі launcher-а (лише тести)."""
    state = state or tf("launcher.json")
    out = tf("launcher.out")
    cst = tf("child.json")
    argv = ["run", "--job", job, "--state", state, "--", PY, "-I", CHILD, mode, cst] + list(cargs)
    if pre:
        cmd = [PY, "-I", "-c", BOOT + pre + f"\nsys.exit(L.exit_code(L.main({argv!r})))"]
    else:
        cmd = [PY, "-I", LAU] + argv
    fo = open(out, "w", encoding="utf-8")
    p = subprocess.Popen(cmd, stdout=fo, stderr=subprocess.STDOUT, creationflags=flags)
    fo.close()
    cleanup_pids.append(p.pid)
    return p, cst, out, state


def rd(p):
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def snap():
    """Свіжий baseline безпосередньо перед сценарієм (процеси, що з'явились раніше, у т.ч. від попередніх тестів, не розглядаються)."""
    b = tf("baseline.json")
    subprocess.run([PY, "-I", LAU, "snapshot", "--out", b], check=True, creationflags=DETACHED)
    return b


def proof(job, scan=True, owner=ME, base=None, scope=None):
    a = [PY, "-I", LAU, "proof", "--job", job, "--expect-owner", owner]
    if scan:
        a += ["--scan-sid", ME, "--unknown", "baseline", "--baseline", base or BASE]
        if scope:                                  # локально: лише дерево тесту (фонові процеси Windows поза тестом — шум, RR10)
            a += ["--scope-root", str(scope)]
    r = subprocess.run(a, capture_output=True, timeout=120, creationflags=DETACHED)
    try:
        return r.returncode, json.loads(r.stdout.decode("utf-8"))
    except ValueError:
        return r.returncode, {"verdict": "?", "problems": [r.stderr.decode("utf-8", "replace")]}


def terminate(job):
    r = subprocess.run([PY, "-I", LAU, "terminate", "--job", job, "--expect-owner", ME], capture_output=True, timeout=60, creationflags=DETACHED)
    return r.returncode


def hold(job):
    h = L.api.OpenJobObjectW(L.JOB_QUERY | L.JOB_TERMINATE | L.SYNCHRONIZE, False, job)
    return h


def job_pids(job):
    h = hold(job)
    if not h:
        return None
    try:
        return L.query_pids(h)[0]
    finally:
        L.api.CloseHandle(h)


def test_job(sddl=None, limits=L.REQUIRED_LIMITS, name=None):
    """Тестовий job від імені тесту (для J12/J16/J17): довільний SD і ліміти."""
    name = name or jname()
    psd = ctypes.c_void_p()
    sa = None
    if sddl:
        assert L.api.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(psd), None)
        sa = L.SECURITY_ATTRIBUTES(ctypes.sizeof(L.SECURITY_ATTRIBUTES), psd, False)
    h = L.api.CreateJobObjectW(ctypes.byref(sa) if sa else None, name)
    li = L.EXTENDED_LIMIT(); li.Basic.LimitFlags = limits
    assert L.api.SetInformationJobObject(h, 9, ctypes.byref(li), ctypes.sizeof(li))
    return name, h


def run(tid):
    return ONLY is None or tid in ONLY


def no_children_alive(launcher_pid, t0_ticks):
    snap = L.process_snapshot()
    return [p for p, (pp, ct, n) in snap.items() if pp == launcher_pid and ct >= t0_ticks]


def now_ticks():
    return (int(time.time() * 10_000_000) + 116444736000000000) - 10_000_000   # FILETIME, із запасом 1 с


try:
    subprocess.run([PY, "-I", LAU, "snapshot", "--out", BASE], check=True, creationflags=DETACHED)
    r = w.BOOL(); k32.IsProcessInJob(k32.GetCurrentProcess(), None, ctypes.byref(r))
    ENV_NESTED = bool(r.value)

    # ------------------------------------------------------------------ J01 аварія launcher-а
    if run("J01"):
        j = jname(); p, cst, out, _ = launch(j, "grandchild")
        st = wait_file(cst); hc, hg = ph(st["child"]), ph(st["grandchild"])
        p.kill(); p.wait(10)
        ok = exited(hc, 5) and exited(hg, 5)
        add("J01", ok and st is not None, f"launcher убито TerminateProcess → нащадок {st['child']} і онук {st['grandchild']} завершені ≤5 с (KILL_ON_JOB_CLOSE)")
        kill_h(hc); kill_h(hg)

    # ------------------------------------------------------------------ J02 breakaway
    if run("J02"):
        j = jname(); p, cst, out, _ = launch(j, "breakaway")
        st = wait_file(cst); pids = job_pids(j) or []
        add("J02", st and not st["breakaway_ok"] and st["breakaway_error"] == 5 and st["grandchild"] in pids,
            f"CreateProcess(CREATE_BREAKAWAY_FROM_JOB) → помилка {st and st['breakaway_error']} (5 = ACCESS_DENIED); звичайний онук у PID-list job")
        p.kill(); p.wait(10)

    # ------------------------------------------------------------------ J03 ім'я job уже існує
    if run("J03"):
        j, h = test_job(L.job_sddl(ME))
        mk = tf("marker")
        p, cst, out, _ = launch(j, "marker", mk)
        try:
            rc = p.wait(10)
        except subprocess.TimeoutExpired:
            rc = None
            p.kill(); p.wait(10)  # лише launcher, створений цим тестом
        add("J03", rc == 1 and "уже існує" in rd(out) and not os.path.exists(mk), f"job з таким іменем уже існує → launcher exit {rc}, процес не запущено")
        L.api.CloseHandle(h)

    # ------------------------------------------------------------------ J04 помилка створення / призначення
    if run("J04"):
        mk = tf("marker")
        p, cst, out, _ = launch(jname(), "marker", mk, pre="L.api.CreateProcessW = lambda *a: (ctypes.set_last_error(5), 0)[1]"); rc = p.wait(30)
        add("J04.create", rc == 1 and "CreateProcessW" in rd(out) and not os.path.exists(mk), f"CreateProcessW → помилка: exit {rc}, runnable-процесу немає")
        mk = tf("marker"); pidf = tf("pid")
        t0 = now_ticks()
        p, cst, out, _ = launch(jname(), "marker", mk, pre=f"L.hooks['after_create']=lambda job,pi: open({pidf!r},'w').write(str(pi.dwProcessId))\nL.is_in_job=lambda h,j: False")
        try:
            rc = p.wait(10)
        except subprocess.TimeoutExpired:
            rc = None
            p.kill(); p.wait(10)  # лише launcher, створений цим тестом
        cpid = int(open(pidf).read()) if os.path.exists(pidf) else None
        time.sleep(0.5)
        alive = no_children_alive(p.pid, t0)
        add("J04.assign", rc == 1 and "поза job" in rd(out) and not os.path.exists(mk) and cpid and not alive,
            f"процес не в job до старту → завершено suspended PID {cpid}; exit {rc}; живих нащадків launcher-а {alive}")

    # ------------------------------------------------------------------ J05 / J15 handle job і whitelist
    if run("J05") or run("J15"):
        canary = "v2test-canary-" + uuid.uuid4().hex
        pre = ("k=ctypes.WinDLL('kernel32', use_last_error=True); k.CreateEventW.restype=ctypes.c_void_p\n"
               f"sa=L.SECURITY_ATTRIBUTES(ctypes.sizeof(L.SECURITY_ATTRIBUTES), None, True); ev=k.CreateEventW(ctypes.byref(sa), True, False, 'Local\\\\{canary}')\n"
               f"os.environ['V2TEST_CANARY_NAME']={canary!r}; os.environ['V2TEST_CANARY_HANDLE']=str(ev)\n"
               "L.hooks['before_create']=lambda job: os.environ.__setitem__('V2TEST_JOB_HANDLE', str(job))\n")
        p, cst, out, _ = launch(jname(), "handles", pre=pre)
        st = wait_file(cst)
        add("J05", st and st["V2TEST_JOB_HANDLE"] in ("absent", "other-object"), f"значення handle job launcher-а в дочірньому процесі: {st and st['V2TEST_JOB_HANDLE']} (не job: absent/other-object; launcher перевіряє, що handle неуспадковуваний)")
        add("J15", st and st["V2TEST_CANARY_HANDLE"] in ("absent", "other-object") and st["stdout"] == "ok" and "STDOUT-INHERITED" in rd(out),
            f"whitelist: успадкований canary-handle launcher-а — {st and st['V2TEST_CANARY_HANDLE']}; stdout успадковано: {st and st['stdout']}")
        p.kill(); p.wait(10)
        # контроль детектора: без whitelist (звичайне успадкування) canary видно
        k = ctypes.WinDLL("kernel32", use_last_error=True); k.CreateEventW.restype = ctypes.c_void_p
        sa = L.SECURITY_ATTRIBUTES(ctypes.sizeof(L.SECURITY_ATTRIBUTES), None, True)
        ev = k.CreateEventW(ctypes.byref(sa), True, False, "Local\\" + canary + "-c")
        cst2 = tf("ctl.json")
        env = dict(os.environ, V2TEST_CANARY_NAME=canary + "-c", V2TEST_CANARY_HANDLE=str(ev))
        c = subprocess.Popen([PY, "-I", CHILD, "handles", cst2], env=env, close_fds=False, creationflags=DETACHED, stdout=subprocess.DEVNULL)
        st2 = wait_file(cst2); c.kill(); c.wait(5); k.CloseHandle(ctypes.c_void_p(ev))
        # контроль детектора J05: справді успадкований handle job, процес у цьому job → LEAKED-JOB
        sa = L.SECURITY_ATTRIBUTES(ctypes.sizeof(L.SECURITY_ATTRIBUTES), None, True)
        jh = L.api.CreateJobObjectW(ctypes.byref(sa), None)
        cst3 = tf("ctlj.json")
        c3 = subprocess.Popen([PY, "-I", CHILD, "handles", cst3], env=dict(os.environ, V2TEST_JOB_HANDLE=str(jh), V2TEST_DELAY="1.5"), close_fds=False, creationflags=DETACHED, stdout=subprocess.DEVNULL)
        k32.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        hc3 = k32.OpenProcess(0x0100 | 0x0001 | 0x100000, False, c3.pid); assigned = k32.AssignProcessToJobObject(jh, hc3)
        st3 = wait_file(cst3); c3.kill(); c3.wait(5); L.api.CloseHandle(jh)
        add("J05.control", assigned and st3 and st3["V2TEST_JOB_HANDLE"] == "LEAKED-JOB", f"контроль детектора: при звичайному успадкуванні handle job виявлено ({st3 and st3['V2TEST_JOB_HANDLE']})")
        add("J15.control", st2 and st2["V2TEST_CANARY_HANDLE"] == "LEAKED-CANARY", f"контроль детектора: при звичайному успадкуванні canary виявлено ({st2 and st2['V2TEST_CANARY_HANDLE']})")

    # ------------------------------------------------------------------ J06 WMI-процес поза job
    if run("J06"):
        b6 = snap(); j = jname(); p, cst, out, _ = launch(j, "wmi")
        st = wait_file(cst, 90); hj = hold(j)
        wp = st and st.get("wmi_pid"); hw = ph(wp)
        in_job = wp in (job_pids(j) or [])
        terminate(j); time.sleep(0.5)
        rc, rep = proof(j, base=b6)
        alive = [a["pid"] for a in rep.get("scan", {}).get("alive", [])]
        if st and st.get("wmi_rc") != 0:
            add("J06", False, f"Win32_Process.Create недоступний на цьому хості: {st.get('stderr', '')[-200:]}", "NOT RUN")
        else:
            add("J06", st and wp and not in_job and rc == 2 and rep["verdict"] == "BLOCKED" and wp in alive and rep.get("active") == 0,
                f"WMI Win32_Process.Create → PID {wp} поза job (у PID-list: {in_job}); job порожній, сканування → BLOCKED")
        kill_h(hw); L.api.CloseHandle(hj); p.wait(10)
        # Локальний контроль тієї самої перевірки: власний процес поза job.
        b6c = snap(); j6c, h6c = test_job(L.job_sddl(ME))
        c6c = subprocess.Popen([PY, "-I", "-c", "import time; time.sleep(30)"], creationflags=DETACHED)
        try:
            time.sleep(0.3)
            rc6c, r6c = proof(j6c, base=b6c)
            scan6c = r6c.get("scan", {})
            add("J06.owner-scan", rc6c == 2 and r6c["verdict"] == "BLOCKED" and r6c.get("active") == 0 and c6c.pid in [v["pid"] for v in scan6c.get("alive", [])],
                f"власний PID {c6c.pid} поза порожнім job → сканування власника блокує proof (exit {rc6c})")
        finally:
            c6c.kill(); c6c.wait(10); L.api.CloseHandle(h6c)

    # ------------------------------------------------------------------ J07 осиротілий онук
    if run("J07"):
        j = jname(); go = tf("go")
        p, cst, out, _ = launch(j, "orphan", go)
        st = wait_file(cst); hj = hold(j); hg = ph(st["grandchild"])
        before = job_pids(j) or []
        open(go, "w").close()
        rc = p.wait(30)
        ok = st["grandchild"] in before and exited(hg, 5) and "лишилось" in rd(out) and L.query_active(hj) == 0
        add("J07", ok, f"нащадок завершився, осиротілий онук {st['grandchild']} лишився в job (PID-list {before}) → launcher завершив job; exit {rc}")
        kill_h(hg); L.api.CloseHandle(hj)

    # ------------------------------------------------------------------ J08 доказ лише після повного PASS
    if run("J08"):
        b8 = snap(); j = jname(); p, cst, out, _ = launch(j, "grandchild")
        st = wait_file(cst); hj = hold(j)
        rc1, r1 = proof(j, base=b8, scope=os.getpid())
        rc0, r0 = proof(j, scan=False)
        trc = terminate(j); p.wait(15)
        for attempt in range(10):
            rc2, r2 = proof(j, base=b8, scope=os.getpid())
            if rc2 == 0:
                break
            time.sleep(0.3)
        add("J08.running", rc1 == 2 and r1["verdict"] == "BLOCKED" and r1["active"] >= 2 and
            any("у job живі процеси" in problem for problem in r1["problems"]), f"дерево живе → BLOCKED (ActiveProcesses={r1.get('active')}: нащадок, онук і, без консолі launcher-а, conhost.exe)")
        add("J08.noscan", rc0 == 2 and r0["verdict"] == "BLOCKED", "без сканування за власником доказ не видається → BLOCKED")
        add("J08.pass", trc == 0 and rc2 == 0 and r2["verdict"] == "PASS" and r2["active"] == 0 and r2["pids"] == [] and not r2["scan"]["alive"] and not r2["scan"]["unknown"],
            f"після terminate: ActiveProcesses={r2.get('active')}, PID-list {r2.get('pids')}, scan={r2.get('scan')}, problems={r2.get('problems')} (exit {rc2})")
        L.api.CloseHandle(hj)

    # ------------------------------------------------------------------ J09 вкладені job
    if run("J09"):
        add("J09.env", ENV_NESTED, f"процес тесту всередині зовнішнього job ({'створеного тестом (--in-outer-job)' if '--in-outer-job' in sys.argv else 'середовища'}) — усі J* виконуються вкладено")
        on, oh = test_job()
        st_l = tf("launcher.json"); cst = tf("child.json"); j = jname()
        pi = L.spawn_in_job(oh, [PY, "-I", LAU, "run", "--job", j, "--state", st_l, "--", PY, "-I", CHILD, "sleep", cst])
        st = wait_file(cst); hc = ph(st["child"])
        rr = w.BOOL(); L.api.IsProcessInJob(hc, oh, ctypes.byref(rr))
        add("J09.explicit", st and rr.value and st["child"] in (job_pids(j) or []), "launcher у зовнішньому job → нащадок водночас у зовнішньому і V2 job")
        L.api.TerminateJobObject(oh, 9); L.api.CloseHandle(oh); L.api.CloseHandle(pi.hProcess); kill_h(hc)

    add("J10", False, "WinSW 2.12.0 start/stop із launcher-ом — потрібна тестова служба (адмін, окремий тест-хост за погодженням №5)", "NOT RUN")

    # ------------------------------------------------------------------ J11 аварія між створенням і стартом
    if run("J11"):
        mk = tf("marker"); pidf = tf("pid")
        p, cst, out, _ = launch(jname(), "marker", mk, pre=f"L.hooks['after_create']=lambda job,pi: (open({pidf!r},'w').write(str(pi.dwProcessId)), os._exit(7))")
        rc = p.wait(30)
        cpid = int(open(pidf).read()) if os.path.exists(pidf) else None
        hc = ph(cpid)
        add("J11", rc == 7 and cpid and exited(hc, 5) and not os.path.exists(mk), f"launcher упав після CreateProcess (до ResumeThread) → suspended PID {cpid} завершено разом із job; маркера немає")
        kill_h(hc)

    # ------------------------------------------------------------------ J12 підмінений owner / ACL job
    if run("J12"):
        good = L.job_sddl(ME)
        for sub, sddl, owner in (("extra-ace", good + "(A;;0x1F003F;;;WD)", ME),
                                 ("admins-full", good.replace(f"(A;;0x{L.JOB_ADMIN:X};;;BA)", "(A;;0x1F003F;;;BA)"), ME),
                                 ("no-system", good.replace(f"(A;;0x{L.JOB_ALL:X};;;SY)", ""), ME),
                                 ("unprotected", good.replace("D:P", "D:"), ME),
                                 ("wrong-owner", good, "S-1-5-80-0")):
            j, h = test_job(sddl)
            rc, rep = proof(j, owner=owner)
            sdp = [x for x in rep["problems"] if "job" in x and ("DACL" in x or "власник" in x)]
            add(f"J12.{sub}", rc == 2 and rep["verdict"] == "BLOCKED" and sdp, f"SD job: {sub} → BLOCKED ({sdp[:1]})")
            L.api.CloseHandle(h)

    # ------------------------------------------------------------------ J13 атомарний JOB_LIST + членство до першої інструкції
    if run("J13"):
        mk = tf("marker"); obs = tf("obs")
        pre = (f"L.hooks['before_resume']=lambda job,pi: open({obs!r},'w').write(json.dumps({{'in_job': L.is_in_job(pi.hProcess, job), "
               f"'marker': os.path.exists({mk!r}), 'limits': L.query_limits(job)}}))")
        p, cst, out, _ = launch(jname(), "marker", mk, pre=pre)
        o = wait_file(obs); t = time.time()
        while not os.path.exists(mk) and time.time() - t < 15:
            time.sleep(0.05)
        add("J13", o and o["in_job"] and not o["marker"] and o["limits"] == L.REQUIRED_LIMITS and os.path.exists(mk),
            f"до ResumeThread: у job={o and o['in_job']}, маркер={o and o['marker']} (жодної інструкції), ліміти 0x{(o or {}).get('limits', 0):X}; після resume маркер створено")
        p.kill(); p.wait(10)

    # ------------------------------------------------------------------ J14 помилки атрибутів / CreateProcess
    if run("J14"):
        for sub, pre, fn in (("init", "L.api.InitializeProcThreadAttributeList = lambda *a: (ctypes.set_last_error(87), 0)[1]", "InitializeProcThreadAttributeList"),
                             ("update-job", "_u=L.api.UpdateProcThreadAttribute\nL.api.UpdateProcThreadAttribute = lambda l,f,a,*r: ((ctypes.set_last_error(87), 0)[1] if a==L.PROC_THREAD_ATTRIBUTE_JOB_LIST else _u(l,f,a,*r))", "JOB_LIST"),
                             ("update-handles", "_u=L.api.UpdateProcThreadAttribute\nL.api.UpdateProcThreadAttribute = lambda l,f,a,*r: ((ctypes.set_last_error(87), 0)[1] if a==L.PROC_THREAD_ATTRIBUTE_HANDLE_LIST else _u(l,f,a,*r))", "HANDLE_LIST"),
                             ("createprocess", "L.api.CreateProcessW = lambda *a: (ctypes.set_last_error(2), 0)[1]", "CreateProcessW"),
                             ("resume", "L.api.ResumeThread = lambda h: 0xFFFFFFFF", "ResumeThread")):
            mk = tf("marker"); t0 = now_ticks()
            p, cst, out, _ = launch(jname(), "marker", mk, pre=pre); rc = p.wait(30); time.sleep(0.3)
            alive = no_children_alive(p.pid, t0)
            add(f"J14.{sub}", rc == 1 and fn in rd(out) and not os.path.exists(mk) and not alive, f"помилка {fn} → STOP (exit {rc}); маркера немає; живих нащадків {alive}")

    # ------------------------------------------------------------------ J16 неправильні ліміти job
    if run("J16"):
        add("J16.expected", L.REQUIRED_LIMITS == 0x2400, f"обов'язкові ліміти job точно 0x2400 (фактично 0x{L.REQUIRED_LIMITS:X})")
        mk = tf("marker")
        pre = ("_s=L.api.SetInformationJobObject\n"
               "def _bad(h,c,p,n):\n    li=ctypes.cast(p, ctypes.POINTER(L.EXTENDED_LIMIT)).contents; li.Basic.LimitFlags |= L.BREAKAWAY_OK; return _s(h,c,p,n)\n"
               "L.api.SetInformationJobObject=_bad")
        p, cst, out, _ = launch(jname(), "marker", mk, pre=pre); rc = p.wait(30)
        add("J16.launcher", rc == 1 and "ліміти job" in rd(out) and not os.path.exists(mk), f"launcher: ліміти з BREAKAWAY_OK → STOP до створення процесу (exit {rc})")
        for sub, lim in (("no-kill", L.DIE_ON_UNHANDLED_EXCEPTION), ("breakaway", L.REQUIRED_LIMITS | L.BREAKAWAY_OK), ("silent", L.REQUIRED_LIMITS | L.SILENT_BREAKAWAY_OK)):
            j, h = test_job(L.job_sddl(ME), limits=lim)
            rc, rep = proof(j)
            add(f"J16.{sub}", rc == 2 and any("ліміти job" in x for x in rep["problems"]), f"proof: ліміти 0x{lim:X} → BLOCKED")
            L.api.CloseHandle(h)

    # ------------------------------------------------------------------ J17 PID-list resize race, owner-query failure
    if run("J17"):
        j, h = test_job(L.job_sddl(ME))
        real = L.api.QueryInformationJobObject
        cnt = {"n": 0}
        def flaky(hh, cls, buf, size, ret, k=2):
            if cls == 3 and cnt["n"] < k:
                cnt["n"] += 1
                ctypes.memmove(buf, (5).to_bytes(4, "little") + (1).to_bytes(4, "little"), 8)
                ctypes.set_last_error(L.ERROR_MORE_DATA); return 0
            return real(hh, cls, buf, size, ret)
        L.api.QueryInformationJobObject = flaky
        try:
            try:
                pids, tries = L.query_pids(h)
                add("J17.resize-retry", pids == [] and tries == 2, f"PID-list двічі ERROR_MORE_DATA → повтор, стабільний результат на спробі {tries}")
            except L.Stop as e:
                add("J17.resize-retry", False, f"PID-list не стабілізувався після двох ERROR_MORE_DATA: {e}")
            cnt["n"] = -10 ** 6
            try:
                L.query_pids(h); add("J17.resize-blocked", False, "постійна зміна розміру не дала Stop")
            except L.Stop as e:
                add("J17.resize-blocked", True, f"PID-list не стабілізувався → Stop/BLOCKED ({e})")
        finally:
            L.api.QueryInformationJobObject = real
        c = subprocess.Popen([PY, "-I", "-c", "import time; time.sleep(60)"], creationflags=DETACHED)
        time.sleep(0.5)
        real_owner = L.owner_of
        L.owner_of = lambda pid, ct, retries=1: None if pid == c.pid else real_owner(pid, ct, retries)
        try:
            alive, unknown = L.owner_scan(ME, "baseline", json.load(open(BASE)), exclude={os.getpid()})
        finally:
            L.owner_of = real_owner
        add("J17.owner-unknown", any(u["pid"] == c.pid for u in unknown), f"власника PID {c.pid} визначити не вдалося (після повтору) → у списку невизначених → BLOCKED")
        c.kill(); c.wait(5); L.api.CloseHandle(h)

    # ------------------------------------------------------------------ J18 матриця зупинки (локальна частина)
    if run("J18"):
        for sub, ev in (("ctrl-c", 0), ("ctrl-break", 1)):
            j = jname(); p, cst, out, _ = launch(j, "grandchild", flags=0x10)      # CREATE_NEW_CONSOLE: власна консоль launcher-а
            st = wait_file(cst); hc, hg = ph(st["child"]), ph(st["grandchild"])
            time.sleep(0.5)
            r = subprocess.run([PY, "-I", "-c", "import ctypes,sys; k=ctypes.windll.kernel32; k.FreeConsole(); ok=k.AttachConsole(int(sys.argv[1])); k.SetConsoleCtrlHandler(None, True); "
                                f"ok2=k.GenerateConsoleCtrlEvent({ev}, 0); print(ok, ok2)", str(p.pid)], capture_output=True, creationflags=DETACHED, timeout=30)
            if r.stdout.split()[:2] != [b"1", b"1"]:
                add(f"J18.{sub}", False, f"подію не вдалося згенерувати в консолі launcher-а на цьому хості ({r.stdout!r})", "NOT RUN")
                p.kill(); p.wait(10)
            else:
                try:
                    rc = p.wait(20)
                    add(f"J18.{sub}", exited(hc, 5) and exited(hg, 5) and (rc & 0xFFFFFFFF) == 0xC000013A, f"{sub} → обробник launcher-а TerminateJobObject; нащадок і онук завершені; exit 0x{rc & 0xFFFFFFFF:X}")
                except subprocess.TimeoutExpired:
                    add(f"J18.{sub}", False, f"{sub} доставлено, але launcher не завершився за 20 с")
                    p.kill(); p.wait(10)
            kill_h(hc); kill_h(hg)
        j = jname(); p, cst, out, _ = launch(j, "grandchild")                      # без консолі (DETACHED) → лише примусове завершення
        st = wait_file(cst); hc, hg = ph(st["child"]), ph(st["grandchild"])
        p.kill(); p.wait(10)
        add("J18.no-console-kill", exited(hc, 5) and exited(hg, 5), "без консолі: примусове завершення launcher-а → job закрито → нащадки завершені")
        kill_h(hc); kill_h(hg)
        b18 = snap(); j = jname(); p, cst, out, _ = launch(j, "grandchild")
        st = wait_file(cst); hc, hg = ph(st["child"]), ph(st["grandchild"]); hj = hold(j)
        p.kill(); p.wait(10); time.sleep(0.5)
        still = not exited(hc) and not exited(hg)
        trc = terminate(j); time.sleep(0.3)
        rc2, r2 = proof(j, base=b18, scope=os.getpid())
        add("J18.installer-held", still and trc == 0 and exited(hc, 5) and exited(hg, 5) and rc2 == 0,
            f"installer тримає handle job: після аварії launcher-а процеси живі ({still}) → terminate лише цього job → proof PASS (exit {rc2})")
        kill_h(hc); kill_h(hg); L.api.CloseHandle(hj)
        add("J18.winsw-timeout", False, "WinSW 2.12.0: stoptimeout / Ctrl+C від WinSW / примусове завершення службою — потрібна тестова служба", "NOT RUN")

    # ------------------------------------------------------------------ J19 одночасні launcher-и
    if run("J19"):
        j = jname(); marks = [tf(f"m{i}") for i in range(5)]
        ps = [launch(j, "marker", m) for m in marks]
        codes = []
        t = time.time()
        while time.time() - t < 20:
            codes = [x[0].poll() for x in ps]
            if sum(1 for c in codes if c is None) <= 1 and sum(1 for m in marks if os.path.exists(m)) >= 1:
                break
            time.sleep(0.1)
        running = [c for c in codes if c is None]; failed = [c for c in codes if c == 1]
        made = sum(1 for m in marks if os.path.exists(m))
        add("J19", len(running) == 1 and len(failed) == 4 and made == 1, f"5 launcher-ів з одним іменем job: працює {len(running)}, STOP {len(failed)}, запущено процесів {made}")
        for x in ps:
            x[0].kill(); x[0].wait(10)

    # ------------------------------------------------------------------ J21 (auditfix2) --scope-root: лише локальна репетиція
    if run("J21"):
        b21 = snap(); j21, h21 = test_job(L.job_sddl(ME))
        outside = subprocess.Popen([PY, "-I", "-c", "import time; time.sleep(30)"], creationflags=DETACHED)       # нащадок тесту (у scope)
        try:
            time.sleep(0.4)
            base = [PY, "-I", LAU, "proof", "--job", j21, "--expect-owner", ME, "--scan-sid", ME, "--unknown", "baseline", "--baseline", b21]
            r_in = subprocess.run(base + ["--scope-root", str(os.getpid())], capture_output=True, timeout=60, creationflags=DETACHED)
            r_other = subprocess.run(base + ["--scope-root", "4"], capture_output=True, timeout=60, creationflags=DETACHED)
            r_block = subprocess.run([PY, "-I", LAU, "proof", "--job", j21, "--expect-owner", ME, "--scan-sid", ME, "--unknown", "block", "--scope-root", str(os.getpid())], capture_output=True, timeout=60, creationflags=DETACHED)
            j_in = json.loads(r_in.stdout.decode("utf-8")); j_other = json.loads(r_other.stdout.decode("utf-8"))
            add("J21.in-scope", r_in.returncode == 2 and outside.pid in [a["pid"] for a in j_in["scan"]["alive"]], f"нащадок тесту в scope → виявлено (exit {r_in.returncode})")
            add("J21.out-of-scope", outside.pid not in [a["pid"] for a in j_other["scan"]["alive"]] and j_other.get("scan_scope") == [4], "процес поза деревом scope-root не розглядається (лише локальна адаптація)")
            add("J21.block-forbidden", r_block.returncode == 2 and "scope-root" in r_block.stdout.decode("utf-8", "replace") and json.loads(r_block.stdout.decode("utf-8"))["verdict"] == "BLOCKED", f"--scope-root із production-політикою --unknown block → BLOCKED (exit {r_block.returncode})")
        finally:
            outside.kill(); outside.wait(10); L.api.CloseHandle(h21)
    # ------------------------------------------------------------------ J20 власний вкладений job нащадка
    if run("J20"):
        j = jname()
        os.environ["V2TEST_LAUNCHER_DIR"] = HERE
        p, cst, out, _ = launch(j, "nested")
        st = wait_file(cst); hg = ph(st and st["grandchild"])
        inv2 = st and st["grandchild"] in (job_pids(j) or [])
        hj = hold(j); trc = terminate(j)
        add("J20", st and st["gc_in_inner"] and inv2 and trc == 0 and exited(hg, 5), f"нащадок створив власний job і онука в ньому → онук і в V2 job (PID-list: {inv2}); terminate V2 job завершує його")
        kill_h(hg); L.api.CloseHandle(hj); p.wait(10)
finally:
    for pid in cleanup_pids:
        h = ph(pid)
        if h and not exited(h):
            kill_h(h)
    time.sleep(0.5)
    shutil.rmtree(TMP, ignore_errors=True)

npass = sum(1 for _, s in results if s == "PASS"); nfail = sum(1 for _, s in results if s == "FAIL"); nnr = sum(1 for _, s in results if s == "NOT RUN")
print(f"Підсумок: {npass} PASS, {nfail} FAIL, {nnr} NOT RUN (усього {len(results)})")
sys.exit(1 if nfail else 0)
