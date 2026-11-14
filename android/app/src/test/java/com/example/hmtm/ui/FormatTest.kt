package com.example.hmtm.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.TimeZone

class FormatTest {
    private val kst = TimeZone.getTimeZone("Asia/Seoul")
    private val now = 1_794_202_212_000L          // 2026-11-09 14:30:12 KST

    @Test fun dayTime() {
        assertEquals("오늘 14:30", Format.dayTime(now, now, kst))
        assertEquals("어제 14:30", Format.dayTime(now - 86_400_000L, now, kst))
        assertEquals("11월 7일 14:30", Format.dayTime(now - 2 * 86_400_000L, now, kst))
        assertEquals("오늘 00:00", Format.dayTime(1_794_150_000_000L, now, kst))  // 같은 날 자정
    }

    @Test fun clockAndDuration() {
        assertEquals("14:30:12", Format.clock(now, kst))
        assertEquals("1분 00초", Format.duration(60_000))
        assertEquals("45초", Format.duration(45_200))
        assertEquals("2분 05초", Format.duration(125_000))
    }

    @Test fun driving() {
        assertFalse(DrivingState.isDriving(null))
        assertFalse(DrivingState.isDriving(0f))
        assertTrue(DrivingState.isDriving(20f))
    }

    @Test fun josa() {
        assertEquals("상대가 승용차가 아니었나요?", Format.notOtherCls("승용차"))
        assertEquals("상대가 보행자가 아니었나요?", Format.notOtherCls("보행자"))
        assertEquals("상대가 농기계가 아니었나요?", Format.notOtherCls("농기계"))
        assertEquals("이", Format.iGa("버스 전용 차선"))
        assertEquals("이(가)", Format.iGa("SUV"))
    }
}
