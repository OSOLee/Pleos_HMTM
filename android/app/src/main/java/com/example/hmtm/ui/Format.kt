package com.example.hmtm.ui

import java.util.Calendar
import java.util.Locale
import java.util.TimeZone

/** 화면에 보이는 시각·길이 문구 */
object Format {

    /** "오늘 14:32" / "어제 09:05" / "11월 7일 14:32" / "2025년 11월 7일 14:32" */
    fun dayTime(ms: Long, now: Long = System.currentTimeMillis(), tz: TimeZone = TimeZone.getDefault()): String {
        val c = Calendar.getInstance(tz).apply { timeInMillis = ms }
        val n = Calendar.getInstance(tz).apply { timeInMillis = now }
        val hm = String.format(Locale.US, "%02d:%02d", c.get(Calendar.HOUR_OF_DAY), c.get(Calendar.MINUTE))
        val days = dayIndex(n) - dayIndex(c)
        return when {
            days == 0L -> "오늘 $hm"
            days == 1L -> "어제 $hm"
            c.get(Calendar.YEAR) == n.get(Calendar.YEAR) ->
                "${c.get(Calendar.MONTH) + 1}월 ${c.get(Calendar.DAY_OF_MONTH)}일 $hm"
            else -> "${c.get(Calendar.YEAR)}년 ${c.get(Calendar.MONTH) + 1}월 ${c.get(Calendar.DAY_OF_MONTH)}일 $hm"
        }
    }

    /** "14:32:05" */
    fun clock(ms: Long, tz: TimeZone = TimeZone.getDefault()): String {
        val c = Calendar.getInstance(tz).apply { timeInMillis = ms }
        return String.format(
            Locale.US, "%02d:%02d:%02d",
            c.get(Calendar.HOUR_OF_DAY), c.get(Calendar.MINUTE), c.get(Calendar.SECOND),
        )
    }

    /** "1분 00초" / "45초" */
    fun duration(ms: Long): String {
        val s = (ms + 500) / 1000
        return if (s >= 60) String.format(Locale.US, "%d분 %02d초", s / 60, s % 60) else "${s}초"
    }

    /** "12.3MB" / "850KB" */
    fun size(bytes: Long): String = when {
        bytes >= 1L shl 20 -> String.format(Locale.US, "%.1fMB", bytes / 1048576.0)
        else -> "${(bytes + 1023) / 1024}KB"
    }

    /** 영상 안 초 "18.2" (모르면 "?") */
    fun seconds(t: Double?): String = if (t == null || t.isNaN()) "?" else String.format(Locale.US, "%.1f", t)

    /** 받침 있으면 "이", 없으면 "가" ("승용차가", "화물차가"). 한글이 아니면 "이(가)" */
    fun iGa(word: String): String {
        val ch = word.trimEnd().lastOrNull() ?: return "이(가)"
        if (ch !in '가'..'힣') return "이(가)"
        return if ((ch - '가') % 28 == 0) "가" else "이"
    }

    /** "상대가 승용차가 아니었나요?" */
    fun notOtherCls(label: String): String = "상대가 $label${iGa(label)} 아니었나요?"

    private fun dayIndex(c: Calendar): Long =
        (c.timeInMillis + c.get(Calendar.ZONE_OFFSET) + c.get(Calendar.DST_OFFSET)) / 86_400_000L
}
