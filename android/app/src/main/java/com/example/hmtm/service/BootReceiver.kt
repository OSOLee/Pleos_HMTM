package com.example.hmtm.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * 차량 전원 ON(부팅 완료) 또는 앱 업데이트 직후 수집 서비스를 자동으로 시작한다.
 * 단, 설치 후 사용자가 앱을 한 번은 직접 열어야 이 신호를 받을 수 있다(Android 정책).
 * 기록 동의(첫 실행 안내)와 자동 기록 설정이 켜져 있을 때만 시작한다.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            Intent.ACTION_BOOT_COMPLETED,
            Intent.ACTION_MY_PACKAGE_REPLACED -> {
                // 기록 동의 전이거나 설정에서 자동 기록을 껐으면 시작하지 않음
                Collector.startIfAllowed(context)
            }
        }
    }
}
