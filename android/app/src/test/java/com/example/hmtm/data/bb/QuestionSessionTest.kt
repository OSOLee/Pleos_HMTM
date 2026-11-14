package com.example.hmtm.data.bb

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class QuestionSessionTest {
    companion object {
        val OPTIONAL = listOf("situation.special", "parties.ego.driver_factors", "parties.other.driver_factors")
    }

    private fun load(name: String) =
        BbCase.parse(JSONObject(javaClass.getResource("/bb/$name.json")!!.readText(Charsets.UTF_8)))

    @Test fun remainingInServerOrder() {
        val c = load("right_turn_left_straight")
        var s = QuestionSession.remaining(c)
        // remaining 서버 순서 그대로 + 뒤에 선택 질문(여러 개 고르기) 셋
        assertEquals(c.remaining.map { it.field } + OPTIONAL, s.questions.map { it.field })
        assertEquals("road.signal_present", s.current!!.field)
        assertEquals(1, s.position)
        assertEquals(8, s.total)
        assertFalse(s.hasSelection)
        // 신호등 있음 → 다음
        s = s.pick(true).next()
        assertEquals("road.wider_road", s.current!!.field)   // depends_on entry_from ∈ [left, right], 영상 값 left
        s = s.pick("mine").next()
        // 중앙선: 모르겠어요 → 답 없이 다음
        s = s.dontKnow().next()
        assertEquals("intersection_entry_order", s.current!!.field)
        s = s.pick("other").next()
        s = s.pick(false).next()
        // 선택 질문: 여러 개 고르기 화면, 건너뛰면 [] (답 없음)
        assertTrue(s.page is Page.Multi)
        s = s.skip().next().skip().next()
        assertTrue(s.isLast)
        s = s.skip().next()
        assertTrue(s.done)
        assertEquals(
            mapOf<String, Any?>(
                "road.signal_present" to true, "road.wider_road" to "mine",
                "intersection_entry_order" to "other", "parties.ego.turn_signal_used" to false,
            ) + OPTIONAL.associateWith { emptyList<Any?>() },
            s.answers(),
        )
    }

    @Test fun dependsOnSkipsQuestion() {
        val c = load("mostly_unknown")
        var s = QuestionSession.remaining(c)
        // 상대 종류 추정값 질문이 맨 앞 (서버 순서)
        assertEquals(BbCase.OtherCls.FIELD, s.current!!.field)
        assertEquals("car", s.current!!.modelGuess)
        assertEquals(0, s.current!!.guessIndex)
        val q = Question(
            "road.wider_road", "넓은 길?", "choice", listOf("equal", "mine"), listOf("같음", "내 길"),
            null, null, null, null, mapOf("parties.other.entry_from" to listOf<Any?>("left", "right")),
        )
        s = s.copy(questions = s.questions + q)
        // 상대가 온 길을 답하기 전에는 조건이 안 맞아 안 보임
        assertFalse(s.visible(q))
        assertEquals(12, s.total)        // 남은 9 + 선택 질문 3
        val withLeft = s.copy(picked = mapOf("parties.other.entry_from" to "left"))
        assertTrue(withLeft.visible(q))
        assertEquals(13, withLeft.total)
    }

    @Test fun backAndForth() {
        var s = QuestionSession.remaining(load("right_turn_left_straight"))
        assertTrue(s.isFirst)
        s = s.pick(false).next()
        assertFalse(s.isFirst)
        s = s.prev()
        assertEquals("road.signal_present", s.current!!.field)
        assertEquals(false, s.selected)
        assertTrue(s.hasSelection)
    }

    @Test fun otherClsFromRemainingOrButton() {
        // 추정(guess): remaining 맨 앞 질문을 그대로 (추정값 포함)
        val g = QuestionSession.otherCls(load("mostly_unknown"))!!
        assertEquals(1, g.questions.size)
        assertEquals("영상으로는 상대는 승용차였던 것 같아요 (추정)", g.current!!.guessEvidence)
        // 영상이 확실히 냄: other_cls의 보기로 질문을 만듦
        val v = QuestionSession.otherCls(load("right_turn_left_straight"))!!
        val q = v.current!!
        assertEquals(BbCase.OtherCls.FIELD, q.field)
        assertEquals(listOf("승용차", "화물차", "버스", "이륜차", "자전거", "농기계", "보행자"), q.choices)
        assertNull(q.modelGuess)
        val done = v.pick("pedestrian").next()
        assertTrue(done.done)
        assertEquals(mapOf<String, Any?>("parties.other.cls" to "pedestrian"), done.answers())
    }

    @Test fun editKeepsAnswersAndPrefills() {
        val first = load("right_turn_left_straight")
        val answered = load("answered")
        // 답한 질문의 정의는 서버 answered에 있음 (전에는 앱이 처음 본 질문을 보관했음)
        assertEquals(first.remaining.map { it.field }, answered.answered.map { it.field })
        var s = QuestionSession.edit(answered)
        assertTrue(s.editing)
        // 답했던 5개 + 새로 남은 4개
        assertEquals(
            listOf(
                "road.signal_present", "road.wider_road", "road.center_line", "intersection_entry_order",
                "parties.ego.turn_signal_used", "parties.ego.signal_at_entry", "parties.other.signal_at_entry",
                "parties.ego.ped_signal_green_at_turn", "intersection_entry_clear",
            ) + OPTIONAL,
            s.questions.map { it.field },
        )
        assertEquals(true, s.selected)                 // 전에 고른 답이 채워져 있음
        // 바꾸지 않으면 답이 그대로
        assertEquals(answered.userAnswers, s.answers())
        // 신호등을 "없음"으로 바꾸면 신호 질문들은 안 보임
        s = s.pick(false)
        assertFalse(s.visible(s.questions.first { it.field == "parties.ego.signal_at_entry" }))
        // 중앙선을 모르겠어요 → 전에 했던 답도 뺌
        s = s.next().next()
        assertEquals("road.center_line", s.current!!.field)
        s = s.dontKnow()
        val a = s.answers()
        assertFalse(a.containsKey("road.center_line"))
        assertEquals(false, a["road.signal_present"])
        assertEquals("ego", a["intersection_entry_order"])
    }

    @Test fun editAfterOtherClsAnswer() {
        val p = load("cls_pedestrian")          // 상대 종류를 보행자로 답한 사건
        val s = QuestionSession.edit(p)
        // answered에 없어도 상대 종류 질문은 other_cls로 만든다
        assertEquals(BbCase.OtherCls.FIELD, s.questions.first().field)
        assertEquals("pedestrian", s.selected)
        assertNotNull(s.questions.firstOrNull { it.field == "parties.other.crosswalk_distance" })
    }

    @Test fun mergeKeepsOrder() {
        val a = Question("a", "A?", "choice", listOf(1), listOf("1"), null, null, null, null, null)
        val b = Question("b", "B?", "choice", listOf(1), listOf("1"), null, null, null, null, null)
        val a2 = a.copy(question = "A2?")
        assertEquals(listOf(a2, b), Questions.merge(listOf(a), listOf(b, a2)))
    }
}
