package com.example.hmtm.data.video

import java.util.Calendar
import java.util.TimeZone

/** 촬영 시작 시각 후보 하나 (서버 meta.recorded_at의 한 칸, docs/design-blackbox.md 5.2) */
data class StartCandidate(val source: String, val startMs: Long)

/**
 * 촬영 시작 시각 추정 (설계 5.2): 파일 이름 → 메타데이터 → 파일 수정 시각 − 길이.
 * 서버(backend/src/blackbox/sync.py)도 같은 규칙으로 직접 읽어 고르므로, 앱은 후보를 모두 보내고
 * 차량 기록 구간을 자를 때만 가장 앞 후보를 쓴다.
 */
object StartTime {
    const val FILENAME = "filename"
    const val METADATA = "metadata"
    const val MTIME = "mtime"
    private val ORDER = listOf(FILENAME, METADATA, MTIME)

    // 서버 NAME_TIME과 같은 꼴: YYYYMMDD_HHMMSS (구분자 - _ . : T 공백 허용)
    private val NAME_TIME =
        Regex("""(?<!\d)(20\d\d)[-_.]?(\d\d)[-_.]?(\d\d)[-_T ]?(\d\d)[-_:.]?(\d\d)[-_:.]?(\d\d)(?!\d)""")

    // MediaMetadataRetriever METADATA_KEY_DATE: "20261109T053012.000Z" (UTC). 밀리초가 없을 수도 있음
    private val META_DATE = Regex("""^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(?:\.\d+)?Z?$""")

    /** 파일 이름 시각 → epoch ms. 시각은 기기 시간대(한국 UTC+9)로 본다. 없거나 날짜가 틀리면 null */
    fun fromFilename(name: String?, tz: TimeZone = TimeZone.getDefault()): Long? {
        val m = NAME_TIME.find(name?.substringAfterLast('/') ?: return null) ?: return null
        val (y, mo, d, h, mi, s) = m.destructured
        return strictMs(tz, y.toInt(), mo.toInt(), d.toInt(), h.toInt(), mi.toInt(), s.toInt())
    }

    /** 영상 메타데이터 날짜(UTC) → epoch ms. 2000년 전(mp4 기본값 1904 등)이면 null */
    fun fromMetadata(date: String?): Long? {
        val m = META_DATE.matchEntire(date?.trim() ?: return null) ?: return null
        val (y, mo, d, h, mi, s) = m.destructured
        if (y.toInt() !in 2000 until 2100) return null
        return strictMs(TimeZone.getTimeZone("UTC"), y.toInt(), mo.toInt(), d.toInt(), h.toInt(), mi.toInt(), s.toInt())
    }

    /** 후보 목록 (앞이 더 믿을 만함). 수정 시각은 녹화 끝으로 보고 길이를 뺀다 */
    fun candidates(
        filename: String?,
        metadataDate: String?,
        mtimeMs: Long?,
        durationMs: Long?,
        tz: TimeZone = TimeZone.getDefault(),
    ): List<StartCandidate> = buildList {
        fromFilename(filename, tz)?.let { add(StartCandidate(FILENAME, it)) }
        fromMetadata(metadataDate)?.let { add(StartCandidate(METADATA, it)) }
        if (mtimeMs != null && mtimeMs > 0 && durationMs != null) add(StartCandidate(MTIME, mtimeMs - durationMs))
    }.sortedBy { ORDER.indexOf(it.source) }

    /** 촬영 시각이 이상한지: 미래(5분 넘게)이거나 72시간(루프 기록 보관 기간)보다 오래됨 → "촬영 시각을 확인해 주세요" */
    fun suspicious(startMs: Long?, now: Long = System.currentTimeMillis()): Boolean =
        startMs != null && (startMs > now + 5 * 60_000L || startMs < now - 72 * 3_600_000L)

    /** 기기 시간대의 그 시각 UTC 차이(분). 서버가 파일 이름 시각을 같은 시간대로 읽게 meta.tz_offset_min으로 보냄 */
    fun tzOffsetMin(atMs: Long, tz: TimeZone = TimeZone.getDefault()): Int = tz.getOffset(atMs) / 60_000

    private fun strictMs(tz: TimeZone, y: Int, mo: Int, d: Int, h: Int, mi: Int, s: Int): Long? {
        val c = Calendar.getInstance(tz).apply {
            isLenient = false
            clear()
            set(y, mo - 1, d, h, mi, s)
        }
        return try {
            c.timeInMillis
        } catch (e: IllegalArgumentException) {   // 13월, 25시 같은 틀린 날짜
            null
        }
    }
}
