package com.example.hmtm.data.vehicle

import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * 최근 windowMs 동안의 차량 상태를 메모리에 유지하는 순환 버퍼.
 * 급제동 등 이벤트가 발생하면 exportJson()으로 그 구간을 별도 파일로 보존한다.
 */
class VehicleBuffer(private val windowMs: Long) {

    private val items = ArrayDeque<VehicleSnapshot>()

    @Synchronized
    fun add(s: VehicleSnapshot) {
        items.addLast(s)
        val cutoff = s.timestamp - windowMs
        while (items.isNotEmpty() && items.first().timestamp < cutoff) items.removeFirst()
    }

    @Synchronized
    fun size(): Int = items.size

    /** 모든 기록 삭제 */
    @Synchronized
    fun clear() = items.clear()

    @Synchronized
    fun copy(): List<VehicleSnapshot> = items.toList()

    /** 현재 버퍼 내용을 JSON 파일로 저장하고 파일을 반환 */
    fun exportJson(dir: File, reason: String, triggerAt: Long? = null): File {
        val now = System.currentTimeMillis()
        val samples = JSONArray()
        copy().forEach { s ->
            samples.put(
                JSONObject()
                    .put("t", s.timestamp)
                    .put("speedKmh", s.speedKmh ?: JSONObject.NULL)
                    .put("gear", s.gear ?: JSONObject.NULL)
                    .put("turnSignal", s.turnSignal ?: JSONObject.NULL)
                    .put("brake", s.brakePedal?.toBooleanStrictOrNull() ?: JSONObject.NULL)
            )
        }
        val root = JSONObject()
            .put("reason", reason)
            .put("triggerAt", triggerAt ?: JSONObject.NULL)
            .put("savedAt", now)
            .put("windowMs", windowMs)
            .put("samples", samples)

        dir.mkdirs()
        val file = File(dir, "event_${triggerAt ?: now}.json")
        file.writeText(root.toString(2))
        return file
    }
}
