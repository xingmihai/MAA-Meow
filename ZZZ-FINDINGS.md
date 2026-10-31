# ZZZ 移植：CI 实测结论（2026-10-31）

这份文档记录**实测数据**，取代之前的推测。所有结论都来自 GitHub Actions 的真实运行结果。

---

## 一、Chaquopy 路线：阻塞

### 现象

在 `main`（AGP 9.4.1）和 `zzz-chaquopy`（AGP 9.2.0）上都失败，错误信息完全一致：

```
An exception occurred applying plugin request [id: 'com.chaquo.python']
> Failed to apply plugin 'com.chaquo.python'.
   > Could not create plugin of type 'PythonPlugin'.
      > Could not generate a decorated class for type PythonPlugin.
         > com/android/build/api/variant/Variant
```

### 结论

Chaquo 的 `PythonPlugin` 字节码引用 `com.android.build.api.variant.Variant`，在 **AGP 9.x 下无法解析**。降到 9.2 也一样。

官方文档 android.html 写的是「AGP should be between **7.3.x and 9.2.x**」，而 changelog 写的「9.0 to 9.4」与之矛盾——**以实测为准，9.x 全线不通**。

要让它工作，得把 AGP 降到 8.13 及以下。而 MAA-Meow 用的是 Kotlin 2.4.21 / KSP 2.3.12 / compileSdk 37 / `androidComponents` 新 API，整体降级等于重写它的构建栈。**这条路放弃。**

---

## 二、Chaquo wheel 索引实测

探测时间 2026-10-31，索引 `https://chaquo.com/pypi-13.1`：

| 包 | cp38 | cp39 | cp310 | cp311 | cp312 | cp313 |
|---|---|---|---|---|---|---|
| numpy | ✅ | ✅ | ✅ 1.26.2 | ✅ 1.26.2 | ✅ | ✅ |
| **opencv-python-headless** | ✅ 4.1.2 | — | ✅ **4.5.1.48** | ❌ | ❌ | ❌ |
| **opencv-python** | ✅ | — | ✅ **4.5.1.48** | ❌ | ❌ | ❌ |
| pillow | ✅ | ✅ | ✅ 11.0.0 | ✅ | ✅ | ✅ |
| pyyaml | — | — | ✅ 6.0.3 | ✅ | ✅ | ✅ |
| **shapely** | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **scipy** | ✅ 1.4.1 | ✅ 1.8.1 | ✅ 1.8.1 | ❌ | ❌ | ❌ |
| **onnxruntime** | — | — | — | — | — | — |

### 两个要命的点

1. **onnxruntime 完全没有 Android wheel** —— 不是版本旧，是根本没有。
   一条龙的 OCR（`src/onnxocr`）和 YOLO 检测都依赖它，意味着**手机上跑不了神经网络推理**。
   模板匹配不依赖它，静态日常还能做，但自动战斗/空洞识别基本没戏。

2. **OpenCV 只有 4.5.1.48，且只在 cp310 及更早** —— 一条龙用的是 4.10.0。
   版本差 5 年，模板匹配行为可能有差异；而且把 Python 钉死在 3.10，
   一条龙声明的 `requires-python >= 3.11.9` 不满足。

---

## 三、重新评估：还值不值得上 Python

把三块成本摊开看：

| 成本项 | 原估计 | 实测后 |
|---|---|---|
| 平台层（截图/注入） | 复用 MAA-Meow | ✅ 不变，这块没受影响 |
| Python 运行时 | Chaquopy 塞进去 | ❌ **走不通**，需另找方案 |
| 识别依赖 | pip 装 | ❌ 缺 onnxruntime，OpenCV 版本也不对 |
| 业务代码 | 直接跑 | ⚠️ 需降级适配 Python 3.10 |
| 资产重做 | 大头 | ⚠️ 不变 |

**Python 带来的收益是「复用一条龙的 Python 代码」，但为此要付：运行时集成 + 依赖缺失 + 版本降级三重代价。**

而一条龙的 Python 代码里，真正值钱的是**资产**（模板图、screen_info 配置、空洞路网）和**业务逻辑**，不是 Python 语法本身。

---

## 四、建议改走：MaaFramework Pipeline

这是我认为现在最贴合的路线，理由是**它和 MAA-Meow 已经是同一套东西**：

- MAA-Meow 的 `bridge.so` 里 `TouchArgs.contact` 注释明确写着「对齐 **MaaFramework >= 5.13.0-beta.3** 的 `AndroidExternalLib.h`」
- workflow 里有 `maafw_tag` 输入，用于覆盖 `libMaaAndroidNativeControlUnit.so`
- 也就是说，**MAA-Meow 的原生桥接层本来就是按 MaaFramework 的接口规范写的**

MaaFramework 是 MAA 团队从 MaaAssistantArknights 抽出的**通用游戏自动化框架**：
用 JSON 描述识别与动作流水线，内置 OpenCV 模板匹配/特征匹配/OCR，支持自定义识别器与动作，官方提供 Android 预编译库。

**这样做的好处**：
- 平台层 100% 复用 MAA-Meow（提权、bridge、虚拟显示、Compose UI 全不动）
- 识别层用 C++ OpenCV，没有 wheel 问题，性能比 Python 强一个量级
- 一条龙的**资产可以复用**：模板图直接拿来，screen_info 的坐标逻辑改写成 Pipeline JSON
- 不需要 Chaquopy，不需要 Python，AGP 冲突消失

**代价**：一条龙的业务状态机（几十个 app 的 Python 代码）要改写成 Pipeline JSON + 少量自定义识别器。这部分工作量不小，但比「让 Python 在 Android 上跑起来」更可控。

---

## 五、如果坚持要 Python

退路只有两条，都不轻松：

1. **自己编 CPython 打进 APK**（不用 Chaquopy 插件）：
   python-for-android / Buildozer，或者手动交叉编译 CPython 3.11 + 打 wheel。
   可控但工程量以周计，且 onnxruntime 仍要自己 NDK 编。

2. **onnxruntime 走官方 Android AAR**：
   `com.microsoft.onnxruntime:onnxruntime-android` 是现成的，从 Java/Kotlin 侧加载，
   经 JNI 供调用。但 onnxocr 的 Python 代码要改成走 Java 桥，等于重写 OCR 层。

---

## 六、当前仓库状态

| 分支 | 状态 |
|---|---|
| `main` | 已回退 Chaquopy 改动，构建恢复。**只保留文档与 Python 骨架（不参与编译）** |
| `zzz-chaquopy` | 试验分支，AGP 9.2 + Chaquopy 17.2 + Python 3.10，**构建失败** |
| `ci-logs` | CI 诊断输出（`ci-report.txt`）、wheel 探测（`wheels-probe.txt`） |

`main` 上保留的 Python 文件（`app/src/main/python/`）在没有 Chaquopy 插件时不会被打包，
纯作参考。等路线定了再决定去留。
