package com.example.hmtm.ui

import com.example.hmtm.data.record.Bookmark
import com.example.hmtm.ui.home.bookmarkText
import org.junit.Assert.assertEquals
import org.junit.Test

class UiLogicTest {
    @Test fun overallProgress() {
        assertEquals(0f, AnalyzingState().overall, 0f)
        assertEquals(0.2f, AnalyzingState(step = 0, uploadProgress = 0.5f).overall, 1e-6f)
        assertEquals(0.65f, AnalyzingState(step = 1, analysisProgress = 50).overall, 1e-6f)
        assertEquals(1f, AnalyzingState(step = 4).overall, 0f)
    }

    @Test fun bookmarkLine() {
        assertEquals("급제동 · 62 → 8 km/h", bookmarkText(Bookmark(0, "hard_brake", 62.4f, 8.2f)))
        assertEquals("급제동", bookmarkText(Bookmark(0, "hard_brake", null, 8f)))
    }

    @Test fun drivingBySpeedAndGear() {
        // 속도를 알면 3km/h 기준
        assertEquals(false, DrivingState.isDriving(0f, 8))
        assertEquals(false, DrivingState.isDriving(2.9f, 8))
        assertEquals(true, DrivingState.isDriving(3f, 8))
        assertEquals(true, DrivingState.isDriving(40f, null))
        // P면 속도와 관계없이 정차
        assertEquals(false, DrivingState.isDriving(10f, 4))
        assertEquals(false, DrivingState.isDriving(null, 4))
        // 속도를 모르면 기어로: R·D·수동 단수는 주행, N·모름은 정차
        assertEquals(true, DrivingState.isDriving(null, 8))
        assertEquals(true, DrivingState.isDriving(null, 2))
        assertEquals(true, DrivingState.isDriving(null, 16))
        assertEquals(false, DrivingState.isDriving(null, 1))
        assertEquals(false, DrivingState.isDriving(null, null))
        assertEquals(false, DrivingState.isDriving(Float.NaN, null))
    }
}
