package com.example.hmtm.data.bb

import org.json.JSONObject

/** 사건 목록 한 줄 (GET /api/bb-cases, docs/design-blackbox.md 3.6) */
data class BbSummary(
    val id: String,
    val status: String,
    val createdAt: Long,
    val recordedAtMs: Long?,
    val collisionT: Double?,
    val otherLabel: String?,
    val chapter: String?,
    val ruleId: String?,
    val title: String?,
    val egoFault: Int?,
    val otherFault: Int?,
    val display: BbCase.FaultDisplay?,
    val provisional: Boolean,
    val remainingCount: Int,
    val reason: String?,
    /** 차량 기록을 붙였는지 (서버 vehicle_record) */
    val vehicleRecord: Boolean = false,
    /** 차량 기록을 입증하면 결과가 바뀌는지 (vehicle_changes) */
    val vehicleChanges: Boolean = false,
    val displayWithVehicle: BbCase.FaultDisplay? = null,
    /** 사고 순간 확인 필요 (collision_review_needed) */
    val collisionReviewNeeded: Boolean = false,
    /** 사고 순간 고르기 기한 (epoch ms). 지났거나 고를 수 없으면 null */
    val collisionPickUntil: Long? = null,
) {
    val analyzing get() = status == BbCase.ANALYZING
    val finished get() = status == BbCase.NEEDS_ANSWERS || status == BbCase.DONE

    /** 결과 화면으로 열 수 있는 사건 (판정됨, 또는 사고 순간을 골라야 하는 no_collision) */
    val openable get() = finished || collisionReviewNeeded

    /** 사고 시각 = 촬영 시작 + 충돌 초, 모르면 사건 만든 시각 */
    val accidentAt: Long get() = recordedAtMs?.let { s -> collisionT?.let { s + (it * 1000).toLong() } ?: s } ?: createdAt

    companion object {
        fun parse(o: JSONObject): BbSummary {
            val f = o.optJSONObject("fault_by_party")
            return BbSummary(
                id = o.getString("id"),
                status = o.optString("status"),
                createdAt = o.optLong("created_at"),
                recordedAtMs = o.optLongOrNull("recorded_at_ms"),
                collisionT = o.optDoubleOrNull("collision_t"),
                otherLabel = o.optJSONObject("other_cls")?.optStringOrNull("label"),
                chapter = o.optStringOrNull("chapter"),
                ruleId = o.optStringOrNull("rule_id"),
                title = o.optStringOrNull("title"),
                egoFault = f?.optIntOrNull("ego"),
                otherFault = f?.optIntOrNull("other"),
                display = BbCase.faultDisplay(o.optJSONObject("fault_display")),
                provisional = o.optBoolean("provisional"),
                remainingCount = o.optInt("remaining_count", 0),
                reason = o.optStringOrNull("reason"),
                vehicleRecord = o.optBoolean("vehicle_record"),
                vehicleChanges = o.optBoolean("vehicle_changes"),
                displayWithVehicle = BbCase.faultDisplay(o.optJSONObject("fault_display_with_vehicle")),
                collisionReviewNeeded = o.optBoolean("collision_review_needed"),
                collisionPickUntil = o.optLongOrNull("collision_pick_until"),
            )
        }
    }
}
