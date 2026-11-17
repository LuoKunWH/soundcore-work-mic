# 第三方声明

诊断协议的帧、握手和音频布局来自 MIT 许可的上游，并在本目录中独立实现。

- 项目：tacshi/Soundcore
- 提交：`d296a1c5c0645797ff7cd3b55e93477a99820857`
- 版权：Copyright (c) 2026 Rocky Shi
- 许可：MIT，全文见 `third_party/licenses/tacshi-Soundcore-MIT-d296a1c.txt`

ozil56/SoundcoreForWindows 在 `3ea51c739a937f144be9c62a4a0b7e103ba3df03` 没有仓库级许可证。本目录没有收录或改写它的 Python 实现。

Windows 依赖从 PyPI 的官方 wheel 钉死，文件在 `third_party/wheels`，哈希同时写在 `requirements-windows.txt` 和 `third_party/wheels/SHA256SUMS`。安装命令使用 `--require-hashes --no-index --find-links`，不从网络重新解析版本。

| 分发包 | 版本 | 许可 | wheel SHA-256 |
| --- | --- | --- | --- |
| bleak | 3.1.0 | MIT | `3cb08e03039f6e477c276252540416b287d4e3de63a86732780ff93a2f6e73ef` |
| cffi | 2.1.1 | MIT-0 | `f53e442b08449d42821fa4a4fba000095af9f62742a500f978a9f557ec44339a` |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | `7afa5a6602a9f29af1f3a2965f831bae7c9d5d597b7cbb716d41ab3b7d89879c` |
| pycparser | 3.12 | BSD-3-Clause | `a076f3f489b39b43ed13563a1dafe42447445bec2e294154ec5c57fcdda4c85e` |
| PyOgg | 0.6.14a1 | BSD-3-Clause / 随包 Unlicense；原生库见 COPYING | `40f79b288b3a667309890885f4cf53371163b7dae17eb17567fb24ab467eca26` |
| sounddevice | 0.5.6 | MIT；内含 PortAudio，MIT | `7f4162f514f007b0bf25a3ccfed3f1705bc2ec311888a90232729eec4f57a4f4` |
| typing-extensions | 4.16.0 | PSF-2.0 | `481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8` |
| winrt-runtime | 4.1.0 | MIT | `01571f68755750d17518009c00ba21c799b4eddac805bf38cb869da08d38a73f` |
| winrt-windows-devices-bluetooth | 4!10.0.28000.2957 | MIT | `e39bcddf747396e2da78cb8c3d00c3e51214e5f1a9dc213fc009434c5264bbea` |
| winrt-windows-devices-bluetooth-advertisement | 4!10.0.28000.2957 | MIT | `ddf2b1bd17e92a63c892273fceb2a4aba3263123cba7be979b51e93ff7d7e32c` |
| winrt-windows-devices-bluetooth-genericattributeprofile | 4!10.0.28000.2957 | MIT | `3e95b316a941106fd8193dead1a31e6abf9f118efceb58da2388e943fcf5f6d8` |
| winrt-windows-devices-enumeration | 4!10.0.28000.2957 | MIT | `0d76f1961bede3dfaf92939ca16edb882daa97bf6481e2dadc8174fec64e7a7e` |
| winrt-windows-devices-radios | 4!10.0.28000.2957 | MIT | `466c47b468c381192218a6f8744d3f2966b43acd710f004bb8a4b4e4e1bcbf88` |
| winrt-windows-foundation | 4!10.0.28000.2957 | MIT | `0669de7ce480806a0f9a46d005837799e37f1738911b54c4bc04788b37974e69` |
| winrt-windows-foundation-collections | 4!10.0.28000.2957 | MIT | `0401c1b6ed512d1fdad8ba1571698e9000ebee6a69781db9a01994ffcc54a503` |
| winrt-windows-storage-streams | 4!10.0.28000.2957 | MIT | `e113832320f2e7f8b09cedfb400cb7eaf0ac769ad1f2038ddbe88801497916c4` |

各 wheel 内的许可证文本已抽出到 `third_party/licenses/`。WinRT 包的版权人是 Microsoft Corporation 与 David Lechner。

## 原生 Opus

只用 PyOgg Windows x64 wheel 中的 `pyogg/opus.dll`。

- SHA-256：`5fa25b62f72f880acf420120d8ca32d31997620cadaab26ae798d13355012d1b`
- 格式：PE32+ executable (DLL), x86-64
- 内嵌版本字符串：`libopus unknown`
- 使用的导出：`opus_get_version_string`、`opus_decoder_create`、`opus_decode`、`opus_decoder_destroy`
- 许可：wheel 内 `COPYING` 包含 Xiph.org Foundation 的 BSD 条款

Windows 上如果这个哈希不一致，`--check-env` 和实机路径都会拒绝加载，并且实机路径在打开蓝牙之前就退出。当前 Linux 环境没有执行这个 DLL。

## 播放库

`sounddevice==0.5.6` 的 Windows x64 wheel 来自 PyPI 项目 python-sounddevice（Matthias Geier，MIT）。许可全文在 `third_party/licenses/sounddevice-0.5.6-py3-none-win_amd64.whl__LICENSE`。

该 wheel 还带有 PortAudio 动态库。随包说明写明版权属于 Ross Bencina 与 Phil Burk，许可是 MIT；说明副本在 `third_party/licenses/sounddevice-0.5.6-py3-none-win_amd64.whl__portaudio-binaries-README.md`。同一个目录里还有一份启用 ASIO 的 DLL。sounddevice 只有在环境变量 `SD_ENABLE_ASIO` 存在时才加载它。本诊断检测到这个变量会直接退出，实际使用的是 `libportaudio64bit.dll`（MME、DirectSound、WDM/KS、WASAPI）。

VB-CABLE 本体没有放进本目录。它是 VB-Audio 的 Donationware，不是开源软件。
