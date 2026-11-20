"""
v2_job_launcher.py — ЕКСПЕРИМЕНТАЛЬНА реалізація моделі повноти процесів backend V2 через Windows Job Object
(наказ №5 «COMPREHENSIVE VALIDATION & REMEDIATION», етап 2). НЕ ЗАТВЕРДЖЕНО для production; WinSW-конфігурація з
launcher-ом — лише тестова. Лише stdlib (ctypes); запуск: python -I -E -s v2_job_launcher.py <команда> …

  run --job NAME [--state FILE] -- <exe> [args…]
        Створює іменований job (захищений DACL, handle неуспадковуваний; ім'я вже існує → STOP), встановлює ліміти
        KILL_ON_JOB_CLOSE | DIE_ON_UNHANDLED_EXCEPTION без BREAKAWAY_OK/SILENT_BREAKAWAY_OK і перевіряє їх зчитуванням.
        Процес створюється атомарно в job (PROC_THREAD_ATTRIBUTE_JOB_LIST) і CREATE_SUSPENDED; bInheritHandles=TRUE лише
        з точним списком handle (PROC_THREAD_ATTRIBUTE_HANDLE_LIST: stdin/stdout/stderr). До ResumeThread — перевірка
        членства в job і лімітів; будь-яка помилка Win32 → TerminateJobObject, exit ≠ 0, жодного runnable-процесу.
        Ctrl+C/Break/Close → TerminateJobObject. Після виходу процесу залишки job (осиротілі нащадки) завершуються.
  proof --job NAME --expect-owner SID [--scan-sid SID] [--unknown block|baseline --baseline FILE] [--exclude-pid PID[,PID]]
        [--scope-root PID[,PID]]   — ЛИШЕ локальна репетиція: розглядати тільки нащадків цих PID (фонові процеси користувача поза тестом)
        Доказ зупинки: job знайдено; власник і DACL job точно очікувані; ліміти точно очікувані; ActiveProcesses = 0;
        PID-list порожній (з повторами при зміні розміру); жодного живого процесу з власником --scan-sid; процеси з
        невизначеним власником → BLOCKED (у локальному режимі baseline — лише ті, що існували до запуску). Вихід 0 — PASS,
        2 — BLOCKED, 1 — помилка. Друкує JSON.
  terminate --job NAME [--timeout S]   — TerminateJobObject лише цього job і очікування ActiveProcesses = 0
  hold --job NAME                      — утримувати handle job (QUERY|TERMINATE) до закриття stdin: job не зникає після виходу
                                         launcher-а, тож installer може довести ActiveProcesses = 0 після sc stop
  snapshot --out FILE                  — знімок процесів (PID, батько, час створення) для локального режиму baseline
  whoami                               — SID поточного процесу
"""
import ctypes
import ctypes.wintypes as w
import json
import os
import subprocess
import sys
import threading
import time

for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
adv = ctypes.WinDLL("advapi32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")
wts = ctypes.WinDLL("wtsapi32", use_last_error=True)

# --------------------------------------------------------------------------------------------- константи
KILL_ON_JOB_CLOSE = 0x2000
DIE_ON_UNHANDLED_EXCEPTION = 0x400
BREAKAWAY_OK = 0x800
SILENT_BREAKAWAY_OK = 0x1000
REQUIRED_LIMITS = KILL_ON_JOB_CLOSE | DIE_ON_UNHANDLED_EXCEPTION
JOB_ALL = 0x1F003F
JOB_ADMIN = 0x12000C                       # READ_CONTROL | SYNCHRONIZE | JOB_OBJECT_QUERY | JOB_OBJECT_TERMINATE
JOB_QUERY, JOB_TERMINATE, READ_CONTROL, SYNCHRONIZE = 0x4, 0x8, 0x20000, 0x100000
SID_SYSTEM, SID_ADMINS = "S-1-5-18", "S-1-5-32-544"
PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x20002
PROC_THREAD_ATTRIBUTE_JOB_LIST = 0x2000D
CREATE_SUSPENDED, CREATE_UNICODE_ENVIRONMENT, EXTENDED_STARTUPINFO_PRESENT = 0x4, 0x400, 0x80000
STARTF_USESTDHANDLES = 0x100
ERROR_ALREADY_EXISTS, ERROR_MORE_DATA, ERROR_INSUFFICIENT_BUFFER = 183, 234, 122
INVALID_HANDLE = ctypes.c_void_p(-1).value
EXIT_BLOCKED = 2


class Win32Error(Exception):
    def __init__(self, func, code=None):
        self.func = func
        self.code = ctypes.get_last_error() if code is None else code
        super().__init__(f"{func}: Win32 {self.code} ({ctypes.FormatError(self.code).strip() if self.code else 'немає коду'})")


class Stop(Exception):
    pass


# --------------------------------------------------------------------------------------------- структури
class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", w.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p), ("bInheritHandle", w.BOOL)]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in ("R", "W", "O", "RB", "WB", "OB")]


class BASIC_LIMIT(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", w.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", w.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]


class EXTENDED_LIMIT(ctypes.Structure):
    _fields_ = [("Basic", BASIC_LIMIT), ("Io", IO_COUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


class ACCOUNTING(ctypes.Structure):
    _fields_ = [("TotalUserTime", ctypes.c_longlong), ("TotalKernelTime", ctypes.c_longlong), ("ThisPeriodTotalUserTime", ctypes.c_longlong),
                ("ThisPeriodTotalKernelTime", ctypes.c_longlong), ("TotalPageFaultCount", w.DWORD), ("TotalProcesses", w.DWORD),
                ("ActiveProcesses", w.DWORD), ("TotalTerminatedProcesses", w.DWORD)]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("lpReserved", w.LPWSTR), ("lpDesktop", w.LPWSTR), ("lpTitle", w.LPWSTR), ("dwX", w.DWORD), ("dwY", w.DWORD),
                ("dwXSize", w.DWORD), ("dwYSize", w.DWORD), ("dwXCountChars", w.DWORD), ("dwYCountChars", w.DWORD), ("dwFillAttribute", w.DWORD),
                ("dwFlags", w.DWORD), ("wShowWindow", w.WORD), ("cbReserved2", w.WORD), ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", w.HANDLE), ("hStdOutput", w.HANDLE), ("hStdError", w.HANDLE)]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", w.HANDLE), ("hThread", w.HANDLE), ("dwProcessId", w.DWORD), ("dwThreadId", w.DWORD)]


class FILETIME(ctypes.Structure):
    _fields_ = [("lo", w.DWORD), ("hi", w.DWORD)]


# --------------------------------------------------------------------------------------------- Win32 API (через об'єкт api — тести підміняють окремі виклики)
def _fn(dll, name, res, *args):
    f = getattr(dll, name)
    f.restype = res
    f.argtypes = list(args)
    return f


class _Api:
    pass


api = _Api()
H, B, D, P = w.HANDLE, w.BOOL, w.DWORD, ctypes.c_void_p
api.CreateJobObjectW = _fn(k32, "CreateJobObjectW", H, P, w.LPCWSTR)
api.OpenJobObjectW = _fn(k32, "OpenJobObjectW", H, D, B, w.LPCWSTR)
api.SetInformationJobObject = _fn(k32, "SetInformationJobObject", B, H, ctypes.c_int, P, D)
api.QueryInformationJobObject = _fn(k32, "QueryInformationJobObject", B, H, ctypes.c_int, P, D, ctypes.POINTER(D))
api.TerminateJobObject = _fn(k32, "TerminateJobObject", B, H, ctypes.c_uint)
api.IsProcessInJob = _fn(k32, "IsProcessInJob", B, H, H, ctypes.POINTER(B))
api.InitializeProcThreadAttributeList = _fn(k32, "InitializeProcThreadAttributeList", B, P, D, D, ctypes.POINTER(ctypes.c_size_t))
api.UpdateProcThreadAttribute = _fn(k32, "UpdateProcThreadAttribute", B, P, D, ctypes.c_size_t, P, ctypes.c_size_t, P, P)
api.DeleteProcThreadAttributeList = _fn(k32, "DeleteProcThreadAttributeList", None, P)
api.CreateProcessW = _fn(k32, "CreateProcessW", B, w.LPCWSTR, w.LPWSTR, P, P, B, D, P, w.LPCWSTR, P, ctypes.POINTER(PROCESS_INFORMATION))
api.ResumeThread = _fn(k32, "ResumeThread", D, H)
api.TerminateProcess = _fn(k32, "TerminateProcess", B, H, ctypes.c_uint)
api.WaitForSingleObject = _fn(k32, "WaitForSingleObject", D, H, D)
api.GetExitCodeProcess = _fn(k32, "GetExitCodeProcess", B, H, ctypes.POINTER(D))
api.CloseHandle = _fn(k32, "CloseHandle", B, H)
api.GetStdHandle = _fn(k32, "GetStdHandle", H, D)
api.GetCurrentProcess = _fn(k32, "GetCurrentProcess", H)
api.DuplicateHandle = _fn(k32, "DuplicateHandle", B, H, H, H, ctypes.POINTER(H), D, B, D)
api.CreateFileW = _fn(k32, "CreateFileW", H, w.LPCWSTR, D, D, P, D, D, H)
api.GetHandleInformation = _fn(k32, "GetHandleInformation", B, H, ctypes.POINTER(D))
api.OpenProcess = _fn(k32, "OpenProcess", H, D, B, D)
api.GetProcessTimes = _fn(k32, "GetProcessTimes", B, H, ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME))
api.SetConsoleCtrlHandler = _fn(k32, "SetConsoleCtrlHandler", B, P, B)
api.OpenProcessToken = _fn(adv, "OpenProcessToken", B, H, D, ctypes.POINTER(H))
api.GetTokenInformation = _fn(adv, "GetTokenInformation", B, H, ctypes.c_int, P, D, ctypes.POINTER(D))
api.ConvertSidToStringSidW = _fn(adv, "ConvertSidToStringSidW", B, P, ctypes.POINTER(w.LPWSTR))
api.ConvertStringSecurityDescriptorToSecurityDescriptorW = _fn(adv, "ConvertStringSecurityDescriptorToSecurityDescriptorW", B, w.LPCWSTR, D, ctypes.POINTER(P), P)
api.GetSecurityInfo = _fn(adv, "GetSecurityInfo", D, H, ctypes.c_int, D, ctypes.POINTER(P), ctypes.POINTER(P), ctypes.POINTER(P), ctypes.POINTER(P), ctypes.POINTER(P))
api.GetSecurityDescriptorControl = _fn(adv, "GetSecurityDescriptorControl", B, P, ctypes.POINTER(w.WORD), ctypes.POINTER(D))
api.GetAce = _fn(adv, "GetAce", B, P, D, ctypes.POINTER(P))
api.LocalFree = _fn(k32, "LocalFree", P, P)
api.NtQuerySystemInformation = _fn(ntdll, "NtQuerySystemInformation", ctypes.c_long, ctypes.c_int, P, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong))
api.WTSEnumerateProcessesExW = _fn(wts, "WTSEnumerateProcessesExW", B, H, ctypes.POINTER(D), D, ctypes.POINTER(P), ctypes.POINTER(D))
api.WTSFreeMemoryExW = _fn(wts, "WTSFreeMemoryExW", B, ctypes.c_int, P, D)
hooks = {}                                  # лише для тестів: точки спостереження (after_create тощо); у production порожньо


def _hook(name, **kw):
    f = hooks.get(name)
    if f:
        f(**kw)


# --------------------------------------------------------------------------------------------- допоміжне
def sid_str(psid):
    s = w.LPWSTR()
    if not api.ConvertSidToStringSidW(psid, ctypes.byref(s)):
        raise Win32Error("ConvertSidToStringSidW")
    try:
        return s.value
    finally:
        api.LocalFree(s)


def process_owner_sid(hproc):
    tok = H()
    if not api.OpenProcessToken(hproc, 0x8, ctypes.byref(tok)):
        raise Win32Error("OpenProcessToken")
    try:
        need = D()
        api.GetTokenInformation(tok, 1, None, 0, ctypes.byref(need))
        buf = ctypes.create_string_buffer(max(need.value, 64))
        if not api.GetTokenInformation(tok, 1, buf, len(buf), ctypes.byref(need)):
            raise Win32Error("GetTokenInformation")
        return sid_str(ctypes.c_void_p.from_buffer(buf).value)
    finally:
        api.CloseHandle(tok)


def my_sid():
    return process_owner_sid(api.GetCurrentProcess())


def job_sddl(owner):
    return f"O:{owner}G:{owner}D:P(A;;0x{JOB_ALL:X};;;SY)(A;;0x{JOB_ALL:X};;;{owner})(A;;0x{JOB_ADMIN:X};;;BA)"


def query_limits(job):
    li = EXTENDED_LIMIT()
    if not api.QueryInformationJobObject(job, 9, ctypes.byref(li), ctypes.sizeof(li), None):
        raise Win32Error("QueryInformationJobObject(ExtendedLimit)")
    return li.Basic.LimitFlags


def query_active(job):
    a = ACCOUNTING()
    if not api.QueryInformationJobObject(job, 1, ctypes.byref(a), ctypes.sizeof(a), None):
        raise Win32Error("QueryInformationJobObject(Accounting)")
    return a.ActiveProcesses


def query_pids(job, tries=6):
    """PID-list із повторами при зміні розміру; не вдалося стабільно — Stop (BLOCKED)."""
    n = 64
    for attempt in range(tries):
        size = 8 + ctypes.sizeof(ctypes.c_size_t) * n
        buf = ctypes.create_string_buffer(size)
        ok = api.QueryInformationJobObject(job, 3, buf, size, None)
        err = ctypes.get_last_error()
        assigned, inlist = int.from_bytes(buf.raw[0:4], "little"), int.from_bytes(buf.raw[4:8], "little")
        if not ok and err != ERROR_MORE_DATA:
            raise Win32Error("QueryInformationJobObject(PidList)", err)
        if ok and assigned == inlist:
            arr = (ctypes.c_size_t * inlist).from_buffer(buf, 8) if inlist else []
            return [int(x) for x in arr], attempt
        n = max(n * 2, assigned + 16)
    raise Stop(f"PID-list job не стабілізувався за {tries} спроб (зміна розміру)")


def is_in_job(hproc, job):
    r = B()
    if not api.IsProcessInJob(hproc, job, ctypes.byref(r)):
        raise Win32Error("IsProcessInJob")
    return bool(r.value)


def inheritable(h):
    f = D()
    if not api.GetHandleInformation(h, ctypes.byref(f)):
        raise Win32Error("GetHandleInformation")
    return bool(f.value & 1)


# --------------------------------------------------------------------------------------------- run (launcher)
def create_job(name, owner):
    psd = P()
    if not api.ConvertStringSecurityDescriptorToSecurityDescriptorW(job_sddl(owner), 1, ctypes.byref(psd), None):
        raise Win32Error("ConvertStringSecurityDescriptorToSecurityDescriptorW")
    try:
        sa = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), psd, False)
        job = api.CreateJobObjectW(ctypes.byref(sa), name)
        err = ctypes.get_last_error()
    finally:
        api.LocalFree(psd)
    if not job:
        raise Win32Error("CreateJobObjectW", err)
    if err == ERROR_ALREADY_EXISTS:
        api.CloseHandle(job)
        raise Stop(f"job '{name}' уже існує (інший launcher або підміна імені) — старт заборонено")
    try:
        if inheritable(job):
            raise Stop("handle job успадковуваний — заборонено")
        li = EXTENDED_LIMIT()
        li.Basic.LimitFlags = REQUIRED_LIMITS
        if not api.SetInformationJobObject(job, 9, ctypes.byref(li), ctypes.sizeof(li)):
            raise Win32Error("SetInformationJobObject")
        got = query_limits(job)
        if got != REQUIRED_LIMITS:
            raise Stop(f"ліміти job 0x{got:X} ≠ очікуваним 0x{REQUIRED_LIMITS:X} (breakaway заборонено, kill-on-close обов'язковий)")
        return job
    except BaseException:
        api.CloseHandle(job)
        raise


def inheritable_std_handles():
    """Точний whitelist: дублікати stdin/stdout/stderr як успадковувані (відсутній → NUL)."""
    cur = api.GetCurrentProcess()
    out = []
    try:
        for i, std in enumerate((-10, -11, -12)):
            h = api.GetStdHandle(ctypes.c_ulong(std & 0xFFFFFFFF).value)
            dup = H()
            if h and h != INVALID_HANDLE and api.DuplicateHandle(cur, h, cur, ctypes.byref(dup), 0, True, 2):
                out.append(dup.value)
                continue
            sa = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
            nul = api.CreateFileW("NUL", 0xC0000000, 3, ctypes.byref(sa), 3, 0, None)
            if not nul or nul == INVALID_HANDLE:
                raise Win32Error("CreateFileW(NUL)")
            out.append(nul)
        return out
    except BaseException:
        for h in out:
            api.CloseHandle(h)
        raise


def spawn_in_job(job, argv, cwd=None):
    """Атомарно в job (JOB_LIST) + CREATE_SUSPENDED; перевірка членства й лімітів до ResumeThread. Повертає PROCESS_INFORMATION."""
    _hook("before_create", job=job)
    std = inheritable_std_handles()
    alist = None
    pi = PROCESS_INFORMATION()
    created = False
    try:
        size = ctypes.c_size_t(0)
        api.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
        if not size.value:
            raise Win32Error("InitializeProcThreadAttributeList(size)")
        alist = ctypes.create_string_buffer(size.value)
        if not api.InitializeProcThreadAttributeList(alist, 2, 0, ctypes.byref(size)):
            alist = None
            raise Win32Error("InitializeProcThreadAttributeList")
        harr = (H * len(std))(*std)
        jarr = (H * 1)(job)
        if not api.UpdateProcThreadAttribute(alist, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, harr, ctypes.sizeof(harr), None, None):
            raise Win32Error("UpdateProcThreadAttribute(HANDLE_LIST)")
        if not api.UpdateProcThreadAttribute(alist, 0, PROC_THREAD_ATTRIBUTE_JOB_LIST, jarr, ctypes.sizeof(jarr), None, None):
            raise Win32Error("UpdateProcThreadAttribute(JOB_LIST)")
        si = STARTUPINFOEXW()
        si.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        si.StartupInfo.dwFlags = STARTF_USESTDHANDLES
        si.StartupInfo.hStdInput, si.StartupInfo.hStdOutput, si.StartupInfo.hStdError = std
        si.lpAttributeList = ctypes.cast(alist, P)
        cmd = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        flags = CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT
        if not api.CreateProcessW(None, cmd, None, None, True, flags, None, cwd, ctypes.byref(si), ctypes.byref(pi)):
            raise Win32Error("CreateProcessW")
        created = True
        _hook("after_create", job=job, pi=pi)
        if not is_in_job(pi.hProcess, job):
            raise Stop(f"процес PID {pi.dwProcessId} поза job до старту — не запускається")
        if query_limits(job) != REQUIRED_LIMITS:
            raise Stop("ліміти job змінились до старту")
        _hook("before_resume", job=job, pi=pi)
        prev = api.ResumeThread(pi.hThread)
        if prev != 1:
            raise Win32Error("ResumeThread") if prev == 0xFFFFFFFF else Stop(f"ResumeThread повернув {prev}, очікується 1")
        return pi
    except BaseException:
        if created:
            api.TerminateJobObject(job, 0xE0)                    # процес ще suspended — завершується разом із job
            api.TerminateProcess(pi.hProcess, 0xE0)
            api.WaitForSingleObject(pi.hProcess, 5000)
            api.CloseHandle(pi.hThread); api.CloseHandle(pi.hProcess)
        raise
    finally:
        if alist is not None:
            api.DeleteProcThreadAttributeList(alist)
        for h in std:
            api.CloseHandle(h)


def wait_job_empty(job, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if query_active(job) == 0:
            return True
        time.sleep(0.1)
    return query_active(job) == 0


def cmd_run(opts, argv):
    name = opts.get("--job")
    if not name or not argv:
        raise Stop("потрібні --job NAME і -- <команда>")
    owner = my_sid()
    job = create_job(name, owner)
    stopping = threading.Event()

    @ctypes.WINFUNCTYPE(B, D)
    def on_ctrl(evt):                                             # Ctrl+C / Break / Close / Logoff / Shutdown
        stopping.set()
        api.TerminateJobObject(job, 0xC000013A)
        return True

    if not api.SetConsoleCtrlHandler(None, False):
        raise Win32Error("SetConsoleCtrlHandler(reset)")
    if not api.SetConsoleCtrlHandler(on_ctrl, True):
        raise Win32Error("SetConsoleCtrlHandler(register)")
    pi = spawn_in_job(job, argv)
    state = opts.get("--state")
    if state:
        with open(state + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"launcher": os.getpid(), "child": pi.dwProcessId, "job": name, "owner": owner}, f)
        os.replace(state + ".tmp", state)
    api.CloseHandle(pi.hThread)
    while api.WaitForSingleObject(pi.hProcess, 200) == 0x102:
        pass
    code = D(); api.GetExitCodeProcess(pi.hProcess, ctypes.byref(code)); api.CloseHandle(pi.hProcess)
    rest = query_active(job)
    if rest:
        print(f"launcher: процес завершився (код {code.value}); у job лишилось {rest} — TerminateJobObject", file=sys.stderr)
        api.TerminateJobObject(job, 0xE1)
    if not wait_job_empty(job, 15):
        print("launcher: job не спорожнів за 15 с", file=sys.stderr)
        return 3
    api.CloseHandle(job)
    return code.value if not stopping.is_set() else 0xC000013A


# --------------------------------------------------------------------------------------------- снімок процесів і власники
def process_snapshot():
    """NtQuerySystemInformation(SystemProcessInformation): {pid: (ppid, create_time, name)} — без відкриття процесів."""
    size = ctypes.c_ulong(1 << 20)
    for _ in range(8):
        buf = ctypes.create_string_buffer(size.value)
        st = api.NtQuerySystemInformation(5, buf, size, ctypes.byref(size))
        if st == 0:
            break
        if st & 0xFFFFFFFF != 0xC0000004:
            raise Win32Error("NtQuerySystemInformation", st & 0xFFFFFFFF)
        size = ctypes.c_ulong(size.value + (1 << 16))
    else:
        raise Stop("NtQuerySystemInformation: буфер не стабілізувався")
    out, off, raw = {}, 0, buf.raw
    while True:
        nxt = int.from_bytes(raw[off:off + 4], "little")
        ct = int.from_bytes(raw[off + 32:off + 40], "little", signed=True)
        ln = int.from_bytes(raw[off + 56:off + 58], "little")
        ptr = int.from_bytes(raw[off + 64:off + 72], "little")
        pid = int.from_bytes(raw[off + 80:off + 88], "little")
        ppid = int.from_bytes(raw[off + 88:off + 96], "little")
        name = ctypes.wstring_at(ptr, ln // 2) if ptr and ln else ""
        out[pid] = (ppid, ct, name)
        if not nxt:
            return out
        off += nxt


def owner_of(pid, ct, retries=1):
    """SID власника процесу (PID + час створення). None — визначити не вдалося (після повтору)."""
    for attempt in range(retries + 1):
        h = api.OpenProcess(0x1000, False, pid)
        if h:
            try:
                c, e, k, u = FILETIME(), FILETIME(), FILETIME(), FILETIME()
                if api.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
                    if ((c.hi << 32) | c.lo) != ct:
                        return "PID-REUSED"
                    return process_owner_sid(h)
            except Win32Error:
                pass
            finally:
                api.CloseHandle(h)
        time.sleep(0.05)
    return None


def in_scope(snap, pid, roots):
    """Нащадок одного з roots за ланцюжком батьків (батько створений раніше за дитину — захист від PID reuse)."""
    seen = 0
    while pid in snap and seen < 64:
        if pid in roots:
            return True
        ppid, ct = snap[pid][0], snap[pid][1]
        if ppid not in snap or snap[ppid][1] > ct:
            return False
        pid = ppid; seen += 1
    return pid in roots


def owner_scan(target_sid, unknown_policy="block", baseline=None, exclude=(), scope_roots=None):
    """Процеси з власником target_sid (живі) і процеси з невизначеним власником. Локальний режим baseline: процеси, що
    існували в знімку до запуску (PID + час створення), не розглядаються."""
    snap = process_snapshot()
    base = {(int(p), int(c)) for p, c in (baseline or [])}
    alive, unknown = [], []
    for pid, (ppid, ct, name) in snap.items():
        if pid in (0, 4) or pid in exclude:
            continue
        if ppid in exclude and name.lower() == "conhost.exe":       # консоль самого інструмента / процесу утримання handle
            continue
        if scope_roots and not in_scope(snap, pid, scope_roots):
            continue
        if baseline is not None and (pid, ct) in base:
            continue
        sid = owner_of(pid, ct)
        if sid == "PID-REUSED":
            continue
        if sid is None:
            unknown.append({"pid": pid, "ppid": ppid, "name": name})
        elif sid == target_sid:
            alive.append({"pid": pid, "ppid": ppid, "name": name})
    return alive, unknown


# --------------------------------------------------------------------------------------------- proof / terminate
def job_sd(job):
    owner, dacl, psd = P(), P(), P()
    rc = api.GetSecurityInfo(job, 6, 0x1 | 0x4, ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(psd))
    if rc != 0:
        raise Win32Error("GetSecurityInfo", rc)
    try:
        ctl, rev = w.WORD(), D()
        if not api.GetSecurityDescriptorControl(psd, ctypes.byref(ctl), ctypes.byref(rev)):
            raise Win32Error("GetSecurityDescriptorControl")
        aces = []
        if dacl.value:
            count = int.from_bytes(ctypes.string_at(dacl.value + 4, 2), "little")
            for i in range(count):
                pace = P()
                if not api.GetAce(dacl, i, ctypes.byref(pace)):
                    raise Win32Error("GetAce")
                atype, aflags = ctypes.string_at(pace.value, 2)
                mask = int.from_bytes(ctypes.string_at(pace.value + 4, 4), "little")
                aces.append((atype, aflags, mask, sid_str(pace.value + 8)))
        return sid_str(owner.value), bool(ctl.value & 0x1000), dacl.value != 0, aces
    finally:
        api.LocalFree(psd)


def check_sd(job, expect_owner):
    owner, protected, has_dacl, aces = job_sd(job)
    want = sorted([(0, 0, JOB_ALL, SID_SYSTEM), (0, 0, JOB_ALL, expect_owner), (0, 0, JOB_ADMIN, SID_ADMINS)])
    probs = []
    if owner != expect_owner:
        probs.append(f"власник job {owner} ≠ {expect_owner}")
    if not has_dacl or not protected:
        probs.append("DACL job відсутній або не захищений від успадкування")
    if sorted(aces) != want:
        probs.append(f"DACL job ≠ очікуваному: {[(hex(m), s) for _, _, m, s in aces]}")
    return probs


def cmd_proof(opts):
    name, expect = opts.get("--job"), opts.get("--expect-owner")
    if not name or not expect:
        raise Stop("потрібні --job і --expect-owner")
    rep = {"job": name, "found": False, "sd_ok": False, "limits_ok": False, "pids": [], "problems": []}
    pr = rep["problems"]
    job = api.OpenJobObjectW(JOB_QUERY | READ_CONTROL | SYNCHRONIZE, False, name)
    if not job:
        pr.append(f"job не знайдено або доступ заборонено: Win32 {ctypes.get_last_error()}")
    else:
        rep["found"] = True
        try:
            sdp = check_sd(job, expect); rep["sd_ok"] = not sdp; pr.extend(sdp)
            lim = query_limits(job); rep["limits"] = f"0x{lim:X}"; rep["limits_ok"] = lim == REQUIRED_LIMITS
            if lim != REQUIRED_LIMITS:
                pr.append(f"ліміти job 0x{lim:X} ≠ 0x{REQUIRED_LIMITS:X}")
            rep["active"] = query_active(job)
            pids, retries = query_pids(job); rep["pids"] = pids; rep["pid_list_retries"] = retries
            if rep["active"] or pids:
                pr.append(f"у job живі процеси: ActiveProcesses={rep['active']}, PID {pids}")
        except (Win32Error, Stop) as e:
            pr.append(f"запит job: {e}")
        finally:
            api.CloseHandle(job)
    scan = opts.get("--scan-sid")
    if scan:
        pol = opts.get("--unknown", "block")
        base = None
        if pol == "baseline":
            with open(opts["--baseline"], encoding="utf-8") as f:
                base = json.load(f)
        elif pol != "block":
            raise Stop("--unknown: block | baseline")
        try:
            excl = {os.getpid()} | {int(x) for x in (opts.get("--exclude-pid") or "").split(",") if x.strip()}
            roots = {int(x) for x in (opts.get("--scope-root") or "").split(",") if x.strip()} or None
            if roots and pol != "baseline":
                raise Stop("--scope-root дозволено лише з --unknown baseline (локальна репетиція)")
            alive, unknown = owner_scan(scan, pol, base, exclude=excl, scope_roots=roots)
            rep["scan_scope"] = sorted(roots) if roots else "all"
        except (Win32Error, Stop) as e:
            alive, unknown = [], [{"pid": -1, "name": f"сканування неможливе: {e}"}]
        rep["scan"] = {"sid": scan, "policy": pol, "alive": alive, "unknown": unknown}
        if alive:
            pr.append(f"живі процеси власника {scan}: {[(a['pid'], a['name']) for a in alive]}")
        if unknown:
            pr.append(f"процеси з невизначеним власником: {[(u['pid'], u['name']) for u in unknown][:20]}")
    else:
        pr.append("сканування за власником не виконано (--scan-sid обов'язковий для доказу)")
    rep["verdict"] = "PASS" if not pr else "BLOCKED"
    print(json.dumps(rep, ensure_ascii=False))
    return 0 if not pr else EXIT_BLOCKED


def cmd_terminate(opts):
    name, owner = opts.get("--job"), opts.get("--expect-owner")
    if not name or not owner:
        raise Stop("terminate потребує --job і --expect-owner")
    job = api.OpenJobObjectW(JOB_QUERY | JOB_TERMINATE | SYNCHRONIZE | READ_CONTROL, False, name)
    if not job:
        raise Win32Error("OpenJobObjectW")
    try:
        problems = check_sd(job, owner)
        limits = query_limits(job)
        if limits != REQUIRED_LIMITS:
            problems.append(f"ліміти job 0x{limits:X} ≠ 0x{REQUIRED_LIMITS:X}")
        if problems:
            raise Stop("terminate заблоковано: " + "; ".join(problems))
        # SD/limits і TerminateJobObject працюють з тим самим відкритим handle.
        if not api.TerminateJobObject(job, 0xE2):
            raise Win32Error("TerminateJobObject")
        ok = wait_job_empty(job, float(opts.get("--timeout", "15")))
        print(f"TERMINATE {'OK' if ok else 'TIMEOUT'} active={query_active(job)}")
        return 0 if ok else EXIT_BLOCKED
    finally:
        api.CloseHandle(job)


def cmd_hold(opts):
    job = api.OpenJobObjectW(JOB_QUERY | JOB_TERMINATE | SYNCHRONIZE, False, opts.get("--job"))
    if not job:
        print(f"HOLD FAIL Win32 {ctypes.get_last_error()}", flush=True)
        return EXIT_BLOCKED
    print("HOLD OK", flush=True)
    try:
        sys.stdin.read()                                          # до закриття stdin installer-ом
    finally:
        api.CloseHandle(job)
    return 0


def parse(argv):
    opts, rest = {}, []
    if "--" in argv:
        i = argv.index("--"); argv, rest = argv[:i], argv[i + 1:]
    it = iter(argv)
    for a in it:
        if a.startswith("--"):
            opts[a] = next(it, None)
    return opts, rest


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        print("STOP: потрібна архітектура x64", file=sys.stderr); return 1
    if not argv:
        print(__doc__, file=sys.stderr); return 1
    cmd, opts_rest = argv[0], parse(argv[1:])
    opts, rest = opts_rest
    try:
        if cmd == "run":
            return cmd_run(opts, rest)
        if cmd == "proof":
            return cmd_proof(opts)
        if cmd == "terminate":
            return cmd_terminate(opts)
        if cmd == "hold":
            return cmd_hold(opts)
        if cmd == "snapshot":
            with open(opts["--out"], "w", encoding="utf-8") as f:
                json.dump([[p, v[1]] for p, v in process_snapshot().items()], f)
            return 0
        if cmd == "whoami":
            print(my_sid()); return 0
        print(f"STOP: невідома команда {cmd}", file=sys.stderr); return 1
    except (Win32Error, Stop) as e:
        print(f"STOP: {cmd}: {e}", file=sys.stderr)
        return 1


def exit_code(rc):
    """Коди ≥ 0x80000000 (NTSTATUS, напр. 0xC000013A) — як знакові 32-бітні: інакше sys.exit на Windows дає -1 (0xFFFFFFFF)."""
    return ctypes.c_int32(rc & 0xFFFFFFFF).value


if __name__ == "__main__":
    sys.exit(exit_code(main()))
