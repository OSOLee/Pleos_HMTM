package com.example.hmtm.data.record

import org.json.JSONObject
import java.io.File

/** 홈의 "사고 의심 순간" 한 줄: 급제동 이벤트 파일(files/events/event_<감지 ms>.json) 하나 */
data class Bookmark(
    val triggerAt: Long,
    val reason: String,
    val speedBefore: Float?,
    val speedAfter: Float?,
)

/**
 * 급제동 북마크 읽기. 이벤트 파일은 VehicleCollectorService가 감지 15초 뒤 버퍼(앞 45초 + 뒤 15초)를 저장한 것.
 * 속도는 "감지 1.5초 전 ~ 감지" 중 가장 빠른 값 → "감지 ~ 5초 뒤" 중 가장 느린 값으로 보여 준다.
 */
object Bookmarks {
    private const val BEFORE_MS = 1_500L
    private const val AFTER_MS = 5_000L

    fun list(eventsDir: File, limit: Int = 20): List<Bookmark> =
        (eventsDir.listFiles { f -> f.name.startsWith("event_") && f.name.endsWith(".json") } ?: emptyArray())
            .sortedByDescending { it.name.removePrefix("event_").removeSuffix(".json").toLongOrNull() ?: 0L }
            .take(limit)
            .mapNotNull { f -> runCatching { parse(f.readText()) }.getOrNull() }

    fun parse(json: String): Bookmark? {
        val o = JSONObject(json)
        val trigger = if (o.isNull("triggerAt")) return null else o.getLong("triggerAt")
        val arr = o.optJSONArray("samples")
        val points = buildList {
            if (arr != null) for (i in 0 until arr.length()) {
                val s = arr.getJSONObject(i)
                if (!s.isNull("speedKmh")) add(s.getLong("t") to s.getDouble("speedKmh").toFloat())
            }
        }
        val before = points.filter { it.first in (trigger - BEFORE_MS)..trigger }.maxOfOrNull { it.second }
        val after = points.filter { it.first in trigger..(trigger + AFTER_MS) }.minOfOrNull { it.second }
        return Bookmark(trigger, o.optString("reason", "hard_brake"), before, after)
    }
}
