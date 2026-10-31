"""
maa_bridge.py — 让 Python 内核拿到 MAA-Meow 的截图与输入能力

设计要点
--------
1. 本模块运行在**提权进程**内（Shizuku user-service 或 Root 进程），
   与 libbridge.so / InputControlUtils 同一进程，因此无需跨进程传帧。
2. 截图走 ctypes 直调 bridge.so 导出的 GetLockedPixels()，零拷贝拿像素指针；
   失败时回退到 Java 侧 NativeBridgeLib.getFrameBufferBitmap()。
3. 输入不自己拼 C struct（struct-by-value 在 ARM64 上有 ABI 风险），
   改为通过 Chaquopy 调 Java 门面 ZBridge，复用其多指触控逻辑。
"""

from __future__ import annotations

import ctypes
import time
from typing import Optional

import numpy as np

# ----------------------------------------------------------------------------
# 与 src/main/native/bridge.h 保持一致的 ABI 定义
# ----------------------------------------------------------------------------


class FrameInfo(ctypes.Structure):
    """对应 C 侧 struct FrameInfo"""

    _fields_ = [
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("stride", ctypes.c_uint32),
        ("length", ctypes.c_uint32),
        ("data", ctypes.c_void_p),
        ("frame_ref", ctypes.c_void_p),
    ]


# enum MethodType（仅作记录，实际输入走 Java 门面）
METHOD_START_GAME = 1
METHOD_STOP_GAME = 2
METHOD_INPUT = 4
METHOD_TOUCH_DOWN = 6
METHOD_TOUCH_MOVE = 7
METHOD_TOUCH_UP = 8
METHOD_KEY_DOWN = 9
METHOD_KEY_UP = 10


class BridgeLoadError(RuntimeError):
    pass


class MaaBridge:
    """bridge.so + Java 门面的 Python 封装"""

    def __init__(self) -> None:
        self._lib = None
        self._load_native()

        # Chaquopy 提供的 Java 互操作；非 Android 环境下为 None（便于 PC 端单测）
        try:
            from java import jclass  # type: ignore

            self._jbridge = jclass("com.aliothmoon.maameow.zzz.ZBridge")
        except Exception:  # pragma: no cover - 仅 Android 生效
            self._jbridge = None

    # ---------------------------------------------------------------- 初始化
    def _load_native(self) -> None:
        """
        bridge.so 由 Java 侧 System.loadLibrary("bridge") 先行加载并完成
        JNI_OnLoad（注册 JavaVM、初始化 capturer）。此处 ctypes.CDLL 拿到的是
        同一个已加载的句柄，不会再触发一次 JNI_OnLoad。
        """
        try:
            lib = ctypes.CDLL("libbridge.so")
            lib.GetLockedPixels.restype = FrameInfo
            lib.GetLockedPixels.argtypes = []
            lib.UnlockPixels.restype = ctypes.c_int
            lib.UnlockPixels.argtypes = [FrameInfo]
            self._lib = lib
        except OSError as e:
            # 不抛异常：允许在纯 Java Bitmap 回退路径下工作
            self._lib = None
            print(f"[maa_bridge] ctypes 加载 libbridge.so 失败，将回退 Java 路径: {e}")

    @property
    def native_ready(self) -> bool:
        return self._lib is not None

    # ---------------------------------------------------------------- 截图
    def lock_frame(self) -> tuple[Optional[np.ndarray], Optional[FrameInfo]]:
        """
        锁定当前帧缓冲并拷贝为 numpy 数组。
        返回 (image, info)；info 必须传回 unlock_frame() 释放，否则会卡住采集线程。
        """
        if self._lib is None:
            return self._frame_via_java()

        info = self._lib.GetLockedPixels()
        if not info.data or info.length == 0 or info.width == 0:
            return None, None

        # stride 以像素为单位还是字节取决于 bridge 实现；这里按 4 字节 RGBA 兜底
        buf = ctypes.string_at(info.data, info.length)
        arr = np.frombuffer(buf, dtype=np.uint8)

        expected = info.height * info.stride * 4
        if arr.size < expected:
            return None, info

        arr = arr[: expected].reshape((info.height, info.stride, 4))
        arr = arr[:, : info.width, :]  # 去掉 stride 带来的行尾填充
        return arr, info

    def unlock_frame(self, info: Optional[FrameInfo]) -> None:
        if info is None or self._lib is None:
            return
        try:
            self._lib.UnlockPixels(info)
        except Exception as e:  # 释放失败不应影响主流程
            print(f"[maa_bridge] UnlockPixels 失败: {e}")

    def _frame_via_java(self) -> tuple[Optional[np.ndarray], Optional[FrameInfo]]:
        """
        回退路径：经 Java 拿 Bitmap，再拷到 numpy。
        比零拷贝慢（多一次 Bitmap 创建 + 拷贝），但 ABI 上最稳。
        """
        if self._jbridge is None:
            return None, None
        try:
            raw = self._jbridge.captureJpeg()  # byte[]
            if not raw:
                return None, None
            import cv2

            arr = np.frombuffer(bytes(raw), dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            return img, None
        except Exception as e:
            print(f"[maa_bridge] Java 回退截图失败: {e}")
            return None, None

    # ---------------------------------------------------------------- 输入
    def _require_jbridge(self):
        if self._jbridge is None:
            raise BridgeLoadError("ZBridge 不可用：Python 未运行在提权进程，或类未打包")
        return self._jbridge

    def touch_down(self, x: int, y: int, contact: int = 0) -> bool:
        return bool(self._require_jbridge().touchDown(int(x), int(y), contact))

    def touch_move(self, x: int, y: int, contact: int = 0) -> bool:
        return bool(self._require_jbridge().touchMove(int(x), int(y), contact))

    def touch_up(self, x: int, y: int, contact: int = 0) -> bool:
        return bool(self._require_jbridge().touchUp(int(x), int(y), contact))

    def tap(self, x: int, y: int, press_ms: int = 40) -> bool:
        """一次完整点击：down -> (可选停留) -> up"""
        ok = self.touch_down(x, y)
        if press_ms > 0:
            time.sleep(press_ms / 1000.0)
        return ok and self.touch_up(x, y)

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
        steps: int = 12,
        contact: int = 0,
    ) -> bool:
        """按住拖拽/滑动：down -> 插值 move -> up"""
        if not self.touch_down(x1, y1, contact):
            return False
        if steps > 0 and duration_ms > 0:
            interval = duration_ms / steps / 1000.0
            for i in range(1, steps + 1):
                t = i / steps
                self.touch_move(
                    int(x1 + (x2 - x1) * t), int(y1 + (y2 - y1) * t), contact
                )
                time.sleep(interval)
        return self.touch_up(x2, y2, contact)

    def key_down(self, key_code: int) -> bool:
        return bool(self._require_jbridge().keyDown(key_code))

    def key_up(self, key_code: int) -> bool:
        return bool(self._require_jbridge().keyUp(key_code))

    def input_text(self, text: str) -> bool:
        return bool(self._require_jbridge().inputText(text))
