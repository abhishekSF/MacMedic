from macmedic.processes import (
    ProcessInfo,
    classify_safety,
    classify_type,
    is_system_critical,
    resolve_app_name,
    top_by_cpu,
    top_by_memory,
)


def make_process(
    pid: int,
    name: str = "app",
    cpu: float = 0.0,
    mem: float = 0.0,
    user: str = "alice",
    cmd: tuple = (),
) -> ProcessInfo:
    return ProcessInfo(
        pid=pid,
        name=name,
        username=user,
        cpu_percent=cpu,
        memory_percent=mem,
        memory_rss=int(mem * 10**6),
        status="running",
        cmdline=cmd,
    )


def test_top_by_cpu_returns_sorted_top_n():
    procs = [
        make_process(1, "a", cpu=5.0),
        make_process(2, "b", cpu=90.0),
        make_process(3, "c", cpu=30.0),
    ]
    ranked = top_by_cpu(procs, 2)
    assert [p.pid for p in ranked] == [2, 3]


def test_top_by_memory_returns_sorted_top_n():
    procs = [
        make_process(1, "a", mem=2.0),
        make_process(2, "b", mem=50.0),
        make_process(3, "c", mem=9.0),
    ]
    ranked = top_by_memory(procs, 2)
    assert [p.pid for p in ranked] == [2, 3]


def test_top_by_cpu_filters_negative_values():
    procs = [
        make_process(1, "a", cpu=-1.0),
        make_process(2, "b", cpu=10.0),
    ]
    assert [p.pid for p in top_by_cpu(procs, 10)] == [2]


def test_top_by_cpu_empty():
    assert top_by_cpu([], 5) == []


def test_critical_kernel_task():
    assert is_system_critical("kernel_task", "root", ())


def test_critical_window_server():
    assert is_system_critical("WindowServer", "_windowserver", ())


def test_critical_root_daemon_by_suffix():
    assert is_system_critical("com.apple.helpd", "root", ("/usr/libexec/helpd",))


def test_non_critical_user_app():
    assert not is_system_critical("Chrome", "alice", ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",))


def test_non_critical_root_binary_without_suffix():
    assert not is_system_critical("MacMedic", "root", ("/Applications/MacMedic.app/Contents/MacOS/MacMedic",))


def test_non_critical_unknown():
    assert not is_system_critical("Terminal", "alice", ())


def test_critical_system_critical_ignores_username():
    assert is_system_critical("launchd", "root", ())


def test_resolve_app_name_from_exe():
    exe = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    assert resolve_app_name(exe, ()) == "Google Chrome"


def test_resolve_app_name_from_cmdline():
    exe = "/usr/libexec/ls"
    cmd = ("/Applications/Slack.app/Contents/MacOS/Slack", "--args")
    assert resolve_app_name(exe, cmd) == "Slack"


def test_resolve_app_name_none():
    assert resolve_app_name("/usr/libexec/helpd", ()) == ""


def test_classify_type_app():
    exe = "/Applications/MacMedic.app/Contents/MacOS/MacMedic"
    assert classify_type(exe, (), "alice") == "App"


def test_classify_type_daemon_root():
    assert classify_type("/usr/libexec/helpd", (), "root") == "Daemon"


def test_classify_type_plain_process():
    assert classify_type("", ("/opt/bin/tool",), "alice") == "Process"


def test_safety_safe_user_app():
    assert classify_safety("Chrome", "alice", ("/Applications/Google Chrome.app/...",), "Google Chrome", 123) == "safe"


def test_safety_caution_root_helper():
    assert classify_safety("somehelper", "root", ("/usr/libexec/somehelper",), "", 456) == "caution"


def test_safety_caution_finder():
    assert classify_safety("Finder", "alice", ("/System/.../Finder",), "Finder", 789) == "caution"


def test_safety_critical_kernel_task():
    assert classify_safety("kernel_task", "root", (), "", 0) == "critical"


def test_safety_critical_self():
    import os

    assert classify_safety("MacMedic", "alice", (), "MacMedic", os.getpid()) == "critical"
