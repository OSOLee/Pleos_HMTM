package com.example.hmtm.data.record

import com.example.hmtm.data.vehicle.VehicleSnapshot
import java.io.BufferedWriter
import java.io.File
import java.io.FileWriter
import java.util.Locale

/**
 * 블랙박스식 루프 기록기.
 * - 차량 상태를 1분 단위 CSV 파일(seg_<분 시작 시각>.csv)로 계속 저장
 * - 보관 기간(retentionMs)이 지난 파일은 cleanup()에서 삭제
 * 나중에 블랙박스 영상 시각으로 해당 구간 파일을 찾아 서버로 보낸다.
 */
class LoopRecorder(
    private val dir: File,
    private val retentionMs: Long,
) {
    private var writer: BufferedWriter? = null
    private var currentMinute = -1L
    private var linesSinceFlush = 0

    fun write(s: VehicleSnapshot) {
        val minute = s.timestamp / MINUTE * MINUTE
        if (minute != currentMinute) rotate(minute)
        writer?.apply {
            write(toCsv(s))
            newLine()
            // 1초(10줄)마다 디스크에 반영 → 갑자기 전원이 꺼져도 최대 1초만 손실
            if (++linesSinceFlush >= 10) {
                flush()
                linesSinceFlush = 0
            }
        }
    }

    private fun rotate(minute: Long) {
        close()
        dir.mkdirs()
        val file = File(dir, "seg_$minute.csv")
        val isNew = !file.exists()
        writer = BufferedWriter(FileWriter(file, true)).also {
            if (isNew) {
                it.write(HEADER)
                it.newLine()
            }
        }
        currentMinute = minute
    }

    /** 보관 기간이 지난 파일 삭제. 삭제한 개수 반환 */
    fun cleanup(now: Long = System.currentTimeMillis()): Int {
        val cutoff = now - retentionMs
        var deleted = 0
        segments().forEach { f ->
            val start = startOf(f) ?: return@forEach
            if (start + MINUTE < cutoff && f.delete()) deleted++
        }
        return deleted
    }

    fun segmentCount(): Int = segments().size

    fun close() {
        writer?.flush()
        writer?.close()
        writer = null
        currentMinute = -1
        linesSinceFlush = 0
    }

    private fun segments(): List<File> =
        dir.listFiles { f -> f.name.startsWith("seg_") && f.name.endsWith(".csv") }?.toList()
            ?: emptyList()

    companion object {
        const val MINUTE = 60_000L
        const val HEADER = "t,speedKmh,gear,turnSignal,brake"

        fun startOf(f: File): Long? =
            f.name.removePrefix("seg_").removeSuffix(".csv").toLongOrNull()

        fun toCsv(s: VehicleSnapshot): String = listOf(
            s.timestamp.toString(),
            s.speedKmh?.let { String.format(Locale.US, "%.2f", it) } ?: "",
            s.gear?.toString() ?: "",
            s.turnSignal ?: "",
            s.brakePedal ?: "",
        ).joinToString(",")
    }
}
