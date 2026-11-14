package com.example.hmtm.data.record

import android.content.Context
import java.io.File

/**
 * 기록 설정 (기기에 저장, SharedPreferences "settings").
 *  - consented: 첫 실행 안내에서 기록에 동의함. 동의 전에는 수집 서비스를 시작하지 않는다
 *  - autoRecord: 자동 기록 (끄면 서비스를 멈추고 부팅 때도 시작하지 않음)
 */
class RecordSettings(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences("settings", Context.MODE_PRIVATE)

    var consented: Boolean
        get() = prefs.getBoolean(KEY_CONSENTED, false)
        set(v) = prefs.edit().putBoolean(KEY_CONSENTED, v).apply()

    var autoRecord: Boolean
        get() = prefs.getBoolean(KEY_AUTO, true)
        set(v) = prefs.edit().putBoolean(KEY_AUTO, v).apply()

    /** 수집 서비스를 돌려도 되는지 */
    val shouldRecord: Boolean get() = RecordPolicy.shouldRecord(consented, autoRecord)

    companion object {
        private const val KEY_CONSENTED = "consented"
        private const val KEY_AUTO = "auto_record"
    }
}

object RecordPolicy {
    /** 수집 서비스를 돌려도 되는지: 동의했고 자동 기록이 켜져 있음 */
    fun shouldRecord(consented: Boolean, autoRecord: Boolean): Boolean = consented && autoRecord

    /** 이 차의 기록 파일 삭제: 루프 기록(files/loop)과 급제동 북마크(files/events). 지운 파일 수 */
    fun wipe(vararg dirs: File): Int = dirs.sumOf { dir ->
        (dir.listFiles() ?: emptyArray()).count { it.isFile && it.delete() }
    }
}
