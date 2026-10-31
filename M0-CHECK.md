# M0 检查表：动手前的四道验证

推进顺序按"**哪个卡住会推翻方案，就先验证哪个**"排。下面的每一步都有明确的通过/失败判据。

---

## 前置结论：两个新发现

### 发现 A：AGP 兼容性没问题（风险 R1 解除）

MAA-Meow 用的是 **AGP 9.4.1**。查了 Chaquopy 官方 changelog：

> 17.0.0（2025-12-01）— Android Gradle plugin versions **9.0 to 9.4** are now supported. (#1096)

且 17.2.0（2026-10-26）是当前最新版。**用 Chaquopy 17.2.0，AGP 9.4.1 在支持范围内。**

⚠️ 但官方 versions.html 表格仍写着 17.0 → AGP 7.3–9.2，与 changelog 不一致。**以 changelog 为准，用 17.2.0**。别用 16.x，它只到 AGP 8.8。

### 发现 B：onnxruntime 可能有坑，但**不阻塞 M0**

Chaquopy 的 Android wheel 仓库里，`onnxruntime` 能查到的可用版本停留在 **1.12.1 / 1.13.1**（cp38/cp39 时代）。而一条龙用的是 `onnxruntime-directml 1.18.0`（PC 专属）。

我这边没法直接访问 chaquo.com 的 wheel 仓库来确认 3.11/3.12 下是否有对应 wheel——**这条你需要自己验证**（见步骤 2）。

**但不阻塞 M0**，理由是：一条龙的识别分三档

| 识别方式 | 依赖 | Android 可行性 |
|---|---|---|
| 模板匹配 | `opencv-python-headless` | ✅ 有 Android wheel，**够用** |
| OCR（onnxocr） | `onnxruntime` | ⚠️ 待验证 |
| YOLO 目标检测 | `onnxruntime` | ⚠️ 待验证 |

而我们定的策略是「只做静态日常、不碰闪避」——**静态日常用模板匹配就够了**。所以先绕开 onnxruntime，等 M2 之后再说。

**如果后面确认没有 wheel**，三条退路（按成本排序）：
1. 自己用 NDK 编 onnxruntime 的 Android wheel（官方支持 Android 构建，可控但费时）
2. 用 `com.microsoft.onnxruntime:onnxruntime-android` AAR，从 Java 侧加载，Python 经 Chaquopy 调 Java（onnxocr 代码要改）
3. 换推理引擎（ncnn / MNN / TFLite），onnx 模型可转——改动最大

---

## 步骤 1：Chaoupy 能编进去（半天）

改 `settings.gradle.kts`，加插件声明：

```kotlin
plugins {
    id("com.chaquo.python") version "17.2.0" apply false
}
```

改 `app/build.gradle.kts`，在 plugins 块加一行 `id("com.chaquo.python")`，并追加：

```kotlin
chaquopy {
    defaultConfig {
        version = "3.11"          // 一条龙要求 >= 3.11.9
        // buildPython 必须与上面同 major.minor，本机装不了就指到具体路径
        // buildPython("/path/to/python3.11")
        pip {
            install("numpy")
            install("opencv-python-headless")   // 别装 opencv-python，它带 GUI 依赖
            install("pillow")
            install("pyyaml")
            install("shapely")
            // 先不要装 onnxruntime，见发现 B
        }
    }
}
```

`defaultConfig.ndk.abiFilters` 保持 `arm64-v8a` 即可。

**通过判据**：Gradle Sync 成功 + `assembleDebug` 编出 APK。
**失败处理**：若报 plugin apply 失败，说明 17.2.0 与 AGP 9.4.1 实际不兼容 → 回退到独立最小工程验证，或在仓库开 issue 问 Chaquopy。

---

## 步骤 2：依赖能装上（半天，紧跟步骤 1）

构建日志里会打印 pip 安装过程。确认没有出现 `No matching distribution found`。

然后顺手测一下 onnxruntime（就算不装，也想知道答案）：

```kotlin
install("onnxruntime")   // 临时加上，看报什么错
```

**通过判据**：numpy / cv2 / PIL / yaml / shapely 全部装成功。
**记录**：把 onnxruntime 的结果记下来（成功版本 / 报错信息），这决定 M2 之后要不要走退路。

---

## 步骤 3：Python 能在提权进程里起来（1 天）— **关键关卡**

这是整个方案最可能翻车的地方。Chaquopy 默认初始化在 App 主进程，而 `InputControlUtils` 的输入注入**必须跑在提权进程**，否则静默失败（不报错、完全没反应）。

在 `RemoteServiceImpl` 的初始化路径上加：

```kotlin
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

if (!Python.isStarted()) {
    Python.start(AndroidPlatform(context))   // context 来自 Shizuku user-service
}
```

然后放一个最小验证脚本 `app/src/main/python/zzz_bootstrap.py`，跑：

```python
import sys, platform
print("python:", sys.version)
import numpy, cv2
print("numpy:", numpy.__version__, "cv2:", cv2.__version__)
```

**通过判据**：提权进程的 logcat（tag `MaaMeow`）里能看到 Python 版本号。
**失败处理**：Python 起不来就退到「App 进程跑 Python + AIDL 传帧」，代价是每帧多一次跨进程拷贝，帧率下降——静态日常还能接受。

---

## 步骤 4：打通"看得见 + 点得到"（2–3 天）

前两步过了才做这步。用已经提交的 `maa_bridge.py` + `ZBridge.kt`：

```python
from maa_bridge import MaaBridge
b = MaaBridge()
img = b._frame_via_java()[0]      # 先用 Java 回退路径，ABI 最稳
print("frame shape:", img.shape if img is not None else None)
b.tap(500, 1200)
```

**通过判据**：`frame shape` 打出合理分辨率，且**游戏里真的被点了一下**。
**失败排查**：
- 拿不到帧 → 检查虚拟显示是否已建、`displayId` 是否设对
- 点了没反应 → 大概率是步骤 3 没过（Python 不在提权进程）
- 两者都通 → 切零拷贝路径（`BridgeLib` 的 `GetLockedPixels`），帧率显著提升

---

## 一句话总结

**步骤 1、2 在本地 Android Studio 里半天就能知道答案，先做这个。** 步骤 3 是真正的生死线。步骤 4 之前不要碰一条龙的业务代码。

跑完步骤 2 把 onnxruntime 的结果告诉我，我据此调整后续方案。
