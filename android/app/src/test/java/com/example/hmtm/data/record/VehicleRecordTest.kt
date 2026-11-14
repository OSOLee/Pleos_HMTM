package com.example.hmtm.data.record

import com.example.hmtm.data.vehicle.VehicleSnapshot
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import java.nio.file.Files

class VehicleRecordTest {
    private lateinit var dir: File

    @Before fun setUp() {
        dir = Files.createTempDirectory("loop").toFile()
    }

    @After fun tearDown() {
        dir.deleteRecursively()
    }

    @Test fun conversionTable() {
        // 기어 (api-spec 6.2)
        assertEquals("P", VehicleRecord.gear("4"))
        assertEquals("R", VehicleRecord.gear("2"))
        assertEquals("N", VehicleRecord.gear("1"))
        assertEquals("D", VehicleRecord.gear("8"))
        assertEquals("D", VehicleRecord.gear("32"))     // 수동 단수
        assertNull(VehicleRecord.gear("0"))
        assertNull(VehicleRecord.gear(""))
        assertNull(VehicleRecord.gear("3"))
        // 브레이크: 문자열 → bool
        assertEquals(true, VehicleRecord.brake("true"))
        assertEquals(false, VehicleRecord.brake("false"))
        assertNull(VehicleRecord.brake(""))
        assertNull(VehicleRecord.brake("PRESSED"))
        // 지시등
        assertEquals("LEFT", VehicleRecord.turnSignal("LEFT"))
        assertEquals("RIGHT", VehicleRecord.turnSignal("TurnSignalState.RIGHT"))
        assertEquals("OFF", VehicleRecord.turnSignal("off"))
        assertNull(VehicleRecord.turnSignal(""))
        assertNull(VehicleRecord.turnSignal("HAZARD"))
        // 속도
        assertEquals(42.5, VehicleRecord.speed("42.50")!!, 1e-9)
        assertNull(VehicleRecord.speed(""))
        assertNull(VehicleRecord.speed("-1.00"))
        assertNull(VehicleRecord.speed("NaN"))
    }

    @Test fun parseLineMatchesLoopRecorder() {
        val line = LoopRecorder.toCsv(VehicleSnapshot(1000L, 42.5f, 8, "RIGHT", "true"))
        assertEquals(Sample(1000L, 42.5, "D", "RIGHT", true), VehicleRecord.parseLine(line))
        val empty = LoopRecorder.toCsv(VehicleSnapshot(2000L))
        assertEquals(Sample(2000L, null, null, null, null), VehicleRecord.parseLine(empty))
        assertNull(VehicleRecord.parseLine(LoopRecorder.HEADER))
        assertNull(VehicleRecord.parseLine("1794202212"))        // 반만 쓴 줄
        assertNull(VehicleRecord.parseLine("abc,1,8,OFF,false"))
    }

    @Test fun window() {
        val s0 = 1_000_000L
        assertEquals((s0 - 15_000)..(s0 + 60_000 + 15_000), VehicleRecord.window(s0, 60_000, "filename"))
        assertEquals((s0 - 60_000)..(s0 + 60_000 + 60_000), VehicleRecord.window(s0, 60_000, "mtime"))
        // 10분 상시 녹화 영상: 앞 여유 15초는 지키고 끝을 300초로 줄임
        assertEquals((s0 - 15_000)..(s0 - 15_000 + 300_000), VehicleRecord.window(s0, 600_000, "filename"))
        assertEquals((s0 - 15_000)..(s0 + 15_000), VehicleRecord.window(s0, null, "filename"))
    }

    /** 분 경계를 넘는 구간: 두 파일을 이어 붙이고 구간 밖 줄은 버림 */
    @Test fun sliceAcrossMinutes() {
        val rec = LoopRecorder(dir, Long.MAX_VALUE)
        val m0 = 1_794_202_200_000L                    // 분 시작
        for (t in m0 until m0 + 120_000 step 100) {
            rec.write(VehicleSnapshot(t, (t - m0) / 1000f, if (t < m0 + 60_000) 8 else 2, "OFF", "false"))
        }
        rec.close()
        assertEquals(2, rec.segmentCount())

        val range = (m0 + 50_000)..(m0 + 70_000)
        val att = VehicleRecord.attach(dir, range)!!
        assertEquals(range.first, att.from)
        assertEquals(range.last, att.to)
        assertEquals(201, att.samples.size)            // 50.0초 ~ 70.0초, 0.1초 간격
        assertTrue(att.samples.all { it.t in range })
        assertEquals(att.samples.sortedBy { it.t }, att.samples)
        assertEquals("D", att.samples.first().gear)
        assertEquals("R", att.samples.last().gear)

        // 서버 모양 (camelCase samples, 빈 값은 null)
        val j = att.toJson("0.1.0")
        assertEquals(range.first, j.getJSONObject("range").getLong("from"))
        val s = j.getJSONArray("samples").getJSONObject(0)
        assertEquals(setOf("t", "speedKmh", "gear", "turnSignal", "brake"), s.keySet())
        assertFalse(s.getBoolean("brake"))
        assertTrue(j.isNull("location"))
        assertEquals("car", j.getJSONObject("vehicle").getString("cls"))
    }

    @Test fun nullValuesBecomeJsonNull() {
        val j = VehicleAttachment(0, 10, listOf(Sample(5, null, null, null, null))).toJson("0.1.0")
        val s: JSONObject = j.getJSONArray("samples").getJSONObject(0)
        for (k in listOf("speedKmh", "gear", "turnSignal", "brake")) assertTrue(k, s.isNull(k))
    }

    @Test fun noRecordInRange() {
        val rec = LoopRecorder(dir, Long.MAX_VALUE)
        rec.write(VehicleSnapshot(1_000_000L, 10f))
        rec.close()
        assertNull(VehicleRecord.attach(dir, 5_000_000L..5_100_000L))
        assertNull(VehicleRecord.attach(File(dir, "없는 폴더"), 0L..1L))
    }
}
