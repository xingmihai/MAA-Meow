"""
android_controller.py — 一条龙 ControllerBase 的 Android 实现

职责：把 MAA-Meow 的截图/输入能力，包装成一条龙内核认识的接口。

坐标体系说明（重要）
--------------------
一条龙的 click(pos) / drag_to(...) 传入的是**标准分辨率坐标系下的游戏窗口坐标**。
PC 版标准是 1920x1080 横屏，而绝区零手机版是竖屏，两者 UI 布局并不相同，
所以这里的换算**不是简单的等比缩放**：

  * 若资产已按手机竖屏重做（推荐，长期方案）：
      把 standard_width/height 设成资产所依据的分辨率，scale == 1.0，直通。
  * 若仍复用 PC 资产（仅用于早期通路验证）：
      等比缩放到手机分辨率，只能验证"能不能点动"，识别结果不可信。

因此本类把换算做成可配置，默认直通（scale=1.0）。
"""

from __future__ import annotations

import time

from cv2.typing import MatLike

from one_dragon.base.controller.controller_base import ControllerBase
from one_dragon.base.geometry.point import Point

from maa_bridge import MaaBridge


class AndroidController(ControllerBase):
    """
    一条龙在 Android 上的控制器。

    运行在提权进程内，直接持有 MaaBridge（同进程的截图/输入能力）。
    """

    def __init__(
        self,
        standard_width: int = 1080,
        standard_height: int = 2400,
        game_width: int = 1080,
        game_height: int = 2400,
        win_title: str = "绝区零",
        screenshot_alive_seconds: float = 5,
        max_screenshot_cnt: int = 0,
    ):
        super().__init__(
            screenshot_alive_seconds=screenshot_alive_seconds,
            max_screenshot_cnt=max_screenshot_cnt,
        )
        self.standard_width = standard_width
        self.standard_height = standard_height
        self.game_width = game_width
        self.game_height = game_height
        self.win_title = win_title

        self.bridge = MaaBridge()
        self._scale_x = game_width / standard_width
        self._scale_y = game_height / standard_height

    # ------------------------------------------------------------ 坐标换算
    def _to_screen(self, pos: Point) -> tuple[int, int]:
        """标准坐标 -> 实际屏幕坐标"""
        if pos is None:
            return self.game_width // 2, self.game_height // 2
        return int(pos.x * self._scale_x), int(pos.y * self._scale_y)

    # ------------------------------------------------------------ 生命周期
    def init_before_context_run(self) -> bool:
        """内核跑起来前的初始化：确认 bridge 已就绪"""
        if not self.bridge.native_ready:
            # ctypes 拿不到就走 Java 回退；两者都不可用时才判失败
            print("[AndroidController] 警告：libbridge.so 未走零拷贝，使用 Java 回退")
        return True

    def cleanup_after_app_shutdown(self) -> None:
        """释放资源。注意别在这里 destroy bridge，它由提权进程统一管理"""
        self.screenshot_history.clear()

    @property
    def is_game_window_ready(self) -> bool:
        """游戏是否在前台/虚拟显示中可用"""
        return self.get_screenshot() is not None

    # ------------------------------------------------------------ 截图
    def get_screenshot(self, independent: bool = False) -> MatLike | None:
        """
        取一帧并缩放到标准分辨率。
        注意 lock/unlock 必须成对，否则采集线程会被卡住。
        """
        image, info = self.bridge.lock_frame()
        try:
            if image is None:
                return None
            # bridge 给的是 RGBA
            if image.shape[2] == 4:
                import cv2

                image = cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)
            if (image.shape[1], image.shape[0]) != (
                self.standard_width,
                self.standard_height,
            ):
                import cv2

                image = cv2.resize(
                    image,
                    (self.standard_width, self.standard_height),
                    interpolation=cv2.INTER_LINEAR,
                )
            return image
        finally:
            self.bridge.unlock_frame(info)

    def fill_uid_black(self, screen: MatLike) -> MatLike:
        """
        PC 版用来遮挡 UID。手机截图不外传，默认不动。
        若后续要把截图带出设备，在这里做遮挡。
        """
        return screen

    # ------------------------------------------------------------ 点击 / 拖拽
    def click(
        self,
        pos: Point = None,
        press_time: float = 0,
        pc_alt: bool = False,
        gamepad_key: str | None = None,
    ) -> bool:
        """
        点击。press_time > 0 时视为长按。
        pc_alt / gamepad_key 是 PC 与手柄专属语义，Android 上忽略。
        """
        x, y = self._to_screen(pos)
        press_ms = int(press_time * 1000) if press_time and press_time > 0 else 40
        return self.bridge.tap(x, y, press_ms=press_ms)

    def drag_to(
        self,
        end: Point,
        start: Point | None = None,
        duration: float = 0.5,
        *,
        timing=None,
    ) -> None:
        """
        按住拖拽。timing 是 PC 端的三段时序控制，Android 上退化为均匀插值。
        """
        sx, sy = (
            self._to_screen(start)
            if start is not None
            else (self.game_width // 2, self.game_height // 2)
        )
        ex, ey = self._to_screen(end)
        self.bridge.swipe(
            sx, sy, ex, ey, duration_ms=int(duration * 1000), steps=12
        )

    def scroll(self, down: int, pos: Point | None = None) -> None:
        """
        滚动：down > 0 向下滚（内容上移），down < 0 向上滚。
        """
        x, y = self._to_screen(pos)
        distance = int(abs(down) * self._scale_y)
        if down > 0:
            end_y = max(0, y - distance)
        else:
            end_y = min(self.game_height, y + distance)
        self.bridge.swipe(x, y, x, end_y, duration_ms=300, steps=10)

    # ------------------------------------------------------------ 文本输入
    def input_str(self, to_input: str, interval: float = 0.1) -> None:
        """整段文本输入（需先由流程点中输入框）"""
        self.bridge.input_text(to_input)
        time.sleep(interval)

    def delete_all_input(self) -> None:
        """清空输入框：先用 KEYCODE 全选再删除"""
        KEYCODE_A = 29
        KEYCODE_DEL = 67
        try:
            from java import jclass  # type: ignore

            meta = jclass("android.view.KeyEvent").META_CTRL_ON
            self.bridge.key_down(KEYCODE_A)  # 具体修饰键由 ZBridge 侧处理
            self.bridge.key_up(KEYCODE_A)
        except Exception:
            pass
        self.bridge.key_down(KEYCODE_DEL)
        self.bridge.key_up(KEYCODE_DEL)

    # ------------------------------------------------------------ 游戏控制
    def close_game(self) -> None:
        """关闭游戏。交由 Java 侧按包名 force-stop"""
        try:
            self.bridge._require_jbridge().stopGame()
        except Exception as e:
            print(f"[AndroidController] close_game 失败: {e}")
