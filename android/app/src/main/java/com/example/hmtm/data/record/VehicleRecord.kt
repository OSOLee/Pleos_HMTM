package com.example.hmtm.data.record

import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** 서버 samples 한 칸 (docs/api-spec.md 1절 변환표, 2.1) */
data class Sample(
    val t: Long,
    val speedKmh: Double?,
    val gear: String?,
    val turnSignal: String?,
    val brake: Boolean?,
)

/** 블랙박스 사건에 붙이는 차량 기록 (POST /api/bb-cases의 vehicle 칸) */
data class VehicleAttachment(val from: Long, val to: Long, val samples: List<Sample>) {
    fun toJson(appVersion: String): JSONObject = JSONObject()
        .put("range", JSONObject().put("from", from).put("to", to))
        .put("samples", JSONArray().apply {
            samples.forEach { s ->
                put(
                    JSONObject()
                        .put("t", s.t)
                        .put("speedKmh", s.speedKmh ?: JSONObject.NULL)
                        .put("gear", s.gear ?: JSONObject.NULL)
                        .put("turnSignal", s.turnSignal ?: JSONObject.NULL)
                        .put("brake", s.brake ?: JSONObject.NULL)
                )
            }
        })
        .put("vehicle", JSONObject().put("cls", "car"))
        .put("location", JSONObject.NULL)
        .put("client", JSONObject().put("app_version", appVersion))
}

/**
 * 루프 CSV(files/loop/seg_<분 시작 ms>.csv, 헤더 t,speedKmh,gear,turnSignal,brake)에서
 * 영상 구간에 맞는 줄을 잘라 samples로 바꾼다 (docs/design-blackbox.md 5.5).
 */
object VehicleRecord {
    const val MARGIN_MS = 15_000L          // 설계 5.5 여유 M
    const val MARGIN_MTIME_MS = 60_000L    // 시작 시각 출처가 파일 수정 시각뿐이면 M을 늘림 (서버 5.3의 ±60초와 같게)
    const val MAX_WINDOW_MS = 300_000L     // 서버 제한 (확정 Q12)
    const val MAX_SAMPLES = 20_000         // 서버 제한

    /** 구간 [S0 − M, S0 + D + M], 최대 300초 (앞쪽 여유는 지키고 끝을 줄임, 서버 vehicle_window와 같음) */
    fun window(startMs: Long, durationMs: Long?, startSource: String?): LongRange {
        val m = if (startSource == "mtime") MARGIN_MTIME_MS else MARGIN_MS
        val lo = startMs - m
        val hi = startMs + (durationMs ?: 0L) + m
        return lo..minOf(hi, lo + MAX_WINDOW_MS)
    }

    /** 구간의 기록. 한 줄도 없으면 null (→ 차량 기록 없이 영상만 올림) */
    fun attach(loopDir: File, range: LongRange): VehicleAttachment? {
        val samples = read(loopDir, range)
        if (samples.isEmpty()) return null
        return VehicleAttachment(range.first, range.last, samples.take(MAX_SAMPLES))
    }

    /** 구간에 걸친 분 파일을 이어 읽어 t 순으로 */
    fun read(loopDir: File, range: LongRange): List<Sample> {
        val first = range.first / LoopRecorder.MINUTE * LoopRecorder.MINUTE
        val files = (loopDir.listFiles { f -> f.name.startsWith("seg_") && f.name.endsWith(".csv") } ?: emptyArray())
            .mapNotNull { f -> LoopRecorder.startOf(f)?.let { it to f } }
            .filter { (start, _) -> start in first..range.last }
            .sortedBy { it.first }
        return files.asSequence()
            .flatMap { (_, f) -> runCatching { f.readLines() }.getOrDefault(emptyList()).asSequence() }
            .mapNotNull { parseLine(it) }
            .filter { it.t in range }
            .sortedBy { it.t }
            .toList()
    }

    /** CSV 한 줄 → Sample. 헤더·깨진 줄(전원이 갑자기 꺼져 반만 쓴 줄 등)은 null */
    fun parseLine(line: String): Sample? {
        if (line.isBlank() || line.startsWith("t,")) return null
        val c = line.split(',')
        if (c.size != 5) return null
        val t = c[0].trim().toLongOrNull() ?: return null
        return Sample(
            t = t,
            speedKmh = speed(c[1]),
            gear = gear(c[2]),
            turnSignal = turnSignal(c[3]),
            brake = brake(c[4]),
        )
    }

    /** "%.2f" 문자열, 빈칸이면 null. 음수·NaN도 null (서버는 0 이상만 받음) */
    fun speed(s: String): Double? = s.trim().toDoubleOrNull()?.takeIf { it.isFinite() && it >= 0.0 }

    /** VehicleGear 정수 → P/R/N/D (api-spec 6.2). 0·빈칸·모르는 값은 null, 수동 단수(16 이상)는 D */
    fun gear(s: String): String? = when (val g = s.trim().toIntOrNull()) {
        null, 0 -> null
        4 -> "P"
        2 -> "R"
        1 -> "N"
        8 -> "D"
        else -> if (g >= 16) "D" else null
    }

    /**
     * Pleos TurnSignal의 toString() → LEFT/RIGHT/OFF. "TurnSignalState.LEFT"처럼 앞에 이름이 붙어도 받는다.
     * 그 밖의 값(비상등 등 실차에서 확인할 것)은 null. 서버는 셋 말고는 422(sample_invalid)로 막는다.
     */
    fun turnSignal(s: String): String? =
        s.trim().substringAfterLast('.').uppercase().takeIf { it in SIGNALS }

    /** "true"/"false" → bool, 빈칸·그 밖 → null (VehicleBuffer.exportJson의 toBooleanStrictOrNull과 같음) */
    fun brake(s: String): Boolean? = s.trim().toBooleanStrictOrNull()

    private val SIGNALS = setOf("LEFT", "RIGHT", "OFF")
}
