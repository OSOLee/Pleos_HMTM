package com.example.hmtm.ui.history

import com.example.hmtm.data.bb.BbSummary
import org.json.JSONArray
import org.junit.Assert.assertEquals
import org.junit.Test

class HistoryTextTest {
    private val list = JSONArray(javaClass.getResource("/bb/list.json")!!.readText(Charsets.UTF_8)).let { a ->
        (0 until a.length()).map { BbSummary.parse(a.getJSONObject(it)) }
    }

    @Test fun rowTexts() {
        val bike = list.first { it.chapter == "car_bicycle" }
        assertEquals("100 : 0", faultText(bike))
        assertEquals("자전거횡단도로 횡단 자전거 대 자전거횡단도로 전후 직진 자동차", summaryText(bike))
        val ped = list.first { it.chapter == "car_pedestrian" && it.ruleId == "보13" }
        assertEquals("보행자 과실 0%", faultText(ped))
        val noRule = list.first { it.chapter == "car_pedestrian" && it.ruleId == null }
        assertEquals("—", faultText(noRule))
        assertEquals("상대 보행자 · 기준 찾는 중", summaryText(noRule))
    }
}
