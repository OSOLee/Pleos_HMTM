package com.example.hmtm.data.vehicle

import android.content.Context

/**
 * 서비스와 화면이 같은 데이터를 보도록 하는 공용 보관소.
 * - 서비스: start()로 수집 시작, buffer에 주기적으로 저장
 * - 화면: latest / buffer를 읽고, uiListener로 실시간 값을 받음
 */
object VehicleHub {

    @Volatile
    var latest = VehicleSnapshot()
        private set

    /** 최근 60초 */
    val buffer = VehicleBuffer(windowMs = 60_000)

    var uiListener: VehicleRepository.Listener? = null

    private var repo: VehicleRepository? = null

    val isRunning: Boolean get() = repo != null

    fun start(context: Context) {
        if (repo != null) return
        repo = VehicleRepository(context.applicationContext).also {
            it.listener = VehicleRepository.Listener { s ->
                latest = s
                uiListener?.onUpdate(s)
            }
            it.start()
        }
    }

    fun stop() {
        repo?.stop()
        repo = null
    }
}
