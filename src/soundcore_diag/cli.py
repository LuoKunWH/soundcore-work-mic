"""Command line. Help, self-test, and environment check never import the live path."""

from __future__ import annotations

import re
import sys

_ADDRESS = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
_DIAG_MAX_SECONDS = 30
_CABLE_MAX_SECONDS = 8 * 60 * 60
_HELP = """\
soundcore 诊断（只做一次有限的链路检查，不是录音产品）

默认、--help、--self-test、--check-env 不会扫描或连接蓝牙，也不会打开声卡。

  python -m soundcore_diag
  python -m soundcore_diag --self-test
  python -m soundcore_diag --check-env
  python -m soundcore_diag live --consent --scan
  python -m soundcore_diag live --consent --address AA:BB:CC:DD:EE:FF [--seconds 30]
  python -m soundcore_diag live --consent --to-cable --address AA:BB:CC:DD:EE:FF [--seconds N]

--scan 只列出带有 D3200 服务 UUID 的广播，不连接。
--address 只连接这一台，并且这次广播必须能确认同一个 UUID。
蓝牙随机地址在断开后可能变化，找不到时要重新扫描。
不带 --to-cable 时，诊断默认并且最长 30 秒。
--to-cable 只把 16 kHz PCM 写到标准 VB-CABLE 的播放端 CABLE Input。
不写 --seconds 时，桥接会一直运行到 Ctrl+C。写了则从连接就绪起算，最长 8 小时。
程序不开始、停止或暂停设备录音，不绑定，不对时，不升级，不列出或下载历史文件。
不保存音频，不上传，也不修改系统默认扬声器或麦克风。
"""


def print_help() -> None:
    print(_HELP, end="")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args in ([], ["-h"], ["--help"]):
        print_help()
        return 0
    if args == ["--self-test"]:
        from soundcore_diag.selftest import run_self_test

        return run_self_test()
    if args == ["--check-env"]:
        from soundcore_diag.envcheck import run_check_env

        return run_check_env()
    if args and args[0] == "live":
        return _live(args[1:])
    print_help()
    return 2


def _live(args: list[str]) -> int:
    if "--consent" not in args:
        print("实时诊断必须同时给出 live 和 --consent。这次没有扫描或连接。")
        return 2
    scan = False
    address = None
    seconds = None
    seconds_set = False
    to_cable = False
    index = 0
    while index < len(args):
        item = args[index]
        if item == "--consent":
            index += 1
            continue
        if item == "--to-cable":
            to_cable = True
            index += 1
            continue
        if item == "--scan":
            scan = True
            index += 1
            continue
        if item == "--address":
            if index + 1 >= len(args):
                print("缺少地址。这次没有扫描或连接。")
                return 2
            address = args[index + 1]
            index += 2
            continue
        if item == "--seconds":
            if index + 1 >= len(args):
                print("缺少秒数。这次没有扫描或连接。")
                return 2
            try:
                seconds = int(args[index + 1])
            except ValueError:
                print("秒数必须是整数。这次没有扫描或连接。")
                return 2
            seconds_set = True
            index += 2
            continue
        print("无法识别的参数。这次没有扫描或连接。")
        return 2
    if to_cable and scan:
        print("--to-cable 不能和 --scan 一起用。请先扫描，再带 --address 运行。这次没有连接。")
        return 2
    if to_cable and address is None:
        print("请先扫描，再把这次看到的地址和 --to-cable 一起传入。这次没有连接。")
        print("断开后蓝牙随机地址可能变化，需要重新扫描。")
        return 2
    if scan == (address is not None):
        print("请只选择 --scan，或只选择 --address。不会自动连接。")
        return 2
    if not to_cable:
        if not seconds_set:
            seconds = _DIAG_MAX_SECONDS
        if seconds is None or not 1 <= seconds <= _DIAG_MAX_SECONDS:
            print("不向虚拟声卡输出时，时长必须在 1 到 30 秒之间。这次没有扫描或连接。")
            return 2
    elif seconds_set and (seconds is None or not 1 <= seconds <= _CABLE_MAX_SECONDS):
        print("桥接时长必须在 1 到 28800 秒之间。不写 --seconds 则会运行到 Ctrl+C。")
        print("这次没有扫描或连接。")
        return 2
    if not scan:
        if not _ADDRESS.match(address or ""):
            print("地址必须是 AA:BB:CC:DD:EE:FF 这种形式。这次没有连接。")
            return 2
        if address is None or address.upper() in {"00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF"}:
            print("这个地址不能作为目标。这次没有连接。")
            return 2
    import asyncio

    from soundcore_diag.live import run_address, run_scan

    if scan:
        return asyncio.run(run_scan())
    return asyncio.run(run_address(address or "", seconds, to_cable=to_cable))
