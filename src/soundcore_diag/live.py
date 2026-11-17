"""Explicit live path. Bleak is imported only while this path is running.

The route is one scan, or one confirmation scan plus one connection to the
address the operator typed. It sends device info, the ECDH handshake, and one
realtime transfer request for the file id carried by notification 1A/06.
Cleanup sends 1A/11 only after that request, then disconnects. The tray bridge
keeps the connection when the device ends a transfer, and asks again only
after the next 1A/06. It never sends recording start, pause, or stop.
"""

from __future__ import annotations

import asyncio
import sys
import signal
import time

from soundcore_diag.cable import CableMissing, CableUnavailable, open_cable_input
from soundcore_diag.harness import LinkClosed
from soundcore_diag.opus_pcm import OpusPcmDecoder, OpusUnavailable
from soundcore_diag.protocol import assert_tx_frame
from soundcore_diag.session import run_diagnostic

D3200_SERVICE = "020cf5da-0000-1000-8000-00805f9b34fb"
WRITE_CHAR = "00007777-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR = "00008888-0000-1000-8000-00805f9b34fb"
SCAN_SECONDS = 8.0
_COINIT_MULTITHREADED = 0x0
_S_OK = 0
_S_FALSE = 1


def _ensure_windows_mta() -> None:
    """Initialize COM as MTA before PortAudio, so Bleak can keep scanning."""
    if sys.platform != "win32":
        return
    import ctypes

    hr = ctypes.windll.ole32.CoInitializeEx(None, _COINIT_MULTITHREADED)
    # HRESULT is unsigned in some bindings; normalize.
    hr = hr & 0xFFFFFFFF
    if hr in {_S_OK, _S_FALSE}:
        return
    raise RuntimeError(f"无法把 COM 初始化成多线程模式（HRESULT=0x{hr:08X}）")

_REASONS = {
    "duration_cap": "已到本次时长上限",
    "transfer_finished": "对端结束了传输",
    "refused": "设备拒绝",
    "crypto_failure": "握手或解密失败",
    "decode_failure": "Opus 解码失败",
    "no_valid_pcm": "超时仍无有效 PCM",
    "no_active_file": "时限内没有当前录音通知",
    "timeout": "命令超时",
    "disconnected": "链路断开",
    "active_file_changed": "当前文件通知发生变化，已停止",
    "file_mismatch": "文件头与当前文件通知不一致",
    "notify_overflow": "通知过多，已停止",
    "protocol_error": "报文不符合约定",
    "link_error": "写入失败",
    "stopped": "已由 Ctrl+C 停止",
    "cable_error": "写入 CABLE Input 失败",
}


def _is_d3200(adv) -> bool:
    values = list(adv.service_uuids) + list(adv.service_data)
    for item in values:
        compact = str(item).lower().replace("-", "")
        if "020cf5da" in compact:
            return True
    return False


def _print_result(result) -> None:
    reason = _REASONS.get(result.stop_reason, "已停止")
    recording = "未知" if result.recording_byte is None else str(result.recording_byte)
    mic = "未知" if result.mic_battery_percent is None else str(result.mic_battery_percent)
    case = "未知" if result.case_battery_percent is None else str(result.case_battery_percent)
    print("诊断结束")
    print(f"停止原因: {reason}")
    print(f"固件字段(5字节，不是完整版本): {result.firmware_field or '未知'}")
    print(f"录音状态字节: {recording}")
    print(f"麦克风电量百分比: {mic}")
    print(f"充电盒电量百分比: {case}")
    print(f"通知次数: {result.notify_count}")
    print(f"分片数: {result.slice_count}")
    print(f"解密帧: {result.decrypted_frames}")
    print(f"PCM帧: {result.pcm_frames}")
    print(f"PCM采样: {result.pcm_samples}")
    print(f"时长毫秒: {result.duration_ms}")
    print(f"峰值绝对值: {result.peak_abs}")
    print(f"RMS: {result.rms:.2f}")
    print("已发送命令: " + ", ".join(result.command_names))
    print(f"传输停止命令已发送: {'yes' if result.transfer_stop_sent else 'no'}")
    if result.cable_writes is not None:
        print(f"写入 CABLE Input 的 PCM 帧: {result.cable_writes}")
    print("未发送录音开始、暂停或停止。未修改系统默认扬声器或麦克风。")


class BleakLink:
    def __init__(self, client) -> None:
        self.client = client
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=256)
        self.closed = False
        self.overflow = False
        self.write_char = None
        self.notify_char = None
        self.response = True
        self.loop = asyncio.get_running_loop()

    def _on_notify(self, _char, data: bytearray) -> None:
        payload = bytes(data)

        def _put() -> None:
            if self.closed:
                return
            try:
                self.queue.put_nowait(payload)
            except asyncio.QueueFull:
                self.overflow = True

        try:
            self.loop.call_soon_threadsafe(_put)
        except RuntimeError:
            self.overflow = True

    async def prepare(self) -> bool:
        service = None
        for item in self.client.services:
            if str(item.uuid).lower() == D3200_SERVICE:
                service = item
                break
        if service is None:
            return False
        for char in service.characteristics:
            uuid = str(char.uuid).lower()
            props = set(char.properties)
            if uuid == WRITE_CHAR and self.write_char is None:
                if "write" in props:
                    self.write_char = char
                    self.response = True
                elif "write-without-response" in props:
                    self.write_char = char
                    self.response = False
            if uuid == NOTIFY_CHAR and self.notify_char is None:
                if "notify" in props or "indicate" in props:
                    self.notify_char = char
        if self.write_char is None or self.notify_char is None:
            return False
        await self.client.start_notify(self.notify_char, self._on_notify)
        return True

    async def write(self, frame: bytes) -> None:
        if self.closed or self.overflow or self.write_char is None:
            raise LinkClosed()
        assert_tx_frame(frame)
        await self.client.write_gatt_char(self.write_char, frame, response=self.response)

    async def disconnect(self) -> None:
        await self.close()

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            if self.notify_char is not None:
                await self.client.stop_notify(self.notify_char)
        except Exception:
            pass
        try:
            await self.client.disconnect()
        except Exception:
            pass
        try:
            self.queue.put_nowait(None)
        except Exception:
            pass


async def _discover(scanner_cls, timeout: float, stop=None):
    async with scanner_cls() as scanner:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if stop is not None and stop():
                break
            await asyncio.sleep(min(0.2, max(0.0, end - time.monotonic())))
        return dict(scanner.discovered_devices_and_advertisement_data)


async def run_scan() -> int:
    from bleak import BleakScanner

    print("开始一次蓝牙扫描，最长 8 秒。这一步不连接。")
    found = await _discover(BleakScanner, SCAN_SECONDS)
    matched = []
    others = 0
    for address, (_device, adv) in found.items():
        if _is_d3200(adv):
            matched.append((address, adv))
        else:
            others += 1
    print(f"未匹配的其他广播数量: {others}（不显示地址）")
    if not matched:
        print("没有看到 D3200 服务 UUID。未连接。")
        return 2
    for index, (address, adv) in enumerate(matched, start=1):
        name = (adv.local_name or "").replace("\n", " ").replace("\r", " ").strip()
        print(f"{index:02d} address={address} rssi={adv.rssi} name={name} d3200=yes")
    print("扫描结束，未连接。请抄下 address，再执行带 --address 的命令。")
    print("蓝牙随机地址在断开后可能变化。下次若找不到，请重新扫描，不要沿用旧地址。")
    return 0


def _install_stop(loop, flag: dict[str, bool]):
    def handle_sigint(*_args) -> None:
        flag["stop"] = True

    def noop() -> None:
        return None

    try:
        loop.add_signal_handler(signal.SIGINT, handle_sigint)

        def restore_loop() -> None:
            try:
                loop.remove_signal_handler(signal.SIGINT)
            except Exception:
                pass

        return restore_loop
    except (NotImplementedError, RuntimeError, ValueError):
        pass

    try:
        previous = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, handle_sigint)

        def restore_signal() -> None:
            try:
                signal.signal(signal.SIGINT, previous)
            except Exception:
                pass

        return restore_signal
    except (ValueError, OSError, RuntimeError):
        # Tray worker threads on Windows cannot install SIGINT.
        # The caller already has a stop() callback for the menu.
        return noop


async def run_address(address: str, seconds: int | None, to_cable: bool = False) -> int:
    try:
        decoder = OpusPcmDecoder()
    except OpusUnavailable:
        print("解码器不可用，未打开蓝牙。")
        return 2
    sink = None
    restore_signal = None
    try:
        if to_cable:
            try:
                _ensure_windows_mta()
                sink = open_cable_input()
            except CableMissing as exc:
                print(str(exc))
                return 2
            except CableUnavailable as exc:
                print(str(exc))
                return 2
            print(
                f"已打开播放端 {sink.name}（{sink.hostapi}，{sink.channels} 声道，16000 Hz）。"
            )
            print("其他程序请把麦克风选成 CABLE Output。本程序只写 CABLE Input。")
            print("没有修改系统默认扬声器或麦克风。")
        from bleak import BleakClient, BleakScanner

        flag = {"stop": False}
        loop = asyncio.get_running_loop()
        restore_signal = _install_stop(loop, flag)

        def stop() -> bool:
            return flag["stop"]

        if to_cable:
            scan_for = SCAN_SECONDS
        else:
            if seconds is None:
                print("诊断时长缺失，未连接。")
                return 2
            deadline_budget = time.monotonic() + seconds
            scan_for = min(SCAN_SECONDS, deadline_budget - time.monotonic() - 2)
            if scan_for < 1:
                print("剩余时间不足，未连接。")
                return 2
        print("将只确认指定地址的 D3200 广播，确认后只连接这一台。")
        print("如果这个地址是上一次连接留下的，断开后它可能已经变化。扫不到就重新扫描。")
        found = await _discover(BleakScanner, scan_for, stop)
        if stop():
            print("已取消，未连接。")
            return 2
        device = None
        wanted = address.upper()
        for seen, (candidate, adv) in found.items():
            if seen.upper() == wanted and _is_d3200(adv):
                device = candidate
                break
        if device is None:
            print("未看到该地址的 D3200 广播，未连接。")
            print("请重新执行 --scan，并使用这次新看到的地址。程序不会自动重连。")
            return 2
        if to_cable:
            connect_timeout = 10.0
            bridge_deadline = None if seconds is None else time.monotonic() + seconds
        else:
            remain = deadline_budget - time.monotonic()
            connect_timeout = min(10.0, max(1.0, remain))
            bridge_deadline = deadline_budget
        client = BleakClient(
            device,
            pair=False,
            timeout=connect_timeout,
            services=[D3200_SERVICE],
        )
        link = BleakLink(client)
        try:
            await client.connect()
            if stop():
                print("已取消，已断开。")
                return 2
            if not await link.prepare():
                print("GATT 特征与诊断所需的写入/通知特征不一致，已断开。未发送录音控制。")
                return 2
            if to_cable and seconds is not None:
                bridge_deadline = time.monotonic() + seconds
            print("已订阅通知。请按下设备上的物理录音键。")
            print("若设备已经在录音且没有发出当前文件通知，需要你自行在设备上结束后再按一次。")
            print("本程序不会发送录音开始、暂停或停止。")
            if to_cable:
                if seconds is None:
                    print("桥接从现在开始，直到你按 Ctrl+C。扫描和连接不占用这段时间。")
                else:
                    print(f"桥接从现在开始，最长 {seconds} 秒。Ctrl+C 可以提前结束。")
                print("单声道 PCM 在双声道端点上会复制到左右声道。采样率保持 16000 Hz。")
            result = await run_diagnostic(
                link,
                decoder,
                deadline=bridge_deadline,
                pcm_timeout=8.0,
                command_timeout=5.0,
                sink=sink,
                stop=stop,
            )
            _print_result(result)
            if result.pcm_frames > 0 and result.stop_reason in {
                "duration_cap",
                "transfer_finished",
                "stopped",
            }:
                return 0
            return 2
        except Exception:
            print("连接或传输失败，已停止。没有改试其他认证或协议。")
            return 2
        finally:
            await link.close()
    finally:
        if sink is not None:
            sink.close()
        if restore_signal is not None:
            try:
                restore_signal()
            except Exception:
                pass
        decoder.close()



async def run_cable_session(stop=None, on_status=None) -> int:
    """Scan, pick the nearest D3200, and bridge until stop() is true.

    Status messages never include Bluetooth addresses. This does not change
    the system default playback or recording devices.
    """

    def status(message: str) -> None:
        if on_status is not None:
            on_status(message)
        print(message)

    try:
        decoder = OpusPcmDecoder()
    except OpusUnavailable:
        status("解码器不可用，未打开蓝牙。")
        return 2
    sink = None
    restore_signal = None
    try:
        try:
            _ensure_windows_mta()
            status("正在打开虚拟声卡…")
            sink = open_cable_input()
        except CableMissing as exc:
            status(str(exc))
            return 2
        except CableUnavailable as exc:
            status(str(exc))
            return 2
        status("虚拟声卡已打开。请在要用的软件里把麦克风选成 CABLE Output。")

        class _FirstPcmSink:
            def __init__(self, inner, notify) -> None:
                self._inner = inner
                self._notify = notify
                self._sent = False
                self.name = inner.name
                self.hostapi = inner.hostapi
                self.channels = inner.channels

            def write(self, mono_pcm: bytes) -> None:
                if not self._sent:
                    self._sent = True
                    self._notify()
                self._inner.write(mono_pcm)

            def rearm(self) -> None:
                self._sent = False

            def close(self) -> None:
                self._inner.close()

        def _on_first_pcm() -> None:
            status("正在传输声音。请在要用的软件里把麦克风选成 CABLE Output。")

        sink = _FirstPcmSink(sink, _on_first_pcm)

        def _on_rearm() -> None:
            sink.rearm()
            status("录音已暂停，连接还在。再按一下录音豆上的录音键，就会接着传声。")

        from bleak import BleakClient, BleakScanner

        flag = {"stop": False}
        loop = asyncio.get_running_loop()
        restore_signal = _install_stop(loop, flag)

        def should_stop() -> bool:
            return flag["stop"] or (stop is not None and stop())

        if should_stop():
            status("已取消，未连接。")
            return 2
        status("正在扫描录音豆…")
        found = await _discover(BleakScanner, SCAN_SECONDS, should_stop)
        if should_stop():
            status("已取消，未连接。")
            return 2
        matches = []
        for _address, (candidate, adv) in found.items():
            if _is_d3200(adv):
                rssi = adv.rssi if adv.rssi is not None else -999
                matches.append((rssi, candidate))
        if not matches:
            status("没有找到录音豆。请把它靠近电脑，并先断开手机上的连接后再试。")
            return 2
        matches.sort(key=lambda item: item[0], reverse=True)
        device = matches[0][1]
        status("已找到录音豆，正在连接…")
        client = BleakClient(
            device,
            pair=False,
            timeout=10.0,
            services=[D3200_SERVICE],
        )
        link = BleakLink(client)
        try:
            await client.connect()
            if should_stop():
                status("已取消，已断开。")
                return 2
            if not await link.prepare():
                status("设备特征不匹配，已断开。未发送录音控制。")
                return 2
            status("已连上。请按下录音豆上的录音键，灯变色后对着它说话。")
            result = await run_diagnostic(
                link,
                decoder,
                deadline=None,
                pcm_timeout=None,
                command_timeout=5.0,
                sink=sink,
                stop=should_stop,
                on_rearm=_on_rearm,
            )
            _print_result(result)
            reason = _REASONS.get(result.stop_reason, "已停止")
            if result.stop_reason == "stopped":
                status("桥接已停止。请再按一下录音豆上的键，把豆上的录音停掉。")
                return 0
            if result.stop_reason == "no_active_file":
                status("没有等到录音开始。若豆已经在录音，请先按停再按一次开始。")
                return 2
            if result.stop_reason == "no_valid_pcm":
                status("已连接但没有收到声音。请确认豆上已经开始录音后再试。")
                return 2
            if result.pcm_frames > 0 and result.stop_reason in {
                "duration_cap",
                "transfer_finished",
            }:
                status(f"桥接已结束（{reason}）。请再按一下豆上的键停掉录音。")
                return 0
            status(f"桥接已停止（{reason}）。请再按一下豆上的键停掉录音。")
            return 2
        except Exception:
            status("连接或传输失败，已停止。没有改试其他认证或协议。")
            return 2
        finally:
            await link.close()
    finally:
        if sink is not None:
            sink.close()
        if restore_signal is not None:
            try:
                restore_signal()
            except Exception:
                pass
        decoder.close()
