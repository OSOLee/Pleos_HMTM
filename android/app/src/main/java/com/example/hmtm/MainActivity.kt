package com.example.hmtm

import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import com.example.hmtm.data.record.RecordSettings
import com.example.hmtm.service.Collector
import com.example.hmtm.ui.HmtmApp
import com.example.hmtm.ui.theme.HmtmTheme

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { HmtmTheme { HmtmApp() } }

        // 첫 실행에는 안내 화면(HmtmApp)에서 동의 → 속도 권한 → 수집 서비스 시작.
        // 동의한 뒤에는 앱을 열 때 권한을 확인하고 시작하며, 차량 전원 ON 시 BootReceiver가 시작한다
        if (RecordSettings(this).consented) {
            if (checkSelfPermission(SPEED) == PackageManager.PERMISSION_GRANTED) startCollector()
            else askSpeed.launch(SPEED)
        }
    }

    // 거부해도 서비스는 시작한다 (속도 없이 Pleos 값만 기록)
    private val askSpeed = registerForActivityResult(ActivityResultContracts.RequestPermission()) { startCollector() }

    private fun startCollector() {
        Collector.startIfAllowed(this)
    }

    companion object {
        const val SPEED = "android.car.permission.CAR_SPEED"
    }
}
