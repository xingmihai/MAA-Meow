package com.aliothmoon.maameow.zzz

import android.graphics.Bitmap
import android.view.Display
import com.aliothmoon.maameow.bridge.NativeBridgeLib
import com.aliothmoon.maameow.maa.InputControlUtils
import com.aliothmoon.maameow.third.Ln
import java.io.ByteArrayOutputStream

/**
 * ZBridge — 供 Python 内核（Chaquopy）调用的 Java 侧门面。
 *
 * 存在原因：
 *   1. Python 直接拼 C struct 按值调用 DispatchInputMessage 在 ARM64 上有 ABI 风险；
 *   2. 多指触控的槽位/时序逻辑已经在 InputControlUtils 里写好，没必要重写；
 *   3. 截图需要 Android framework 类型（Bitmap/Surface），交给 Java 最稳。
 *
 * 约束：本类的方法**必须运行在提权进程内**，否则 InputManager 注入与
 * 虚拟显示采集都会失败。
 *
 * 注意：Chaquopy 调用 Kotlin object 的方法需要 @JvmStatic，否则 Python 侧
 * 只能拿到实例方法而拿不到 companion 上的静态方法。
 */
object ZBridge {

    private const val TAG = "ZBridge"

    /**
     * 目标显示 ID。
     *  - 前台模式：Display.DEFAULT_DISPLAY (0)
     *  - 后台模式：虚拟显示的 displayId，由宿主在启动 Python 前注入
     */
    @Volatile
    var displayId: Int = Display.DEFAULT_DISPLAY
        private set

    /** 由宿主（RemoteServiceImpl 一类）在虚拟显示建好后调用 */
    @JvmStatic
    @Synchronized
    fun setDisplayId(id: Int) {
        displayId = id
        Ln.i("$TAG: displayId -> $id")
    }

    // ------------------------------------------------------------------ 输入

    @JvmStatic
    fun touchDown(x: Int, y: Int, contact: Int): Boolean {
        return try {
            InputControlUtils.down(x, y, contact, displayId)
        } catch (e: Throwable) {
            Ln.e("$TAG: touchDown failed", e)
            false
        }
    }

    @JvmStatic
    fun touchMove(x: Int, y: Int, contact: Int): Boolean {
        return try {
            InputControlUtils.move(x, y, contact, displayId)
        } catch (e: Throwable) {
            Ln.e("$TAG: touchMove failed", e)
            false
        }
    }

    @JvmStatic
    fun touchUp(x: Int, y: Int, contact: Int): Boolean {
        return try {
            InputControlUtils.up(x, y, contact, displayId)
        } catch (e: Throwable) {
            Ln.e("$TAG: touchUp failed", e)
            false
        }
    }

    /** 取消所有在场手指，异常分支收尾用 */
    @JvmStatic
    fun cancelTouch() {
        try {
            InputControlUtils.cancel(displayId)
        } catch (e: Throwable) {
            Ln.e("$TAG: cancelTouch failed", e)
        }
    }

    @JvmStatic
    fun keyDown(keyCode: Int): Boolean {
        return try {
            InputControlUtils.keyDown(keyCode, displayId)
        } catch (e: Throwable) {
            Ln.e("$TAG: keyDown failed", e)
            false
        }
    }

    @JvmStatic
    fun keyUp(keyCode: Int): Boolean {
        return try {
            InputControlUtils.keyUp(keyCode, displayId)
        } catch (e: Throwable) {
            Ln.e("$TAG: keyUp failed", e)
            false
        }
    }

    /**
     * 文本输入。走 InputControlUtils 的 INPUT 通道（转发给 bridge 的
     * DispatchInputMessage INPUT），需先由流程点中输入框。
     */
    @JvmStatic
    fun inputText(text: String): Boolean {
        return try {
            // TODO: 接 bridge 的 METHOD_INPUT 通道；当前 InputControlUtils 未暴露
            //       文本入口，需要在 InputControlUtils 增加一个 text(String, displayId)
            //       转发到 bridge_input.cpp 的 InputArgs。
            Ln.w("$TAG: inputText 尚未接线 (text=${text.length} chars)")
            false
        } catch (e: Throwable) {
            Ln.e("$TAG: inputText failed", e)
            false
        }
    }

    // ------------------------------------------------------------------ 截图

    /**
     * 抓一帧 JPEG，返回给 Python 解码。
     * 这是 ctypes 零拷贝路径的**回退方案**，比 GetLockedPixels 慢，
     * 但 ABI 上最稳，建议先用它跑通通路，再切零拷贝。
     */
    @JvmStatic
    fun captureJpeg(quality: Int = 90): ByteArray? {
        return try {
            val bmp: Bitmap = NativeBridgeLib.getFrameBufferBitmap() ?: return null
            val bos = ByteArrayOutputStream()
            bmp.compress(Bitmap.CompressFormat.JPEG, quality, bos)
            bmp.recycle()
            bos.toByteArray()
        } catch (e: Throwable) {
            Ln.e("$TAG: captureJpeg failed", e)
            null
        }
    }

    /** 帧计数器，用于判断是否还在出帧（卡死检测） */
    @JvmStatic
    fun frameCount(): Long = NativeBridgeLib.frameCount

    // ------------------------------------------------------------------ 游戏

    /** 按包名强停游戏。包名需在宿主侧配置好后传入 */
    @JvmStatic
    fun stopGame(): Boolean {
        return try {
            // TODO: 接 bridge 的 METHOD_STOP_GAME，或直接用 ActivityManager
            //       forceStopPackage（需要提权进程权限）
            Ln.w("$TAG: stopGame 尚未接线")
            false
        } catch (e: Throwable) {
            Ln.e("$TAG: stopGame failed", e)
            false
        }
    }
}
