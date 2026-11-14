package com.example.hmtm.data.bb

import com.example.hmtm.ui.history.vehicleText
import com.example.hmtm.ui.questions.hintNote
import com.example.hmtm.ui.record.speedScale
import com.example.hmtm.ui.record.timeTicks
import com.example.hmtm.ui.result.NO_EFFECT
import com.example.hmtm.ui.result.vehicleSummary
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 차량 기록은 참고 자료 (docs/design-blackbox.md 4.4). 응답 파일 left_turn_effect / left_turn_noeffect / list_vehicle은
 * backend 가짜 분석기 left_turn_motion(차16-1)에 영상 움직임을 따라 달린 차량 기록(fine)을 붙여 저장한 것 (2026-11-10).
 * effect = 지시등을 켜지 않음, noeffect = 부딪히기 6초 전부터 LEFT.
 */
class VehicleEvidenceTest {
    private fun load(name: String) =
        BbCase.parse(JSONObject(javaClass.getResource("/bb/$name.json")!!.readText(Charsets.UTF_8)))

    @Test fun twoVerdicts() {
        val c = load("left_turn_effect")
        assertEquals("fine", c.syncGrade)
        assertEquals("차16-1", c.result!!.ruleId)
        assertEquals(60 to 40, c.result!!.egoFault to c.result!!.otherFault)
        assertEquals("내 차 70 : 상대 30", c.resultWithVehicle!!.display!!.text)
        val e = c.vehicleEffects.single()
        assertEquals("방향지시등", e.label)
        assertEquals("안 켬", e.valueLabel)
        assertEquals("내 차가 방향지시등을 켜지 않았어요", e.summary)
        assertTrue(e.applied)
        assertEquals(10, e.egoDelta)
        assertEquals(VehicleEffect.EGO_MORE, e.direction)
        assertEquals("내 차 과실 +10", e.deltaText)
        // 지시등 질문은 남아 있고 차량 기록 값은 참고로만
        val q = c.remaining.first { it.field == "parties.ego.turn_signal_used" }
        assertNull(q.modelGuess)
        val h = q.vehicleHint!!
        assertEquals("안 켬", h.valueLabel)
        assertTrue(h.determined)
        assertTrue(h.applied)
        assertEquals("참고용이에요. 결과는 고른 답으로 정해요", hintNote(h))
        // 기본 판정 근거에 차량 기록 값이 없음
        assertFalse(c.evidence.any { it.field == "parties.ego.turn_signal_used" })
    }

    @Test fun resultCard() {
        val s = vehicleSummary(load("left_turn_effect"))!!
        assertEquals("내 차 70 : 상대 30", s.headline)
        assertNull(s.message)
        assertEquals(listOf("내 차 과실 +10"), s.rows.map { it.badge })
        assertTrue(s.canOpenRecord)

        val n = vehicleSummary(load("left_turn_noeffect"))!!
        assertNull(n.headline)
        assertEquals(NO_EFFECT, n.message)
        assertTrue(n.rows.isEmpty())

        // 차량 기록이 없으면 카드가 없음
        assertNull(vehicleSummary(load("right_turn_left_straight")))
    }

    @Test fun coarseNotApplied() {
        val o = JSONObject(javaClass.getResource("/bb/left_turn_effect.json")!!.readText(Charsets.UTF_8))
        val e = o.getJSONArray("vehicle_effects").getJSONObject(0)
        e.put("applied", false).put("reason", "sync_coarse").put("reason_text", "영상과 차량 기록의 시각을 대략만 맞췄어요")
            .put("fault_by_party_if_applied", JSONObject().put("ego", 70).put("other", 30))
        val s = vehicleSummary(BbCase.parse(o.put("vehicle_effects", JSONArray().put(e))))!!
        assertNull(s.headline)
        assertEquals("영상과 차량 기록의 시각을 대략만 맞췄어요", s.message)
        assertEquals("반영 안 함", s.rows.single().badge)
        assertEquals("시각이 정확히 맞으면 내 차 70 : 상대 30", s.rows.single().sub)
        assertFalse(s.rows.single().applied)
    }

    @Test fun timeline() {
        val t = load("left_turn_noeffect").timeline!!
        assertTrue(t.aligned)
        assertEquals(-15.0, t.fromS, 1e-9)
        assertEquals(101, t.speed.size)
        assertEquals(listOf(VehicleTimeline.Span(-6.0, 5.0, "LEFT")), t.turnSignal)
        assertEquals("부딪히기 6.0초 전부터 왼쪽 지시등을 켜고 있었어요", TimelineText.turnSignal(t))
        assertEquals("부딪힌 뒤에 브레이크를 밟았어요", TimelineText.brake(t))
        assertTrue(TimelineText.speed(t).startsWith("부딪힐 때 속도 "))
        assertEquals(listOf("D"), t.gear.map { it.label })
        val off = load("left_turn_effect").timeline!!
        assertEquals("부딪히기 전에 지시등을 켜지 않았어요", TimelineText.turnSignal(off))
        assertEquals(50.0, speedScale(t.speedMax), 1e-9)
        assertEquals(listOf(-15.0, -10.0, -5.0, 0.0, 5.0), timeTicks(-15.0, 5.0))
        assertEquals("−6.0초", TimelineText.sec(-6.0))
    }

    @Test fun timelineTexts() {
        val t = VehicleTimeline(
            -15.0, 5.0, listOf(-0.2 to 23.4, 0.0 to 10.0), 41.0,
            listOf(VehicleTimeline.Span(-8.0, -3.0, "RIGHT")), listOf(VehicleTimeline.Span(-1.2, 5.0)),
            emptyList(), emptyList(), "coarse", false, null,
        )
        assertEquals("부딪히기 8.0초 전~3.0초 전 오른쪽 지시등 (부딪힐 때는 꺼짐)", TimelineText.turnSignal(t))
        assertEquals("부딪히기 1.2초 전부터 브레이크를 밟았어요", TimelineText.brake(t))
        assertEquals("부딪힐 때 속도 23km/h · 이 구간 최고 41km/h", TimelineText.speed(t))
    }

    @Test fun answeredDefinitions() {
        val a = load("answered")
        assertEquals(5, a.answered.size)
        assertEquals("이 교차로에 신호등이 있었나요?", a.answered.first().question)
    }

    @Test fun listRows() {
        val rows = JSONArray(javaClass.getResource("/bb/list_vehicle.json")!!.readText(Charsets.UTF_8)).let { arr ->
            (0 until arr.length()).map { BbSummary.parse(arr.getJSONObject(it)) }
        }
        val changed = rows.first { it.vehicleChanges }
        assertTrue(changed.vehicleRecord)
        assertEquals("기록 입증 시 70 : 30", vehicleText(changed))
        val same = rows.first { it.vehicleRecord && !it.vehicleChanges && it.ruleId == "차16-1" }
        assertNull(vehicleText(same))
        assertNotNull(same.displayWithVehicle)
        assertTrue(rows.any { !it.vehicleRecord })
    }
}
