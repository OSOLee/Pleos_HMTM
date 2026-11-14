package com.example.hmtm.data.bb

import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale
import kotlin.math.abs

/**
 * 차량 기록은 참고 자료 (docs/design-blackbox.md 4.4). 판정(result)은 영상·사용자 답 기준이고,
 * 차량 기록을 입증할 수 있으면 바뀌는 결과(result_with_vehicle)와 차이를 만든 기록(vehicle_effects),
 * 그래프용 요약(vehicle_timeline)을 따로 받는다.
 */

/** 질문 하나에 대한 차량 기록 값 (remaining[].vehicle_hint). 화면 "차량 기록: 켬" */
data class VehicleHint(
    val valueLabel: String,
    val text: String?,
    val determined: Boolean,
    val applied: Boolean,
    val reason: String?,
    val reasonText: String?,
) {
    companion object {
        fun parse(o: JSONObject?): VehicleHint? {
            if (o == null) return null
            return VehicleHint(
                valueLabel = o.optStringOrNull("value_label") ?: return null,
                text = o.optStringOrNull("text"),
                determined = o.optBoolean("determined"),
                applied = o.optBoolean("applied"),
                reason = o.optStringOrNull("reason"),
                reasonText = o.optStringOrNull("reason_text"),
            )
        }
    }
}

/** 두 판정의 차이를 만든 기록 한 줄 (vehicle_effects[]) */
data class VehicleEffect(
    val field: String,
    val label: String,
    val valueLabel: String,
    /** "내 차가 방향지시등을 켜지 않았어요" */
    val summary: String,
    /** 차량 규칙 문장 "사고 전 10초 동안 왼쪽 지시등을 켜지 않았어요" */
    val text: String?,
    /** true: result_with_vehicle에 들어감. false: 시각을 대략만 맞춰 쓰지 않음 (reasonText) */
    val applied: Boolean,
    val reasonText: String?,
    val egoDelta: Int?,
    /** ego_more / ego_less / changed */
    val direction: String,
    /** applied false일 때 정확히 맞았다면의 비율 (내 차, 상대) */
    val ifApplied: Pair<Int, Int>?,
) {
    /** "내 차 과실 +10" / "내 차 과실 −10" / "적용 기준이 바뀜" */
    val deltaText: String
        get() = when {
            egoDelta != null && egoDelta != 0 && direction != CHANGED ->
                "내 차 과실 ${if (egoDelta > 0) "+" else "−"}${abs(egoDelta)}"
            else -> "적용 기준이 바뀜"
        }

    companion object {
        const val EGO_MORE = "ego_more"
        const val EGO_LESS = "ego_less"
        const val CHANGED = "changed"

        fun list(a: JSONArray?): List<VehicleEffect> =
            if (a == null) emptyList() else (0 until a.length()).mapNotNull { a.optJSONObject(it)?.let(::parse) }

        fun parse(o: JSONObject): VehicleEffect {
            val f = o.optJSONObject("fault_by_party_if_applied")
            val ego = f?.optIntOrNull("ego")
            val other = f?.optIntOrNull("other")
            return VehicleEffect(
                field = o.optString("field"),
                label = o.optStringOrNull("label") ?: "차량 기록",
                valueLabel = o.optString("value_label"),
                summary = o.optStringOrNull("summary") ?: o.optString("text"),
                text = o.optStringOrNull("text"),
                applied = o.optBoolean("applied", true),
                reasonText = o.optStringOrNull("reason_text"),
                egoDelta = o.optIntOrNull("ego_delta"),
                direction = o.optStringOrNull("direction") ?: CHANGED,
                ifApplied = if (ego != null && other != null) ego to other else null,
            )
        }
    }
}

/** 충돌 전후 차량 기록 요약 (vehicle_timeline). 시각은 충돌 기준 초 (앞이 음수) */
data class VehicleTimeline(
    val fromS: Double,
    val toS: Double,
    /** (초, km/h). 기록이 없는 점은 km/h가 null */
    val speed: List<Pair<Double, Double?>>,
    val speedMax: Double?,
    val turnSignal: List<Span>,
    val brake: List<Span>,
    val gear: List<Span>,
    val gaps: List<Span>,
    val syncGrade: String?,
    /** 영상 충돌 순간과 그래프 0초가 맞는지 (fine). 아니면 "대략만 맞췄어요" */
    val aligned: Boolean,
    val t0Ms: Long?,
) {
    /** 구간: 지시등이면 label = LEFT/RIGHT, 기어면 P/R/N/D */
    data class Span(val from: Double, val to: Double, val label: String? = null)

    /** 그 초의 속도 (가장 가까운 점, 기록이 없으면 null) */
    fun speedAt(s: Double): Double? = speed.minByOrNull { abs(it.first - s) }?.second

    companion object {
        fun parse(o: JSONObject?): VehicleTimeline? {
            if (o == null) return null
            val sp = o.optJSONArray("speed") ?: JSONArray()
            return VehicleTimeline(
                fromS = o.optDouble("from_s", -15.0),
                toS = o.optDouble("to_s", 5.0),
                speed = (0 until sp.length()).mapNotNull { i ->
                    val p = sp.optJSONArray(i) ?: return@mapNotNull null
                    p.optDouble(0) to (if (p.isNull(1)) null else p.optDouble(1))
                },
                speedMax = o.optDoubleOrNull("speed_max"),
                turnSignal = spans(o.optJSONArray("turn_signal"), "dir"),
                brake = spans(o.optJSONArray("brake"), null),
                gear = spans(o.optJSONArray("gear"), "value"),
                gaps = spans(o.optJSONArray("gaps"), null),
                syncGrade = o.optStringOrNull("sync_grade"),
                aligned = o.optBoolean("aligned"),
                t0Ms = o.optLongOrNull("t0_ms"),
            )
        }

        private fun spans(a: JSONArray?, labelKey: String?): List<Span> =
            if (a == null) emptyList() else (0 until a.length()).mapNotNull { i ->
                val s = a.optJSONObject(i) ?: return@mapNotNull null
                Span(s.optDouble("from"), s.optDouble("to"), labelKey?.let { s.optStringOrNull(it) })
            }
    }
}

/** 기록 보기 화면의 요약 문구 (JVM 시험용으로 화면 밖에 둠) */
object TimelineText {
    /** "−6.0초" / "0초" / "+2.5초" */
    fun sec(s: Double): String = when {
        abs(s) < 0.05 -> "0초"
        s < 0 -> "−" + String.format(Locale.US, "%.1f초", -s)
        else -> "+" + String.format(Locale.US, "%.1f초", s)
    }

    fun dir(d: String?): String = when (d) {
        "LEFT" -> "왼쪽"
        "RIGHT" -> "오른쪽"
        "BOTH" -> "비상등"
        else -> "켜짐"
    }

    /** "부딪히기 6.0초 전부터 왼쪽 지시등" / "지시등을 켜지 않았어요" */
    fun turnSignal(t: VehicleTimeline): String {
        val before = t.turnSignal.filter { it.from <= 0.0 }
        if (before.isEmpty()) return "부딪히기 전에 지시등을 켜지 않았어요"
        val s = before.last()
        return if (s.to >= -0.05) "부딪히기 ${ago(s.from)}부터 ${dir(s.label)} 지시등을 켜고 있었어요"
        else "부딪히기 ${ago(s.from)}~${ago(s.to)} ${dir(s.label)} 지시등 (부딪힐 때는 꺼짐)"
    }

    /** "브레이크: 부딪히기 1.2초 전부터" */
    fun brake(t: VehicleTimeline): String {
        val first = t.brake.firstOrNull { it.to >= -3.0 } ?: return "부딪히기 직전 3초 동안 브레이크를 밟지 않았어요"
        return if (first.from <= -0.05) "부딪히기 ${ago(first.from)}부터 브레이크를 밟았어요"
        else "부딪힌 뒤에 브레이크를 밟았어요"
    }

    /** "부딪힐 때 속도 23km/h · 최고 43km/h" */
    fun speed(t: VehicleTimeline): String {
        val at = t.speedAt(-0.2) ?: t.speedAt(0.0)
        val parts = listOfNotNull(
            at?.let { "부딪힐 때 속도 ${kmh(it)}" },
            t.speedMax?.let { "이 구간 최고 ${kmh(it)}" },
        )
        return if (parts.isEmpty()) "속도 기록이 없어요" else parts.joinToString(" · ")
    }

    fun kmh(v: Double): String = "${Math.round(v)}km/h"

    private fun ago(s: Double): String = if (abs(s) < 0.05) "0초" else String.format(Locale.US, "%.1f초 전", -s)
}
