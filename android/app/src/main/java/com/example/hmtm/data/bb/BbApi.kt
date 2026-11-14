package com.example.hmtm.data.bb

import com.example.hmtm.data.net.ApiClient
import com.example.hmtm.data.net.ApiException
import com.example.hmtm.data.net.ProgressRequestBody
import com.example.hmtm.data.video.PickedVideo
import com.example.hmtm.data.video.StartCandidate
import com.example.hmtm.data.video.StartTime
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import org.json.JSONArray
import org.json.JSONObject
import kotlinx.coroutines.delay
import java.io.InputStream

/** 블랙박스 사건 API (docs/design-blackbox.md 3.6) */
class BbApi(private val client: ApiClient) {

    /**
     * POST /api/bb-cases (multipart): video + meta + vehicle(선택) + scenario(가짜 분석기, 개발용).
     * 202 analyzing 사건을 돌려준다. 업로드 진행률은 onProgress(0~1).
     */
    suspend fun create(
        video: PickedVideo,
        open: () -> InputStream,
        vehicle: JSONObject?,
        scenario: String?,
        onProgress: (Float) -> Unit,
    ): BbCase = createRaw(video.name, video.mimeType, video.sizeBytes, open, meta(video), vehicle, scenario, onProgress)

    suspend fun createRaw(
        name: String,
        mimeType: String,
        sizeBytes: Long,
        open: () -> InputStream,
        meta: JSONObject,
        vehicle: JSONObject?,
        scenario: String?,
        onProgress: (Float) -> Unit,
    ): BbCase {
        val metaText = meta.toString()
        val res = client.call("POST", "/api/bb-cases") {
            MultipartBody.Builder().setType(MultipartBody.FORM)
                .addFormDataPart(
                    "video", name,
                    ProgressRequestBody(mimeType.toMediaTypeOrNull(), sizeBytes, open) { sent, total ->
                        if (total > 0) onProgress((sent.toFloat() / total).coerceIn(0f, 1f))
                    },
                )
                .addFormDataPart("meta", metaText)
                .apply {
                    if (vehicle != null) addFormDataPart("vehicle", vehicle.toString())
                    if (!scenario.isNullOrBlank()) addFormDataPart("scenario", scenario)
                }
                .build()
        }
        return BbCase.parse(res)
    }

    /** GET /api/bb-cases/{id}: 분석 중이면 progress, 끝났으면 결과 */
    suspend fun get(id: String): BbCase = BbCase.parse(client.getJson("/api/bb-cases/$id"))

    /**
     * 분석이 끝날 때까지 GET을 되풀이한다. 매번 onUpdate로 알린다. 연결이 잠깐 끊기면(network) 계속 기다린다.
     * timeoutMs가 지나도 analyzing이면 ApiException(analysis_timeout).
     */
    suspend fun await(
        id: String,
        onUpdate: (BbCase) -> Unit = {},
        intervalMs: Long = POLL_MS,
        timeoutMs: Long = POLL_TIMEOUT_MS,
    ): BbCase {
        val end = System.currentTimeMillis() + timeoutMs
        var networkFails = 0
        while (true) {
            val c = try {
                get(id).also { networkFails = 0 }
            } catch (e: ApiException) {
                if (e.code != ApiException.NETWORK || ++networkFails > MAX_NETWORK_FAILS) throw e
                null
            }
            if (c != null) {
                onUpdate(c)
                if (!c.analyzing) return c
            }
            if (System.currentTimeMillis() > end) {
                throw ApiException(0, "analysis_timeout", "분석이 너무 오래 걸려요. 잠시 후 다시 확인해 주세요")
            }
            delay(intervalMs)
        }
    }

    /**
     * PUT /api/bb-cases/{id}/answers: 지금까지의 답 전부 → 새로 판정한 사건.
     * 409 bb_case_analyzing(분석 중)이면 onBusy로 알리고 busyWaitMs 뒤 다시 보낸다 (최대 busyTries번).
     */
    suspend fun putAnswers(
        id: String,
        answers: Map<String, Any?>,
        onBusy: (ApiException) -> Unit = {},
        busyWaitMs: Long = BUSY_WAIT_MS,
        busyTries: Int = BUSY_TRIES,
    ): BbCase {
        val body = JSONObject().put("answers", answersJson(answers))
        var tries = 0
        while (true) {
            try {
                return BbCase.parse(client.putJson("/api/bb-cases/$id/answers", body))
            } catch (e: ApiException) {
                if (e.status != 409 || e.code != BUSY || ++tries >= busyTries) throw e
                onBusy(e)
                delay(busyWaitMs)
            }
        }
    }

    /**
     * PUT /api/bb-cases/{id}/collision {"t": 초}: 고른 사고 순간으로 다시 분석 → 202 분석 중 객체 (그 뒤 await로 폴링).
     * 오류는 ApiException: 409 collision_not_needed·bb_case_analyzing, 410 video_gone, 422 collision_invalid·request_invalid,
     * 503 analyzer_not_ready
     */
    suspend fun putCollision(id: String, t: Double): BbCase =
        BbCase.parse(client.putJson("/api/bb-cases/$id/collision", JSONObject().put("t", Math.round(t * 1000) / 1000.0)))

    /** DELETE /api/bb-cases/{id} (204). 이미 없으면(404) 지워진 것으로 본다 */
    suspend fun delete(id: String) {
        try {
            client.delete("/api/bb-cases/$id")
        } catch (e: ApiException) {
            if (e.status != 404) throw e
        }
    }

    /** DELETE /api/bb-cases: 내 사건 전부 (분석 중인 것도). 지운 개수 */
    suspend fun deleteAll(): Int = client.call("DELETE", "/api/bb-cases").optInt("deleted", 0)

    /** GET /api/bb-cases?before=&limit=: 내 사건 목록 (최근 것부터) */
    suspend fun list(before: Long? = null, limit: Int = PAGE): List<BbSummary> {
        val q = buildString {
            append("?limit=").append(limit)
            if (before != null) append("&before=").append(before)
        }
        val a = client.getArray("/api/bb-cases$q")
        return (0 until a.length()).mapNotNull { a.optJSONObject(it)?.let(BbSummary::parse) }
    }

    companion object {
        const val PAGE = 20
        const val BUSY = "bb_case_analyzing"
        const val BUSY_WAIT_MS = 3_000L
        const val BUSY_TRIES = 5

        fun answersJson(answers: Map<String, Any?>): JSONObject = JSONObject().apply {
            answers.forEach { (k, v) ->
                put(k, when (v) {
                    null -> JSONObject.NULL
                    is List<*> -> JSONArray(v)
                    else -> v
                })
            }
        }

        const val POLL_MS = 1_000L
        const val POLL_TIMEOUT_MS = 10 * 60_000L
        private const val MAX_NETWORK_FAILS = 5

        /**
         * meta: 파일 이름, 촬영 시작 시각 후보(recorded_at), 길이, 수정 시각, 시간대 (bb-flow-notes 4절).
         * 수정 시각은 recorded_at에 넣지 않고 mtime_ms로 따로 보낸다. recorded_at에 넣으면 서버가 출처를 "app"으로 보아
         * 믿을 만한 시각(coarse)으로 쓰기 때문 (서버는 mtime만 있으면 none으로 둠).
         */
        fun meta(v: PickedVideo): JSONObject =
            meta(v.name, v.sizeBytes, v.durationMs, v.candidates, v.mtimeMs, v.tzOffsetMin)

        fun meta(
            name: String,
            sizeBytes: Long,
            durationMs: Long?,
            candidates: List<StartCandidate>,
            mtimeMs: Long?,
            tzOffsetMin: Int,
        ): JSONObject = JSONObject()
            .put("filename", name)
            .put("recorded_at", JSONArray().apply {
                candidates.filter { it.source != StartTime.MTIME }.forEach {
                    put(JSONObject().put("source", it.source).put("start_ms", it.startMs))
                }
            })
            .put("duration_s", durationMs?.let { it / 1000.0 } ?: JSONObject.NULL)
            .put("mtime_ms", mtimeMs ?: JSONObject.NULL)
            .put("tz_offset_min", tzOffsetMin)
            .put("size_bytes", sizeBytes)
    }
}
