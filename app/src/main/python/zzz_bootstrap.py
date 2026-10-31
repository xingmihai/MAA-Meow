"""
zzz_bootstrap.py — M0 步骤 3 的验证脚本

用途：确认 Python 解释器与其依赖，确实跑在**提权进程**里。
这一步过了，才谈得上截图与输入注入。

用法（Kotlin 侧）：
    val py = Python.getInstance()
    val mod = py.getModule("zzz_bootstrap")
    val report = mod.callAttr("probe").toString()
    Ln.i("bootstrap: $report")

返回 JSON 字符串，便于 Kotlin 侧直接解析或打印到 logcat。
"""

from __future__ import annotations

import json
import os
import platform
import sys


def _try_import(name: str) -> dict:
    """尝试导入并返回版本信息；失败时给出异常类型，方便定位是缺 wheel 还是 ABI 问题。"""
    try:
        mod = __import__(name)
        version = getattr(mod, "__version__", None)
        if version is None:
            version = getattr(mod, "VERSION", None)
        return {"ok": True, "version": str(version)}
    except Exception as e:  # noqa: BLE001 - 这里就是要把所有失败形态都报出来
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
        }


def probe() -> str:
    """探测运行环境，返回 JSON。"""
    info = {
        "python_version": sys.version,
        "python_impl": platform.python_implementation(),
        # 提权进程的 pid 与 uid 是关键判据：
        #   Shizuku user-service 进程 uid 通常是 2000(shell) 或 0(root)
        #   App 主进程则是 u0_aXXX（通常 >= 10000）
        "pid": os.getpid(),
        "uid": os.getuid() if hasattr(os, "getuid") else -1,
        "packages": {
            name: _try_import(name)
            for name in (
                "numpy",
                "cv2",
                "PIL",
                "yaml",
                "shapely",
                # onnxruntime 单独列出：它决定 OCR / YOLO 能否上，
                # 但不阻塞 M0（模板匹配只依赖 cv2）
                "onnxruntime",
            )
        },
    }

    # 顺带报一下能否触达 Java 门面 ZBridge。
    # 这同时验证了「Python 与 ZBridge 在同一进程」——
    # 若不在同一进程，jclass 会失败，输入注入也就无从谈起。
    try:
        from java import jclass  # type: ignore

        bridge = jclass("com.aliothmoon.maameow.zzz.ZBridge")
        info["zbridge"] = {
            "ok": True,
            "displayId": int(bridge.getDisplayId()),
            "frameCount": int(bridge.frameCount()),
        }
    except Exception as e:  # noqa: BLE001
        info["zbridge"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    return json.dumps(info, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    print(probe())
