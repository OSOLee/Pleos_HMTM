package com.example.hmtm.service

import android.content.Context
import android.content.Intent
import com.example.hmtm.data.record.RecordSettings

/** 수집 서비스 켜고 끄기. 기록 동의(첫 실행 안내) + 자동 기록이 켜져 있을 때만 시작한다 */
object Collector {
    fun startIfAllowed(context: Context): Boolean {
        if (!RecordSettings(context).shouldRecord) return false
        context.startForegroundService(Intent(context, VehicleCollectorService::class.java))
        return true
    }

    fun stop(context: Context) {
        context.stopService(Intent(context, VehicleCollectorService::class.java))
    }
}
