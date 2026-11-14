package com.example.hmtm.data.bb

import com.example.hmtm.R
import com.example.hmtm.ui.result.notices
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 여러 개 고르기·묶음·이어지는 질문·결과 안내 (docs/app-ui.md 2.8, 2.5 "확인해 주세요").
 * 응답 파일은 지금 backend로 만든 것: ped_modifiers(보행자 가감 요소 셋), car_speed(내 차 과속 답 → 인과관계 질문),
 * clock_mismatch(차량 기록 2시간 어긋남 + 시계 3일 전)
 */
class MultiChoiceTest {
    private fun load(name: String) =
        BbCase.parse(JSONObject(javaClass.getResource("/bb/$name.json")!!.readText(Charsets.UTF_8)))

    private val driver = "parties.ego.driver_factors"

    private fun multiSession(): QuestionSession {
        val c = load("right_turn_left_straight")
        val q = c.optionalQuestions.first { it.field == driver }
        return QuestionSession(c.id, listOf(q))
    }

    @Test fun parsesOptionalMulti() {
        val c = load("ped_modifiers")
        val q = c.optionalQuestions.single()
        assertEquals(driver, q.field)
        assertTrue(q.multi && q.optional && q.answerable)
        assertEquals(q.options.size - 1, q.noneIndex)        // "해당 없음"은 맨 끝
        assertEquals("해당 없음 (모두 아니요)", q.choices.last())
        // 특수 상황은 보기 묶음 이름이 있음
        val sp = load("right_turn_left_straight").optionalQuestions.first { it.field == "situation.special" }
        assertEquals(sp.options.size, sp.optionGroups!!.size)
    }

    @Test fun multiThreeKindsOfAnswer() {
        var s = multiSession()
        assertTrue(s.page is Page.Multi)
        assertFalse(s.hasSelection)                          // 고르기 전에는 "다음"이 꺼짐
        // 1) 고른 보기 목록
        s = s.toggle(driver, "speed_20plus").toggle(driver, "phone")
        assertEquals(listOf("speed_20plus", "phone"), s.chosen(driver))
        assertTrue(s.hasSelection)
        // "해당 없음"을 고르면 나머지가 꺼지고 혼자만
        s = s.toggle(driver, Question.NONE)
        assertEquals(listOf(Question.NONE), s.chosen(driver))
        // 다른 보기를 고르면 "해당 없음"이 꺼짐
        s = s.toggle(driver, "phone")
        assertEquals(listOf("phone"), s.chosen(driver))
        assertEquals(mapOf(driver to listOf("phone")), s.next().answers())
        // 모두 끄면 고른 것 없음 (답에 없음)
        s = s.toggle(driver, "phone")
        assertFalse(s.hasSelection)
        assertFalse(s.answers().containsKey(driver))
        // 2) 아무것도 안 고르고 건너뛰기 = [] (답 없음)
        assertEquals(mapOf(driver to emptyList<Any?>()), s.skip().next().answers())
        // 3) "해당 없음" = ["none"]
        assertEquals(mapOf(driver to listOf(Question.NONE)), s.toggle(driver, Question.NONE).next().answers())
    }

    @Test fun skipReplacesEarlierAnswer() {
        val s = multiSession().copy(base = mapOf(driver to listOf("phone")), picked = mapOf(driver to listOf("phone")))
        assertEquals(mapOf(driver to emptyList<Any?>()), s.skip().next().answers())
    }

    @Test fun pedestrianModifiersBundled() {
        val c = load("ped_modifiers")
        var s = QuestionSession.remaining(c)
        // 가감 요소 셋이 한 화면 + 운전자 요인(선택) 한 화면
        assertEquals(2, s.total)
        val p = s.page as Page.Bundle
        assertEquals(listOf("parties.other.vulnerable_type", "road.protection_zone", "road.ped_visibility"), p.fields)
        assertFalse(s.hasSelection)
        // 밤만 고름 → 고르지 않은 두 질문은 답하지 않음 (추측하지 않음)
        s = s.toggleIn(p, "road.ped_visibility", "night")
        assertTrue(s.hasSelection)
        // 같은 질문 안에서는 하나만
        s = s.toggleIn(p, "road.ped_visibility", "obstructed")
        assertEquals("obstructed", s.picked["road.ped_visibility"])
        s = s.toggleIn(p, "road.ped_visibility", "night")
        val after = s.next()
        assertEquals(mapOf<String, Any?>("road.ped_visibility" to "night"), after.answers())
        assertTrue(after.page is Page.Multi)
    }

    @Test fun bundleNoneIsExclusive() {
        val c = load("ped_modifiers")
        var s = QuestionSession.remaining(c)
        val p = s.page as Page.Bundle
        s = s.toggleIn(p, "road.ped_visibility", "night").toggleBundleNone(p)
        assertTrue(s.bundleNone(p))
        // 해당 없음 = 질문마다 그 질문의 "해당 없음" 값 (서버에는 따로 보냄)
        assertEquals(
            mapOf<String, Any?>(
                "parties.other.vulnerable_type" to "none", "road.protection_zone" to "none", "road.ped_visibility" to "clear",
            ),
            s.next().answers(),
        )
        // 다른 보기를 고르면 "해당 없음"이 풀리고 그 보기만
        s = s.toggleIn(p, "parties.other.vulnerable_type", "child")
        assertFalse(s.bundleNone(p))
        assertEquals(mapOf<String, Any?>("parties.other.vulnerable_type" to "child"), s.next().answers())
        // 건너뛰기: 묶음 질문 모두 답 없음 (전에 했던 답도 뺌)
        val before = s.copy(base = mapOf("road.protection_zone" to "child"))
        assertEquals(emptyMap<String, Any?>(), before.skip().next().answers())
    }

    @Test fun followUpAfterSpeeding() {
        val c = load("car_speed")
        // 서버에 과속을 보낸 뒤: remaining 끝에 인과관계 질문
        assertEquals(listOf("speed_20plus"), c.userAnswers[driver])     // 여러 개 고르기 답은 List로
        val asked = load("right_turn_left_straight").remaining.map { it.field } + QuestionSessionTest.OPTIONAL
        val f = QuestionSession.followUp(c, asked)!!
        assertTrue(f.followUp)
        assertEquals(listOf("parties.ego.avoidable_at_limit"), f.questions.map { it.field })
        assertEquals(listOf("예 (피할 수 있었음)", "아니요 (지켰어도 났을 것)"), f.current!!.choices)
        // 답은 지금까지의 답 + 새 답
        assertEquals(listOf("speed_20plus"), f.pick(true).next().answers()[driver])
        // 새 질문이 없으면 결과로
        assertNull(QuestionSession.followUp(c, asked + "parties.ego.avoidable_at_limit"))
    }

    @Test fun editShowsMultiAnswer() {
        val c = load("car_speed")
        // 서버가 답한 선택 질문의 정의도 answered에 줌 (optional) → 서버 응답만으로 답변 고치기 (기기 보관 없음)
        val def = c.answered.first { it.field == driver }
        assertTrue(def.optional && def.multi)
        assertTrue(c.optionalQuestions.none { it.field == driver })
        val s = QuestionSession.edit(c)
        val i = s.pages.indexOfFirst { it is Page.Multi && it.fields == listOf(driver) }
        assertTrue(i >= 0)
        assertEquals(listOf("speed_20plus"), s.copy(index = i).chosen(driver))
        // 답하지 않은 선택 질문(특수 상황·상대 운전자 요인)은 응답의 정의로 한 번씩
        assertEquals(1, s.questions.count { it.field == "situation.special" })
        // 과속 인과관계 질문은 운전자 요인 바로 뒤, 과속을 빼면 숨김
        val fields = s.questions.map { it.field }
        assertEquals(fields.indexOf(driver) + 1, fields.indexOf("parties.ego.avoidable_at_limit"))
        val avoid = s.questions.first { it.field == "parties.ego.avoidable_at_limit" }
        assertTrue(s.visible(avoid))
        assertFalse(s.copy(index = i).toggle(driver, Question.NONE).visible(avoid))
        // 과속을 빼면 인과관계 답도 보내지 않음
        val avoidF = "parties.ego.avoidable_at_limit"
        assertTrue(s.copy(picked = s.picked + (avoidF to true)).answers().containsKey(avoidF))
        val noSpeed = s.copy(index = i, picked = s.picked + (avoidF to true)).toggle(driver, Question.NONE)
        assertFalse(noSpeed.answers().containsKey("parties.ego.avoidable_at_limit"))
    }

    @Test fun editKeepsBundleTogether() {
        // 밤만 답한 보행자 사건: 답한 질문(answered)이 앞, 남은 둘이 뒤로 흩어져도 한 화면으로 모음
        val p = load("ped_modifiers")
        val vis = p.remaining.first { it.field == "road.ped_visibility" }
        val c = p.copy(
            answered = listOf(vis), remaining = p.remaining - vis, userAnswers = mapOf(vis.field to "night"),
        )
        val s = QuestionSession.edit(c)
        val b = s.pages.first() as Page.Bundle
        assertEquals(setOf("parties.other.vulnerable_type", "road.protection_zone", "road.ped_visibility"), b.fields.toSet())
        assertEquals("night", s.picked["road.ped_visibility"])
    }

    @Test fun clockWarningsAndVehicleReason() {
        val c = load("clock_mismatch")
        assertEquals(listOf(true, false), c.clockWarnings.map { it.video })
        assertTrue(c.clockWarnings[0].message.contains("3일"))
        assertEquals("vehicle_clock_mismatch", c.syncReason)
        assertTrue(c.vehicleUnusedText!!.startsWith("차량 기록 시각과 영상 촬영 시각이 크게 어긋나"))
        assertEquals(
            listOf(R.string.notice_video_clock, R.string.notice_vehicle_clock, R.string.notice_vehicle_unused),
            notices(c).map { it.title },
        )
        // 차량 기록을 안 올린 사건(no_vehicle_record)은 안내 없음
        val p = load("ped_modifiers")
        assertEquals("no_vehicle_record", p.syncReason)
        assertNull(p.vehicleUnusedText)
        assertTrue(notices(p).isEmpty())
    }
}
