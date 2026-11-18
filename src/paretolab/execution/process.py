"""Starting and stopping run processes, including everything they start themselves."""
import os
import signal
import subprocess

WINDOWS = os.name == "nt"
#: Own process group: Ctrl+C reaches only paretolab, which then stops the runs in order; no console window.
SPAWN_OPTIONS = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
                 if WINDOWS else {"start_new_session": True})


def spawn(args, cwd, log_file) -> subprocess.Popen:
    return subprocess.Popen(args, cwd=str(cwd), stdout=log_file, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            **SPAWN_OPTIONS)


def kill_tree(proc: subprocess.Popen, wait_s: float = 15.0) -> None:
    """Kill ``proc`` and its descendants (a solver may start helpers of its own)."""
    if proc.poll() is not None:
        return
    try:
        if WINDOWS:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.wait(timeout=wait_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=wait_s)


class KillOnExit:
    """Windows safety net: a Job Object that kills the runs if paretolab itself dies abruptly (window closed,
    process killed). Normal exits stop the runs explicitly; elsewhere this does nothing."""

    def __init__(self):
        self.job = None
        if not WINDOWS:
            return
        try:
            import ctypes
            from ctypes import wintypes

            class Basic(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class Io(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount",
                                                           "OtherOperationCount", "ReadTransferCount",
                                                           "WriteTransferCount", "OtherTransferCount")]

            class Extended(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", Io),
                            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.CreateJobObjectW.restype = wintypes.HANDLE
            k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            job = k32.CreateJobObjectW(None, None)
            if not job:
                return
            info = Extended()
            info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
                self._k32, self.job = k32, job
        except Exception:
            self.job = None

    def add(self, proc: subprocess.Popen) -> None:
        if self.job is not None:
            try:
                self._k32.AssignProcessToJobObject(self.job, int(proc._handle))
            except Exception:
                pass
