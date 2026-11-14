package com.example.hmtm.data.vehicle

import ai.pleos.playground.vehicle.Vehicle
import android.car.Car
import android.car.VehiclePropertyIds
import android.car.hardware.CarPropertyValue
import android.car.hardware.property.CarPropertyManager
import android.content.Context
import android.os.Handler
import android.os.Looper

/** 차량 상태 한 시점의 스냅샷 */
data class VehicleSnapshot(
    val timestamp: Long = System.currentTimeMillis(),
    val speedKmh: Float? = null,     // CarPropertyManager
    val gear: Int? = null,           // CarPropertyManager (VehicleGear 상수)
    val turnSignal: String? = null,  // Pleos TurnSignal
    val brakePedal: String? = null,  // Pleos Brake
    val error: String? = null,
)

/**
 * 차량 데이터 수집기
 * - 방향지시등, 브레이크: Pleos Vehicle SDK
 * - 속도, 기어: Android Automotive 표준 CarPropertyManager
 * 값이 바뀔 때마다 listener로 메인 스레드에 전달한다.
 */
class VehicleRepository(private val context: Context) {

    fun interface Listener {
        fun onUpdate(snapshot: VehicleSnapshot)
    }

    var listener: Listener? = null

    private val mainHandler = Handler(Looper.getMainLooper())
    private var snapshot = VehicleSnapshot()
    private var vehicle: Vehicle? = null
    private var car: Car? = null
    private var running = false

    private fun update(block: (VehicleSnapshot) -> VehicleSnapshot) {
        val next = synchronized(this) {
            snapshot = block(snapshot).copy(timestamp = System.currentTimeMillis())
            snapshot
        }
        mainHandler.post { listener?.onUpdate(next) }
    }

    fun start() {
        if (running) return
        running = true
        startPleos()
        startCarProperty()
    }

    // ---------- Pleos Vehicle SDK ----------
    // 1차 확인용으로 200ms마다 현재 값을 조회한다.
    // 값이 정상적으로 읽히는 것을 확인한 뒤 registerXxx 콜백 방식으로 교체 예정.
    private val pollTask = object : Runnable {
        override fun run() {
            val v = vehicle ?: return

            v.getTurnSignal().getCurrentTurnSignalState(
                onComplete = { s -> update { it.copy(turnSignal = s.toString()) } },
                onFailed = { e -> update { it.copy(error = "TurnSignal: ${e.message}") } },
            )
            v.getBrake().getCurrentBrakePedalStatus(
                onComplete = { s -> update { it.copy(brakePedal = s.toString()) } },
                onFailed = { e -> update { it.copy(error = "Brake: ${e.message}") } },
            )

            if (running) mainHandler.postDelayed(this, 200)
        }
    }

    private fun startPleos() {
        try {
            vehicle = Vehicle(context).also { it.initialize() }
            mainHandler.post(pollTask)
        } catch (e: Exception) {
            update { it.copy(error = "Pleos 초기화 실패: ${e.message}") }
        }
    }

    // ---------- CarPropertyManager (속도, 기어) ----------
    private val propertyCallback = object : CarPropertyManager.CarPropertyEventCallback {
        override fun onChangeEvent(value: CarPropertyValue<*>) {
            when (value.propertyId) {
                VehiclePropertyIds.PERF_VEHICLE_SPEED -> {
                    val ms = value.value as? Float ?: return
                    update { it.copy(speedKmh = ms * 3.6f) } // m/s → km/h
                }
                VehiclePropertyIds.GEAR_SELECTION -> {
                    update { it.copy(gear = value.value as? Int) }
                }
            }
        }

        override fun onErrorEvent(propertyId: Int, areaId: Int) {
            update { it.copy(error = "CarProperty 오류: $propertyId") }
        }
    }

    private fun startCarProperty() {
        try {
            val c = Car.createCar(context) ?: return
            car = c
            val mgr = c.getCarManager(Car.PROPERTY_SERVICE) as CarPropertyManager
            mgr.registerCallback(
                propertyCallback,
                VehiclePropertyIds.PERF_VEHICLE_SPEED,
                CarPropertyManager.SENSOR_RATE_NORMAL,
            )
            mgr.registerCallback(
                propertyCallback,
                VehiclePropertyIds.GEAR_SELECTION,
                CarPropertyManager.SENSOR_RATE_ONCHANGE,
            )
        } catch (e: SecurityException) {
            update { it.copy(error = "속도/기어 권한 없음: ${e.message}") }
        }
    }

    fun stop() {
        running = false
        mainHandler.removeCallbacks(pollTask)
        (car?.getCarManager(Car.PROPERTY_SERVICE) as? CarPropertyManager)
            ?.unregisterCallback(propertyCallback)
        car?.disconnect()
        vehicle?.release()
        car = null
        vehicle = null
    }
}
