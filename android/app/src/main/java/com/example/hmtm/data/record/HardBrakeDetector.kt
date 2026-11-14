package com.example.hmtm.data.record

import com.example.hmtm.data.vehicle.VehicleSnapshot

/**
 * 급제동 감지기.
 * 최근 1초 동안의 감속도가 기준 이상이면 true를 반환한다.
 *
 * 기준값은 에뮬레이터·실차 테스트 결과를 보고 조정한다.
 * - minDecelKmhPerSec 15 ≈ 4.2 m/s² ≈ 0.42g (일반적인 급제동 수준)
 * - minStartSpeedKmh  20 : 저속 정지는 무시
 * - cooldownMs        30초 : 한 번의 급제동으로 이벤트가 여러 번 생기지 않도록
 */
class HardBrakeDetector(
    private val minDecelKmhPerSec: Float = 15f,
    private val minStartSpeedKmh: Float = 20f,
    private val cooldownMs: Long = 30_000,
) {
    private val history = ArrayDeque<Pair<Long, Float>>()
    private var lastTrigger = 0L

    fun check(s: VehicleSnapshot): Boolean {
        val v = s.speedKmh ?: return false
        history.addLast(s.timestamp to v)
        while (history.isNotEmpty() && history.first().first < s.timestamp - 1_000) {
            history.removeFirst()
        }
        if (s.timestamp - lastTrigger < cooldownMs) return false

        val (t0, v0) = history.first()
        val dt = (s.timestamp - t0) / 1000f
        if (dt < 0.5f || v0 < minStartSpeedKmh) return false

        val decel = (v0 - v) / dt
        if (decel >= minDecelKmhPerSec) {
            lastTrigger = s.timestamp
            return true
        }
        return false
    }
}
