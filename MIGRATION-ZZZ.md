# MAA-Meow → 绝区零一条龙 改造清单

fork 已完成：`https://github.com/xingmihai/MAA-Meow`
本文说明接下来要动哪些文件、按什么顺序动、以及每一步的验证标准。

---

## 零、先说清楚一个前提

**我没有把代码推到你的仓库。** 这份清单和配套骨架代码是本地产出的，需要你自己提交（或用下面的方式批量应用）。

配套文件：

| 文件 | 放进仓库的位置 |
|---|---|
| `python/maa_bridge.py` | `app/src/main/python/maa_bridge.py` |
| `python/android_controller.py` | `app/src/main/python/android_controller.py` |
| `kotlin/ZBridge.kt` | `app/src/main/java/com/aliothmoon/maameow/zzz/ZBridge.kt` |

---

## 一、三个决定改造路线的发现

### 发现 1：bridge.so 导出了干净的 C ABI

`app/src/main/native/bridge.h` 里只有三个导出函数：

```c
BRIDGE_API FrameInfo GetLockedPixels(void);
BRIDGE_API int UnlockPixels(FrameInfo info);
BRIDGE_API int DispatchInputMessage(MethodParam param);
```

这意味着 Python 可以用 `ctypes` 直接零拷贝拿帧，**不需要跨进程传图**。这是整个移植里最有价值的一块。

### 发现 2：输入不该自己拼 struct

`DispatchInputMessage` 是按值传 `MethodParam`（含 union，24 字节），ARM64 AAPCS 下按值传大 struct 有 ABI 风险，ctypes 容易踩坑。

**正确做法**：Python 通过 Chaquopy 调 Java 门面 `ZBridge`，复用现成的 `InputControlUtils`（已实现多指触控槽位管理）：

```java
InputControlUtils.down(int x, int y, int contact, int displayId)
InputControlUtils.move(int x, int y, int contact, int displayId)
InputControlUtils.up(int x, int y, int contact, int displayId)
InputControlUtils.keyDown(int keyCode, int displayId)
InputControlUtils.keyUp(int keyCode, int displayId)
```

### 发现 3：虚拟显示**不能直接照搬**

MAA-Meow 后台模式建 1280×720 虚拟显示，让明日方舟按标准 16:9 渲染，资产零改动复用。

**绝区零手机版是竖屏 UI**，强制横屏虚拟显示大概率导致 UI 错乱或游戏拒绝渲染。所以：

- 虚拟显示要按**竖屏比例**建（如 1080×2400 或降到 720×1600 省算力）
- PC 版资产（模板图、界面坐标、空洞路网）**仍然要重做**

这是全部工作量的大头，前面几轮已讨论过，不再赘述。

---

## 二、文件改动清单

### 2.1 新增

| 文件 | 作用 |
|---|---|
| `app/src/main/python/maa_bridge.py` | ctypes 封装 bridge.so + Java 回退 |
| `app/src/main/python/android_controller.py` | 实现一条龙 `ControllerBase` |
| `app/src/main/java/.../zzz/ZBridge.kt` | 供 Python 调用的 Java 门面 |
| `app/src/main/python/zzz_od/` | 一条龙业务代码整包拷贝过来 |

### 2.2 改造（摘掉 MaaCore）

| 现存文件 | 动作 |
|---|---|
| `maa/MaaCoreLibrary.java` | **删除**或保留但不用（JNA 绑 MaaCore，与一条龙无关） |
| `maa/MaaInstanceOptions.kt`、`maa/task/`、`maa/callback/` | 明日方舟任务定义，**全部弃用** |
| `remote/MaaCoreServiceImpl.kt` | 改造成加载 Python 内核的入口（见 M1） |
| `remote/RemoteServiceImpl.kt` | 保留不动，它是提权进程入口 |
| `native/` 整个目录 | **保留不动**，这是通用平台层，正是我们复用的东西 |
| `presentation/` Compose UI | 保留，改文案与任务列表 |

一句话：**只换内核，不动平台层。**

---

## 三、构建配置

`app/build.gradle.kts` 追加 Chaquopy：

```kotlin
plugins {
    id("com.chaquo.python") version "16.0.0"   // 版本需与 AGP 9.2.1 兼容，见风险 R1
}

chaquopy {
    defaultConfig {
        version = "3.11"
        buildPython = "3.11"      // 需本地有 CPython 3.11
        pip {
            install("numpy")
            install("opencv-python-headless")   // 不要装 opencv-python，无 GUI 依赖
            install("onnxruntime")              // Android 上只有 CPU/XNNPACK EP
            install("pillow")
            install("pyyaml")
            install("shapely")
        }
    }
}
```

`defaultConfig.ndk.abiFilters` 保持 `arm64-v8a`（Chaquopy 也只支持有限 ABI，别加 armeabi-v7a 徒增体积）。

**装不了的库**（PC 版依赖，Android 无对应 wheel）：
`pyautogui`、`pynput`、`mss`、`onnxruntime-directml`、`PySide6`。
这些的 import 链必须从一条龙源码里 stub 掉。

---

## 四、分步路线

### M0 — 打通"看得见 + 点得到"（1 周）

**目标**：Python 能拿到一帧、能让游戏响应一次点击。这是全部可行性验证的枢纽。

1. 接好 Chaquopy，先不放一条龙，只放一个 `hello.py` 验证 Python 能跑
2. 放 `maa_bridge.py` + `ZBridge.kt`
3. 建虚拟显示或前台启动游戏，`ZBridge.setDisplayId(id)`
4. Python 里跑：
   ```python
   from maa_bridge import MaaBridge
   b = MaaBridge()
   img, info = b.capture_jpeg_fallback()   # 先用 Java 回退路径，最稳
   b.tap(500, 1200)
   ```

**验证标准**：游戏里某处真的被点了一下。

⚠️ **必须先确认 Python 跑在提权进程里**。若 Python 在 App 进程，`InputControlUtils` 注入会静默失败（无 `INJECT_EVENTS` 权限）。初始化方式：

```kotlin
if (!Python.isStarted()) {
    Python.start(AndroidPlatform(context))   // context 来自 Shizuku user-service
}
```

M0 卡住的话后面都免谈，所以这一步要单独验证。

### M1 — 接上一条龙内核（1–2 周）

1. 把一条龙 `src/` 整体拷到 `app/src/main/python/` 下，保持包结构
2. 删掉/stub 掉平台相关 import：`pyautogui`、`pynput`、`mss`、`PySide6`、DirectML
3. 改 `MaaCoreServiceImpl` → 创建 `AndroidController`，驱动一条龙的 Operation 链
4. 用一条龙的**模板匹配**跑一次（先不上 YOLO/OCR）

**验证标准**：手机端能识别出主界面（不需要真的执行任务）。

### M2 — 第一个日常（1–2 周）

选最简单的静态界面，比如邮件领取。重做它的 `screen_info` 模板与坐标。

**验证标准**：全自动领完邮件。

### M3 — 扩展（持续）

咖啡 → 刮刮乐 → 影像店 → 体力本。
**不要碰自动闪避和式舆防卫战**，性能上限不够（前面算过约 11fps 闭环）。

---

## 五、风险清单

| 编号 | 风险 | 说明 | 应对 |
|---|---|---|---|
| **R1** | Chaquopy 与 AGP 9.2.1 兼容性 | MAA-Meow 用很新的 AGP 9.2.1 / KSP 2.3，Chaquopy 16 未必跟得上 | 先在一个空的 AGP 9 工程里验证 Chaquopy 能编过；不行就降 AGP |
| **R2** | Python 在提权进程初始化 | Shizuku user-service 进程能否正常起 Chaquopy 未经验证 | M0 第一件事就验证；失败则退回"App 进程 + AIDL 传帧"，代价是帧延迟上升 |
| **R3** | 绝区零在虚拟显示下能否渲染 | 3D 动作游戏可能拒绝离屏渲染、帧率暴跌，或检测投屏 | 先跑前台模式；后台模式作为可选增益 |
| **R4** | 磁盘/体积 | Chaquopy + numpy + opencv + onnxruntime + 一条龙资产，APK 会非常大 | 资产按需下载而非打进 APK；能砍的 wheel 都砍 |
| **R5** | 许可证 | MAA-Meow 是 **AGPL-3.0**（比一条龙的 GPL v3 更严），含网络场景开源义务 | 对外分发前确认能否接受 AGPL |
| **R6** | 账号风险 | root/注入行为在米哈游游戏里风险高于 PC 端 | 自行权衡 |

---

## 六、建议的第一个 commit

不要把清单一次性做完。建议第一提交只放这三样，让 M0 能跑起来：

```
feat(zzz): 接入 Chaquopy 与 Python 桥接层，打通截图与输入通路

- 新增 ZBridge，供 Python 调用多指触控注入
- 新增 maa_bridge，ctypes 直连 libbridge.so 抓帧
- 新增 AndroidController，实现一条龙 ControllerBase
- 尚未接入一条龙业务代码
```

跑通 M0 再往下走。**M0 不通，后面全是空谈。**
