package com.example.hmtm.service

import android.app.Notification
import com.example.hmtm.R
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.util.Log
import com.example.hmtm.data.record.HardBrakeDetector
import com.example.hmtm.data.record.LoopRecorder
import com.example.hmtm.data.vehicle.VehicleHub
import java.io.File

/**
 * 차량 전원이 켜져 있는 동안 백그라운드에서 계속 동작하는 수집 서비스.
 *
 * 100ms마다:
 *  1) 메모리 버퍼(최근 60초)에 추가
 *  2) 루프 파일(1분 단위 CSV, 72시간 보관)에 기록
 *  3) 급제동 감지 → 감지 15초 후 버퍼 전체(앞 45초 + 뒤 15초)를 이벤트 파일로 보존
 */
class VehicleCollectorService : Service() {

    // 파일 쓰기를 화면 스레드와 분리
    private val thread = HandlerThread("vehicle-collector").apply { start() }
    private val handler = Handler(thread.looper)

    private lateinit var loop: LoopRecorder
    private val detector = HardBrakeDetector()
    private var lastCleanup = 0L

    private val sampler = object : Runnable {
        override fun run() {
            val now = System.currentTimeMillis()
            val s = VehicleHub.latest.copy(timestamp = now)

            VehicleHub.buffer.add(s)

            try {
                loop.write(s)
            } catch (e: Exception) {
                Log.e(TAG, "루프 기록 실패", e)
            }

            if (detector.check(s)) {
                Log.i(TAG, "급제동 감지: ${s.speedKmh} km/h")
                handler.postDelayed({ saveEvent("hard_brake", now) }, POST_EVENT_MS)
            }

            if (now - lastCleanup > CLEANUP_INTERVAL_MS) {
                val n = loop.cleanup(now)
                if (n > 0) Log.i(TAG, "오래된 루프 파일 $n 개 삭제")
                lastCleanup = now
            }

            handler.postDelayed(this, SAMPLE_MS)
        }
    }

    override fun onCreate() {
        super.onCreate()
        startAsForeground()
        loop = LoopRecorder(File(filesDir, "loop"), RETENTION_MS)
        VehicleHub.start(this)
        handler.post(sampler)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        handler.post { loop.close() }
        thread.quitSafely()
        VehicleHub.stop()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun saveEvent(reason: String, triggerAt: Long) {
        try {
            val file = VehicleHub.buffer.exportJson(File(filesDir, "events"), reason, triggerAt)
            Log.i(TAG, "이벤트 저장: ${file.name}")
        } catch (e: Exception) {
            Log.e(TAG, "이벤트 저장 실패", e)
        }
    }

    private fun startAsForeground() {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, getString(R.string.notification_channel), NotificationManager.IMPORTANCE_LOW)
        )
        val notification = Notification.Builder(this, CHANNEL_ID)
            // 알림은 한 줄, 간결하게 (pleos-design-rules 6절)
            .setContentTitle(getString(R.string.notification_recording))
            .setSmallIcon(android.R.drawable.ic_menu_recent_history)
            .setOngoing(true)
            .build()

        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTI_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(NOTI_ID, notification)
        }
    }

    companion object {
        private const val TAG = "HMTM"
        private const val CHANNEL_ID = "vehicle_collector"
        private const val NOTI_ID = 1

        private const val SAMPLE_MS = 100L
        private const val POST_EVENT_MS = 15_000L                 // 이벤트 후 15초 더 기록
        private const val RETENTION_MS = 72L * 60 * 60 * 1000     // 72시간
        private const val CLEANUP_INTERVAL_MS = 60L * 60 * 1000   // 1시간마다 정리
    }
}
