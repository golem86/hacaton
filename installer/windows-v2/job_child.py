"""
job_child.py — ТЕСТОВА фікстура для test_v2_job.py (не для production). Запускається launcher-ом усередині job.
  python job_child.py <режим> <state.json> [параметри]
Режими:
  sleep                — записати PID і спати
  grandchild           — створити онука (sleep), записати PID-и, спати
  orphan <go-file>     — створити онука, записати PID-и, дочекатися go-file і завершитися (онук лишається сиротою)
  breakaway            — спроба CreateProcess(CREATE_BREAKAWAY_FROM_JOB) + звичайний онук; записати коди й членство
  handles              — перевірити, що успадковано: handle job (V2TEST_JOB_HANDLE) і canary (V2TEST_CANARY_HANDLE) відсутні
  wmi                  — створити процес через WMI Win32_Process.Create (поза job), записати PID
  nested               — створити власний job і онука в ньому (JOB_LIST); записати PID-и
  marker <file>        — одразу створити файл-маркер (доказ, що процес виконав хоча б одну інструкцію)
"""
import sys as _sys
_sys.dont_write_bytecode = True          # не лишати __pycache__ у каталозі комплекту
import ctypes
import ctypes.wintypes as w
import json
import os
import subprocess
import sys
import time

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")
mode, state = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else None)
PY = sys.executable
SLEEP = [PY, "-I", "-c", "import time; time.sleep(120)"]


def save(d):
    d.setdefault("child", os.getpid())
    with open(state + ".tmp", "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(state + ".tmp", state)


def in_job_any(h):
    r = w.BOOL()
    k32.IsProcessInJob.argtypes = [w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)]
    k32.IsProcessInJob(h, None, ctypes.byref(r))
    return bool(r.value)


if mode == "marker":
    open(sys.argv[3], "w").close()
    time.sleep(60)
elif mode == "sleep":
    save({}); time.sleep(120)
elif mode == "grandchild":
    g = subprocess.Popen(SLEEP)
    save({"grandchild": g.pid}); time.sleep(120)
elif mode == "orphan":
    g = subprocess.Popen(SLEEP)
    save({"grandchild": g.pid})
    while not os.path.exists(sys.argv[3]):
        time.sleep(0.1)
    os._exit(0)
elif mode == "breakaway":
    class SI(ctypes.Structure):
        _fields_ = [("cb", w.DWORD)] + [(f"r{i}", ctypes.c_byte * 0) for i in range(0)] + [("pad", ctypes.c_byte * 100)]
    class PI(ctypes.Structure):
        _fields_ = [("hProcess", w.HANDLE), ("hThread", w.HANDLE), ("pid", w.DWORD), ("tid", w.DWORD)]
    si = SI(); si.cb = 104; pi = PI()
    k32.CreateProcessW.argtypes = [w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, w.BOOL, w.DWORD, ctypes.c_void_p, w.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p]
    cmd = ctypes.create_unicode_buffer(subprocess.list2cmdline(SLEEP))
    ok = k32.CreateProcessW(None, cmd, None, None, False, 0x01000000, None, None, ctypes.byref(si), ctypes.byref(pi))
    err = ctypes.get_last_error()
    if ok:                                     # якщо вихід із job раптом дозволено — фіксуємо і завершуємо цей процес
        k32.TerminateProcess(pi.hProcess, 9)
    g = subprocess.Popen(SLEEP)
    save({"breakaway_ok": bool(ok), "breakaway_error": err, "breakaway_pid": pi.pid if ok else None, "grandchild": g.pid})
    time.sleep(120)
elif mode == "handles":
    time.sleep(float(os.environ.get("V2TEST_DELAY", "0")))
    res = {}
    k32.GetHandleInformation.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    for key in ("V2TEST_JOB_HANDLE", "V2TEST_CANARY_HANDLE"):
        v = os.environ.get(key)
        if not v:
            res[key] = "no-env"; continue
        h = w.HANDLE(int(v)); f = w.DWORD()
        if not k32.GetHandleInformation(h, ctypes.byref(f)):
            res[key] = "absent"; continue
        if key == "V2TEST_JOB_HANDLE":           # той самий job? (IsProcessInJob(self, h) для чужого типу handle → помилка)
            r = w.BOOL()
            k32.GetCurrentProcess.restype = w.HANDLE      # псевдо-handle -1 — 64-бітний; без restype/argtypes обрізається до 32 біт
            k32.IsProcessInJob.argtypes = [w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)]
            ok = k32.IsProcessInJob(k32.GetCurrentProcess(), h, ctypes.byref(r))
            res[key] = "LEAKED-JOB" if ok and r.value else "other-object"
        else:                                    # canary — подія; перевіряємо ім'я через NtQueryObject
            buf = ctypes.create_string_buffer(1024); ln = ctypes.c_ulong()
            ntdll.NtQueryObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
            st = ntdll.NtQueryObject(h, 1, buf, 1024, ctypes.byref(ln))
            name = ""
            if st == 0:
                l = int.from_bytes(buf.raw[0:2], "little"); p = int.from_bytes(buf.raw[8:16], "little")
                name = ctypes.wstring_at(p, l // 2) if p else ""
            res[key] = "LEAKED-CANARY" if os.environ.get("V2TEST_CANARY_NAME", "?") in name else "other-object"
    try:
        sys.stdout.write("STDOUT-INHERITED\n"); sys.stdout.flush(); res["stdout"] = "ok"
    except Exception as e:
        res["stdout"] = f"fail {e}"
    save(res); time.sleep(120)
elif mode == "wmi":
    ps = os.path.join(os.environ["SystemRoot"], r"System32\WindowsPowerShell\v1.0\powershell.exe")
    cl = subprocess.list2cmdline(SLEEP)
    r = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command",
                        f"$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{{ CommandLine = '{cl}' }}; \"$($r.ReturnValue) $($r.ProcessId)\""],
                       capture_output=True, timeout=120)
    out = r.stdout.decode("utf-8", "replace").strip().split()
    save({"wmi_rc": int(out[0]) if out else -1, "wmi_pid": int(out[1]) if len(out) > 1 else None, "stderr": r.stderr.decode("utf-8", "replace")[-300:]})
    time.sleep(120)
elif mode == "nested":
    sys.path.insert(0, os.environ["V2TEST_LAUNCHER_DIR"])
    import v2_job_launcher as L
    inner = L.api.CreateJobObjectW(None, None)
    li = L.EXTENDED_LIMIT(); li.Basic.LimitFlags = L.REQUIRED_LIMITS
    L.api.SetInformationJobObject(inner, 9, ctypes.byref(li), ctypes.sizeof(li))
    pi = L.spawn_in_job(inner, SLEEP)
    save({"grandchild": pi.dwProcessId, "gc_in_inner": L.is_in_job(pi.hProcess, inner)})
    time.sleep(120)
else:
    sys.exit(f"невідомий режим {mode}")
