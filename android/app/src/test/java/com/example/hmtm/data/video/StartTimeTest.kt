package com.example.hmtm.data.video

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.TimeZone

class StartTimeTest {
    private val kst = TimeZone.getTimeZone("Asia/Seoul")
    private val s0 = 1_794_202_212_000L          // 2026-11-09 14:30:12 KST = 05:30:12 UTC

    @Test fun filenameForms() {
        for (n in listOf(
            "20261109_143012_F.mp4", "EVT_20261109-143012.avi", "REC 2026-11-09 14:30:12.mp4",
            "/Normal/Front/20261109T143012.mp4", "2026.11.09_14.30.12_R.MP4",
        )) assertEquals(n, s0, StartTime.fromFilename(n, kst))
    }

    @Test fun filenameRejects() {
        assertNull(StartTime.fromFilename("video.mp4", kst))
        assertNull(StartTime.fromFilename("20261399_143012.mp4", kst))     // 13월
        assertNull(StartTime.fromFilename("120261109_143012.mp4", kst))    // 앞에 숫자가 붙음 (서버와 같게)
        assertNull(StartTime.fromFilename(null, kst))
    }

    @Test fun metadata() {
        assertEquals(s0, StartTime.fromMetadata("20261109T053012.000Z"))
        assertEquals(s0, StartTime.fromMetadata("20261109T053012Z"))
        assertNull(StartTime.fromMetadata("19040101T000000.000Z"))          // mp4 기본값
        assertNull(StartTime.fromMetadata(""))
        assertNull(StartTime.fromMetadata(null))
    }

    @Test fun candidateOrder() {
        val c = StartTime.candidates("20261109_143012_F.mp4", "20261109T053010.000Z", s0 + 62_000, 60_000, kst)
        assertEquals(listOf("filename", "metadata", "mtime"), c.map { it.source })
        assertEquals(listOf(s0, s0 - 2_000, s0 + 2_000), c.map { it.startMs })
        val onlyMtime = StartTime.candidates("clip.mp4", null, s0 + 60_000, 60_000, kst)
        assertEquals(listOf(StartCandidate("mtime", s0)), onlyMtime)
        assertTrue(StartTime.candidates("clip.mp4", null, s0, null, kst).isEmpty())   // 길이를 모르면 수정 시각은 못 씀
    }

    @Test fun suspiciousAndTz() {
        assertFalse(StartTime.suspicious(s0, s0 + 3_600_000))
        assertTrue(StartTime.suspicious(s0 + 3_600_000, s0))                  // 미래
        assertTrue(StartTime.suspicious(s0 - 73 * 3_600_000L, s0))            // 72시간 넘음
        assertFalse(StartTime.suspicious(null, s0))
        assertEquals(540, StartTime.tzOffsetMin(s0, kst))
    }
}
