package com.example.hmtm.data.bb

import org.json.JSONObject
import java.io.File

/**
 * 사건마다 기기에만 두는 것: 원본 영상 주소 (영상 다시 보기·사고 순간 고르기. 서버는 판정 뒤 영상을 지움).
 * 답한 질문 정의(선택 질문 포함)·차량 기록 여부는 서버 응답에 있다 (design-blackbox 3.6, analyzer-integration-notes 10절).
 * 전에 쓴 파일의 vehicle_record·questions·optional_questions 칸은 읽지 않는다 (다음에 쓸 때 빠짐).
 */
data class CaseLocal(
    val videoUri: String? = null,
    val mimeType: String? = null,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("video_uri", videoUri ?: JSONObject.NULL)
        .put("mime_type", mimeType ?: JSONObject.NULL)

    companion object {
        fun parse(o: JSONObject) = CaseLocal(
            videoUri = o.optStringOrNull("video_uri"),
            mimeType = o.optStringOrNull("mime_type"),
        )
    }
}

/**
 * files/cases/<사건 id>.json. 서버 사건을 지우면 같이 지운다.
 * 파일 쓰기라 IO 스레드에서 부른다.
 */
class CaseStore(private val dir: File) {

    @Synchronized
    fun get(id: String): CaseLocal? {
        val f = file(id) ?: return null
        if (!f.exists()) return null
        return runCatching { CaseLocal.parse(JSONObject(f.readText(Charsets.UTF_8))) }.getOrNull()
    }

    @Synchronized
    fun update(id: String, change: (CaseLocal) -> CaseLocal): CaseLocal {
        val f = file(id) ?: return change(CaseLocal())
        val next = change(get(id) ?: CaseLocal())
        dir.mkdirs()
        val tmp = File(dir, "${f.name}.tmp")
        tmp.writeText(next.toJson().toString(), Charsets.UTF_8)
        if (!tmp.renameTo(f)) {
            f.delete()
            tmp.renameTo(f)
        }
        return next
    }

    @Synchronized
    fun delete(id: String) {
        file(id)?.delete()
    }

    @Synchronized
    fun clear() {
        dir.listFiles()?.forEach { it.delete() }
    }

    /** 서버 id는 16진 글자. 그 밖이면 파일로 쓰지 않음 */
    private fun file(id: String): File? =
        if (id.isNotEmpty() && id.all { it.isLetterOrDigit() || it == '-' || it == '_' }) File(dir, "$id.json") else null
}
