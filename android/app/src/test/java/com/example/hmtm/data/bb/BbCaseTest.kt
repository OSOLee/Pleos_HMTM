package com.example.hmtm.data.bb

import com.example.hmtm.data.video.StartCandidate
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 실제 서버 응답으로 읽기 확인. 응답 파일(test/resources/bb 폴더의 json)은 backend의 가짜 분석기로
 * POST·GET /api/bb-cases를 돌려 저장한 것 (2026-11-09).
 */
class BbCaseTest {
    private fun load(name: String) =
        JSONObject(javaClass.getResource("/bb/$name.json")!!.readText(Charsets.UTF_8))

    @Test fun analyzing() {
        val c = BbCase.parse(load("analyzing"))
        assertTrue(c.analyzing)
        assertEquals(0, c.progress)
        assertNull(c.result)
        assertTrue(c.evidence.isEmpty())
        assertTrue(c.remaining.isEmpty())
    }

    @Test fun finishedWithVerdict() {
        val c = BbCase.parse(load("right_turn_left_straight"))
        assertTrue(c.finished)
        val r = c.result!!
        assertEquals("ok", r.status)
        assertTrue(r.provisional)
        assertEquals("차13-1", r.ruleId)
        assertEquals(60, r.egoFault)
        assertEquals(40, r.otherFault)
        assertEquals("car_car", r.chapter)
        assertEquals("ratio", r.display!!.kind)
        assertEquals("내 차 60 : 상대 40", r.display!!.text)
        assertFalse(r.display!!.pedestrianOnly)
        assertEquals(18.2, c.collisionT!!, 1e-6)
        assertEquals(1794202212000L, c.startMs)
        assertEquals(1794202212000L + 18200, c.accidentAt)
        // 남은 질문: 서버 remaining 그대로, 개수는 remaining_count
        assertEquals(5, c.remainingCount)
        assertEquals(
            listOf("road.signal_present", "road.wider_road", "road.center_line", "intersection_entry_order",
                "parties.ego.turn_signal_used"),
            c.remaining.map { it.field },
        )
        // 근거 문장: 서버 answers[].evidence 그대로, 차량 → 영상 → 내 답변 → 가정 순
        val sources = c.evidence.map { it.source }
        assertEquals(sources.sortedBy { listOf("vehicle_info", "vehicle", "video", "user", "guess", "default").indexOf(it) }, sources)
        assertTrue(c.evidence.any { it.source == "video" && it.text == "내 차가 우회전했어요 (17.5초)" })
        assertTrue(c.evidence.any {
            it.source == "guess" && it.text == "교차로에 신호등이 없었어요 (영상 추정)"
        })
        assertTrue(c.userAnswers.isEmpty())
        // 상대 종류: 영상이 확실히 냄 → "상대가 승용차가 아니었나요?"
        val o = c.otherCls!!
        assertEquals("video", o.source)
        assertEquals("승용차", o.label)
        assertTrue(o.askable)
        assertEquals(7, o.options.size)
        assertEquals("pedestrian", o.options.last())
        assertEquals("보행자", o.choices.last())
    }

    @Test fun questionFields() {
        val q = BbCase.parse(load("right_turn_left_straight")).remaining
        val signal = q[0]
        assertEquals("이 교차로에 신호등이 있었나요?", signal.question)
        assertEquals(listOf<Any?>(true, false), signal.options)
        assertEquals(listOf("있음", "없음"), signal.choices)
        assertEquals(false, signal.modelGuess)
        assertEquals(1, signal.guessIndex)
        assertEquals("video", signal.guessSource)
        assertEquals("영상으로는 교차로에 신호등이 없었던 것 같아요 (추정)", signal.guessEvidence)
        assertTrue(signal.answerable)
        val wider = q[1]
        assertEquals(mapOf("parties.other.entry_from" to listOf<Any?>("left", "right")), wider.dependsOn)
        assertEquals(-1, q[2].guessIndex)
    }

    @Test fun pedestrianOnlyDisplay() {
        val c = BbCase.parse(load("ped_crosswalk_unsignalized"))
        // 2026-11-11부터 보행자 장에 가감 요소 질문 셋이 남아 needs_answers (판정은 그대로)
        assertEquals(BbCase.NEEDS_ANSWERS, c.status)
        val d = c.result!!.display!!
        assertTrue(d.pedestrianOnly)
        assertEquals("보행자 과실 0%", d.text)
        assertEquals("차대보행자 기준은 보행자 과실만 정해요. 내 차 몫은 나머지 100%예요", d.note)
        assertEquals("car_pedestrian", c.result!!.chapter)
        assertEquals(3, c.remainingCount)
        assertEquals("보행자", c.otherCls!!.label)
    }

    /** 차량 기록은 참고 자료 (2026-11-10): 기본 판정의 근거에는 차량 기록이 없고 영상 값이 쓰인다 */
    @Test fun vehicleRecordIsNotInBaseEvidence() {
        val c = BbCase.parse(load("reverse_vehicle"))
        val e = c.evidence.first { it.field == "parties.ego.movement" }
        assertEquals("video", e.source)
        assertEquals("내 차가 직진했어요 (17초)", e.text)
        // 출처 vehicle은 내 차 종류뿐 → "차량 정보" 배지
        assertEquals(listOf("parties.ego.cls"), c.evidence.filter { it.source == BbCase.VEHICLE_INFO }.map { it.field })
        assertFalse(c.evidence.any { it.source == "vehicle" })
        assertTrue(c.vehicleRecord)
        assertEquals("coarse", c.syncGrade)
        assertEquals("no_rule", c.resultWithVehicle!!.status)
        assertTrue(c.vehicleEffects.isEmpty())
        val t = c.timeline!!
        assertFalse(t.aligned)
        assertEquals("coarse", t.syncGrade)
    }

    @Test fun noCollision() {
        val c = BbCase.parse(load("no_collision"))
        assertTrue(c.failed)
        assertFalse(c.finished)
        assertEquals("no_impact", c.analysis!!.reason)
        assertEquals("부딪힌 순간을 찾지 못했어요", c.analysis!!.message)
        assertEquals(0, c.remainingCount)
    }

    @Test fun guessOtherCls() {
        val c = BbCase.parse(load("mostly_unknown"))
        assertEquals(9, c.remainingCount)
        assertEquals("no_rule", c.result!!.status)
        assertNull(c.result!!.display)
        assertNull(c.result!!.egoFault)
        // 상대 종류 추정값 → 질문 맨 앞, 근거는 "추정" 배지
        assertEquals("guess", c.otherCls!!.source)
        assertTrue(c.otherCls!!.askable)
        assertEquals(BbCase.OtherCls.FIELD, c.remaining.first().field)
        assertEquals("guess", c.evidence.first { it.field == BbCase.OtherCls.FIELD }.source)
    }

    @Test fun userAnswersAfterPut() {
        val c = BbCase.parse(load("answered"))
        assertEquals(
            mapOf<String, Any?>(
                "road.signal_present" to true, "road.wider_road" to "equal", "road.center_line" to true,
                "intersection_entry_order" to "ego", "parties.ego.turn_signal_used" to true,
            ),
            c.userAnswers,
        )
        assertEquals(4, c.remainingCount)
        assertTrue(c.evidence.any { it.source == "user" && it.text == "교차로에 신호등이 있었어요 (직접 답했어요)" })
        val p = BbCase.parse(load("cls_pedestrian"))
        assertEquals("user", p.otherCls!!.source)
        assertFalse(p.otherCls!!.askable)
        assertEquals("car_pedestrian", p.result!!.chapter)
    }

    @Test fun metaKeepsMtimeOutOfRecordedAt() {
        val m = BbApi.meta(
            name = "20261109_143012_F.mp4", sizeBytes = 10, durationMs = 30_000,
            candidates = listOf(StartCandidate("filename", 1L), StartCandidate("mtime", 2L)),
            mtimeMs = 32_002L, tzOffsetMin = 540,
        )
        assertEquals("20261109_143012_F.mp4", m.getString("filename"))
        assertEquals(1, m.getJSONArray("recorded_at").length())
        assertEquals("filename", m.getJSONArray("recorded_at").getJSONObject(0).getString("source"))
        assertEquals(32_002L, m.getLong("mtime_ms"))
        assertEquals(30.0, m.getDouble("duration_s"), 1e-9)
        assertEquals(540, m.getInt("tz_offset_min"))
    }
}
