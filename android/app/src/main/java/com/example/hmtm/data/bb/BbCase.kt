package com.example.hmtm.data.bb

import org.json.JSONArray
import org.json.JSONObject

/**
 * 블랙박스 사건 응답 (docs/design-blackbox.md 3.6 "끝난 사건").
 * 분석이 끝나지 않았거나 ok가 아니면 {id, status, progress, analysis, sync}만 온다.
 * 앱은 서버가 준 문장·보기·추정값을 그대로 보여 준다 (근거 문장, 남은 질문, 비율 표기).
 */
data class BbCase(
    val id: String,
    val status: String,
    val progress: Int,
    val createdAt: Long?,
    val analysis: Analysis?,
    val result: Verdict?,
    /** 기본 판정에 쓴 값의 근거 (answers[].evidence), 차량 정보 → 영상 → 내 답변 → 가정 순 */
    val evidence: List<Evidence>,
    /** 실제로 답이 필요한 질문 (remaining), 서버 순서 그대로 */
    val remaining: List<Question>,
    /** remaining_count ("질문 N개 남음") */
    val remainingCount: Int,
    /** 사용자가 답한 값 (answers 중 source == user). PUT answers는 "지금까지의 답 전부"라 여기서 시작한다 */
    val userAnswers: Map<String, Any?>,
    /** 판정에 쓴 값 전부 (출처 무관). 질문 depends_on 판단용 */
    val values: Map<String, Any?> = emptyMap(),
    val vehicleRecord: Boolean,
    val syncGrade: String?,
    val otherCls: OtherCls?,
    val collisionT: Double?,
    /** 시각 맞추기의 촬영 시작 시각 (sync.start_ms) */
    val startMs: Long?,
    /** 답한 질문의 정의와 지금 답 (answered[]). 답변 고치기 = answered + remaining */
    val answered: List<Question> = emptyList(),
    /** 차량 기록을 입증할 수 있으면의 판정 (result_with_vehicle, 기록이 없으면 null) */
    val resultWithVehicle: Verdict? = null,
    /** 차이를 만든 기록 (결과가 같으면 빈 목록) */
    val vehicleEffects: List<VehicleEffect> = emptyList(),
    val timeline: VehicleTimeline? = null,
    /** 답하지 않은 질문 전부 (questions[], 선택 질문 포함). 여러 개 고르기·선택 질문은 여기서 */
    val questions: List<Question> = emptyList(),
    /** 서버 시각과 하루 넘게 다른 시계 (data_quality.clock_warnings, 없으면 sync.clock_warnings) */
    val clockWarnings: List<ClockWarning> = emptyList(),
    /** 시각 맞추기가 none인 이유 코드·문장 (data_quality.sync_reason·sync_reason_text, 없으면 sync.reason·reason_text) */
    val syncReason: String? = null,
    val syncReasonText: String? = null,
    /** 사고 순간 확인 (collision_review, design-blackbox 3.6). 없으면 null */
    val review: CollisionReview? = null,
) {
    /** 결과 화면을 보여 줄 사건: 판정됐거나, 판정은 못 했지만 사고 순간을 고르면 다시 분석할 수 있는 사건 */
    val showable get() = finished || review?.needed == true

    /** 결과를 바꾸는(반영된) 기록 */
    val appliedEffects get() = vehicleEffects.filter { it.applied }

    val analyzing get() = status == ANALYZING
    val finished get() = status == NEEDS_ANSWERS || status == DONE
    val failed get() = status in setOf(NO_COLLISION, UNSUPPORTED, FAILED)

    /** 선택 질문 (optional, remaining에 없음): 운전자 요인·특수 상황 같은 여러 개 고르기 */
    val optionalQuestions get() = questions.filter { it.optional && it.answerable }

    /**
     * 올린 차량 기록을 시각이 안 맞아 쓰지 않은 이유 (vehicle_clock_mismatch 등). "차량 기록 없음" 대신 서버 문장을 보인다.
     * 기록을 올리지 않았거나(no_vehicle_record) 영상 쪽 이유(촬영 시각·충돌 순간 모름)면 null
     */
    val vehicleUnusedText: String?
        get() = if (syncReason in VEHICLE_UNUSED_REASONS) syncReasonText else null

    /** 사고 시각 = 촬영 시작 + 충돌 초. 모르면 사건 만든 시각 */
    val accidentAt: Long?
        get() = startMs?.let { s -> collisionT?.let { s + (it * 1000).toLong() } ?: s } ?: createdAt

    data class Analysis(val status: String, val reason: String?, val message: String?)

    /** 시계 경고 한 줄 (kind: video_clock / vehicle_clock, message: 서버 문장) */
    data class ClockWarning(val kind: String, val direction: String?, val message: String) {
        val video get() = kind == VIDEO_CLOCK

        companion object {
            const val VIDEO_CLOCK = "video_clock"
            const val VEHICLE_CLOCK = "vehicle_clock"

            fun list(a: org.json.JSONArray?): List<ClockWarning> =
                if (a == null) emptyList() else (0 until a.length()).mapNotNull { i ->
                    val o = a.optJSONObject(i) ?: return@mapNotNull null
                    val msg = o.optStringOrNull("message") ?: return@mapNotNull null
                    ClockWarning(o.optString("kind"), o.optStringOrNull("direction"), msg)
                }
        }
    }

    /** result.fault_display: pedestrian_only면 text("보행자 과실 30%")가 머리 숫자, ratio면 내 차 : 상대 */
    data class FaultDisplay(val kind: String, val text: String, val note: String?) {
        val pedestrianOnly get() = kind == "pedestrian_only"
    }

    data class Verdict(
        val status: String,
        val provisional: Boolean,
        val ruleId: String?,
        val title: String?,
        val egoFault: Int?,
        val otherFault: Int?,
        val notice: String?,
        val chapter: String? = null,
        val display: FaultDisplay? = null,
    )

    /** 근거 한 줄: 출처(vehicle/video/user/default) + 서버 문장 */
    data class Evidence(val field: String, val source: String, val text: String)

    /** 상대 종류 (other_cls). source: video / user / guess / null */
    data class OtherCls(
        val value: String?,
        val label: String?,
        val source: String?,
        val chapter: String?,
        val options: List<Any?>,
        val choices: List<String>,
    ) {
        /** "상대가 OO이(가) 아니었나요?" 버튼: 영상이 확실히 냈거나 추정값으로 판정했을 때 (3.6) */
        val askable get() = (source == "video" || source == "guess") && label != null && options.isNotEmpty()

        /** 상대 종류 질문 (remaining에 없을 때 버튼에서 씀). 보기는 서버 값 그대로 */
        fun question(): Question = Question(
            field = FIELD, question = "상대는 무엇이었나요?", answerType = "choice",
            options = options, choices = choices,
            modelGuess = if (source == "guess") value else null,
            guessSource = if (source == "guess") "video" else null,
            guessEvidence = null, guessChoice = if (source == "guess") label else null,
            dependsOn = null,
        )

        companion object {
            const val FIELD = "parties.other.cls"
        }
    }

    companion object {
        const val ANALYZING = "analyzing"
        const val NEEDS_ANSWERS = "needs_answers"
        const val DONE = "done"
        const val NO_COLLISION = "no_collision"
        const val UNSUPPORTED = "unsupported"
        const val FAILED = "failed"

        fun parse(o: JSONObject): BbCase {
            val answers = o.optJSONObject("answers")
            val dq = o.optJSONObject("data_quality")
            val remaining = Question.list(o.optJSONArray("remaining"))
            val other = o.optJSONObject("other_cls")?.let(::otherCls)
            val sync = o.optJSONObject("sync")
            return BbCase(
                id = o.getString("id"),
                status = o.getString("status"),
                progress = o.optInt("progress", 0),
                createdAt = o.optLongOrNull("created_at"),
                analysis = o.optJSONObject("analysis")?.let {
                    Analysis(it.optString("status"), it.optStringOrNull("reason"), it.optStringOrNull("message"))
                },
                result = o.optJSONObject("result")?.let(::verdict),
                evidence = evidence(answers, other?.source),
                remaining = remaining,
                remainingCount = if (o.has("remaining_count") && !o.isNull("remaining_count")) o.optInt("remaining_count")
                else remaining.size,
                userAnswers = answersFrom(answers, "user"),
                values = answersFrom(answers, null),
                vehicleRecord = dq?.optBoolean("vehicle_record") ?: false,
                syncGrade = dq?.optStringOrNull("sync_grade") ?: o.optJSONObject("sync")?.optStringOrNull("grade"),
                otherCls = other,
                collisionT = o.optJSONObject("event")?.optDoubleOrNull("collision_t"),
                startMs = o.optJSONObject("sync")?.optLongOrNull("start_ms"),
                answered = Question.list(o.optJSONArray("answered")),
                resultWithVehicle = o.optJSONObject("result_with_vehicle")?.let(::verdict),
                vehicleEffects = VehicleEffect.list(o.optJSONArray("vehicle_effects")),
                timeline = VehicleTimeline.parse(o.optJSONObject("vehicle_timeline")),
                questions = Question.list(o.optJSONArray("questions")),
                // no_collision 등 판정하지 않은 사건은 data_quality가 없어 sync에만 있음
                clockWarnings = ClockWarning.list(dq?.optJSONArray("clock_warnings") ?: sync?.optJSONArray("clock_warnings")),
                syncReason = dq?.optStringOrNull("sync_reason") ?: sync?.optStringOrNull("reason"),
                syncReasonText = dq?.optStringOrNull("sync_reason_text") ?: sync?.optStringOrNull("reason_text"),
                review = CollisionReview.parse(o.optJSONObject("collision_review")),
            )
        }

        fun verdict(r: JSONObject): Verdict {
            val f = r.optJSONObject("fault_by_party")
            return Verdict(
                status = r.optString("status"),
                provisional = r.optBoolean("provisional"),
                ruleId = r.optStringOrNull("rule_id"),
                title = r.optStringOrNull("title"),
                egoFault = f?.optIntOrNull("ego"),
                otherFault = f?.optIntOrNull("other"),
                notice = r.optStringOrNull("notice"),
                chapter = r.optStringOrNull("chapter"),
                display = faultDisplay(r.optJSONObject("fault_display")),
            )
        }

        fun faultDisplay(d: JSONObject?): FaultDisplay? {
            if (d == null) return null
            val text = d.optStringOrNull("text") ?: return null
            return FaultDisplay(d.optString("kind"), text, d.optStringOrNull("note"))
        }

        private fun otherCls(o: JSONObject) = OtherCls(
            value = o.optStringOrNull("value"),
            label = o.optStringOrNull("label"),
            source = o.optStringOrNull("source"),
            chapter = o.optStringOrNull("chapter"),
            options = o.optJSONArray("options").values(),
            choices = o.optJSONArray("choices").values().map { it.toString() },
        )

        /**
         * 판정에 쓴 답(answers: {field: {value, source, evidence}}) → 근거 줄. 문장은 서버 evidence 그대로.
         * 출처 순서: 차량 정보 → 영상 → 내 답변 → 추정 → 가정. 문장이 없는 줄은 뺀다.
         */
        fun evidence(answers: JSONObject?, otherClsSource: String? = null): List<Evidence> {
            if (answers == null) return emptyList()
            val rows = answers.keys().asSequence().mapNotNull { field ->
                val a = answers.optJSONObject(field) ?: return@mapNotNull null
                val text = a.optStringOrNull("evidence") ?: return@mapNotNull null
                var source = a.optStringOrNull("source") ?: "default"
                // 영상·차량 기록 추정값으로 채운 값(basis == guess)은 "추정" 배지, 기본값만 "가정" 배지.
                // 상대 종류를 영상 추정값으로 판정했으면(other_cls.source == guess)도 "추정"
                if (source == "default" && a.optStringOrNull("basis") == GUESS) source = GUESS
                if (field == OtherCls.FIELD && otherClsSource == GUESS && source == "default") source = GUESS
                // 기본 판정에서 출처 vehicle은 내 차 종류(차량 정보)뿐 → 차량 기록과 다른 배지 (4.4)
                if (source == "vehicle") source = VEHICLE_INFO
                Evidence(field, source, text)
            }.toList()
            return rows.sortedBy { SOURCE_ORDER.indexOf(it.source).let { i -> if (i < 0) SOURCE_ORDER.size else i } }
        }

        /** answers 중 그 출처의 값 (source가 null이면 전부) */
        private fun answersFrom(answers: JSONObject?, source: String?): Map<String, Any?> {
            if (answers == null) return emptyMap()
            val out = LinkedHashMap<String, Any?>()
            for (k in answers.keys()) {
                val a = answers.optJSONObject(k) ?: continue
                if (source == null || a.optString("source") == source) out[k] = a.opt("value").unwrapList()
            }
            return out
        }

        const val GUESS = "guess"
        /** 올린 차량 기록을 시각이 안 맞아 쓰지 않은 이유 (design-blackbox 3.6 "시각 맞추기") */
        val VEHICLE_UNUSED_REASONS = setOf("vehicle_clock_mismatch", "vehicle_record_not_covering")
        const val VEHICLE_INFO = "vehicle_info"
        private val SOURCE_ORDER = listOf(VEHICLE_INFO, "vehicle", "video", "user", GUESS, "default")
    }
}

/**
 * 사고 순간 확인 (collision_review, design-blackbox 3.6). 사고 순간을 못 찾았거나(no_collision) 추정이거나 확신도가 낮으면 needed.
 * 영상이 서버에 남아 있는 동안(can_pick, 기한 pick_until) 사용자가 순간을 골라 PUT …/collision으로 다시 분석한다.
 */
data class CollisionReview(
    val needed: Boolean,
    /** no_collision / guess / low_confidence */
    val reason: String?,
    val message: String?,
    /** 분석기가 낸 사고 순간 (초, 없으면 null) */
    val t: Double?,
    val candidates: List<Candidate>,
    val canPick: Boolean,
    val pickUntil: Long?,
    /** 기한이 지나 영상을 지움 (다시 고를 수 없음) */
    val expired: Boolean,
    /** 고른 순간으로 다시 분석해 판정됨 (초) */
    val pickedT: Double?,
    /** 고른 순간으로도 판정하지 못함. 결과는 고르기 전 것 그대로 */
    val lastPick: LastPick?,
) {
    data class Candidate(val t: Double, val source: String?)
    data class LastPick(val t: Double?, val status: String?, val reason: String?, val message: String?)

    companion object {
        fun parse(o: JSONObject?): CollisionReview? {
            if (o == null) return null
            val cands = o.optJSONArray("candidates")
            return CollisionReview(
                needed = o.optBoolean("needed"),
                reason = o.optStringOrNull("reason"),
                message = o.optStringOrNull("message"),
                t = o.optDoubleOrNull("t"),
                candidates = if (cands == null) emptyList() else (0 until cands.length()).mapNotNull { i ->
                    val c = cands.optJSONObject(i) ?: return@mapNotNull null
                    c.optDoubleOrNull("t")?.let { Candidate(it, c.optStringOrNull("source")) }
                }.distinctBy { it.t },
                canPick = o.optBoolean("can_pick"),
                pickUntil = o.optLongOrNull("pick_until"),
                expired = o.optBoolean("expired"),
                pickedT = o.optJSONObject("picked")?.optDoubleOrNull("t"),
                lastPick = o.optJSONObject("last_pick")?.let {
                    LastPick(it.optDoubleOrNull("t"), it.optStringOrNull("status"), it.optStringOrNull("reason"),
                        it.optStringOrNull("message"))
                },
            )
        }
    }
}

/** 질문 하나 (remaining[] / questions[]). 보기 값(options)과 화면 이름(choices)은 순서대로 짝 */
data class Question(
    val field: String,
    val question: String,
    val answerType: String,
    val options: List<Any?>,
    val choices: List<String>,
    val modelGuess: Any?,
    /** video / vehicle / default / null */
    val guessSource: String?,
    val guessEvidence: String?,
    val guessChoice: String?,
    /** {질문 키: 값 또는 [값...]} 이 조건이 맞을 때만 묻는다 */
    val dependsOn: Map<String, List<Any?>>?,
    /** 이 질문에 대한 차량 기록 값 (참고, 판정에는 안 씀) */
    val vehicleHint: VehicleHint? = null,
    /** 선택 질문 (remaining에 없고 답하지 않아도 결과가 정해짐) */
    val optional: Boolean = false,
    /** 보기마다 묶음 이름 (특수 상황: "일반", "교차로" …). 없으면 null */
    val optionGroups: List<String>? = null,
) {
    val multi get() = answerType == MULTI

    /** 앱이 답할 수 있는 질문: 보기 하나 고르기(choice) 또는 여러 개 고르기(multi) */
    val answerable get() = (answerType == "choice" || multi) && options.isNotEmpty() && options.size == choices.size

    /** 여러 개 고르기의 "해당 없음 (모두 아니요)" 보기 번호 (없으면 -1) */
    val noneIndex: Int get() = if (multi) options.indexOf(NONE) else -1

    /** 추정값이 가리키는 보기 번호 (없으면 -1) */
    val guessIndex: Int get() = if (modelGuess == null) -1 else options.indexOfFirst { sameValue(it, modelGuess) }

    companion object {
        const val MULTI = "multi"
        /** 여러 개 고르기의 "해당 없음": 혼자 고를 때만 전부 "아니요" (backend-gaps-notes 5절) */
        const val NONE = "none"

        fun parse(o: JSONObject) = Question(
            field = o.getString("field"),
            question = o.optString("question"),
            answerType = o.optString("answer_type", "choice"),
            options = o.optJSONArray("options").values(),
            choices = o.optJSONArray("choices").values().map { it.toString() },
            modelGuess = o.opt("model_guess").unwrapList(),
            guessSource = o.optStringOrNull("guess_source"),
            guessEvidence = o.optStringOrNull("guess_evidence"),
            guessChoice = o.optStringOrNull("guess_choice"),
            dependsOn = o.optJSONObject("depends_on")?.let { d ->
                d.keys().asSequence().associateWith { k ->
                    when (val v = d.opt(k)) {
                        is JSONArray -> v.values()
                        else -> listOf(v.unwrap())
                    }
                }
            },
            vehicleHint = VehicleHint.parse(o.optJSONObject("vehicle_hint")),
            optional = o.optBoolean("optional", false),
            optionGroups = o.optJSONArray("option_groups")?.values()?.map { it.toString() },
        )

        fun list(a: JSONArray?): List<Question> =
            if (a == null) emptyList() else (0 until a.length()).mapNotNull { a.optJSONObject(it)?.let(::parse) }

        /** 보기 값 비교: JSON 숫자는 Int/Long/Double로 올 수 있어 숫자는 값으로 견준다 */
        fun sameValue(a: Any?, b: Any?): Boolean = when {
            a is Number && b is Number -> a.toDouble() == b.toDouble()
            else -> a == b
        }
    }
}

internal fun JSONObject.optStringOrNull(k: String): String? = if (isNull(k)) null else optString(k).ifEmpty { null }
internal fun JSONObject.optIntOrNull(k: String): Int? = if (isNull(k)) null else optInt(k)
internal fun JSONObject.optLongOrNull(k: String): Long? = if (isNull(k)) null else optLong(k)
internal fun JSONObject.optDoubleOrNull(k: String): Double? = if (isNull(k)) null else optDouble(k).takeIf { !it.isNaN() }
internal fun Any?.unwrap(): Any? = if (this == null || this == JSONObject.NULL) null else this
/** 답 값: 여러 개 고르기 답(JSON 배열)은 List로 */
internal fun Any?.unwrapList(): Any? = when (val v = unwrap()) {
    is JSONArray -> v.values()
    else -> v
}
internal fun JSONArray?.values(): List<Any?> = if (this == null) emptyList() else (0 until length()).map { opt(it).unwrap() }
