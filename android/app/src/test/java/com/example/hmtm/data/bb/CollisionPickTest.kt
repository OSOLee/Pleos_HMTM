package com.example.hmtm.data.bb

import com.example.hmtm.data.net.ApiClient
import com.example.hmtm.data.net.ApiException
import com.example.hmtm.data.net.MemoryTokenStore
import com.example.hmtm.ui.player.Replay
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * 사고 순간 고르기 (design-blackbox 3.2·3.6 PUT collision, collision_review).
 * 응답 파일은 android/tools/save_bb_responses.py로 지금 서버(가짜 분석기)에서 저장:
 * no_collision_pick(후보 18.2·12.0초) → PUT {"t": 18.2} → pick_accepted(202) → pick_done(차13-1),
 * no_collision → PUT {"t": 12.0} → pick_failed(last_pick, 결과 그대로), pick_errors(409·422), list_pick(목록)
 */
class CollisionPickTest {
    private fun res(name: String) = javaClass.getResource("/bb/$name.json")!!.readText(Charsets.UTF_8)
    private fun load(name: String) = BbCase.parse(JSONObject(res(name)))

    @Test fun needsPickWithCandidates() {
        val c = load("no_collision_pick")
        assertEquals(BbCase.NO_COLLISION, c.status)
        assertFalse(c.finished)
        assertTrue(c.showable)          // 판정은 없지만 결과 화면에서 고르기를 안내
        val r = c.review!!
        assertTrue(r.needed && r.canPick && !r.expired)
        assertEquals("no_collision", r.reason)
        assertEquals(listOf(18.2, 12.0), r.candidates.map { it.t })
        assertNotNull(r.pickUntil)
        assertTrue(r.message!!.startsWith("영상에서 사고 순간을 찾지 못했어요"))
        assertNull(r.lastPick)
    }

    @Test fun pickedThenJudged() {
        assertEquals(BbCase.ANALYZING, load("pick_accepted").status)
        val c = load("pick_done")
        assertTrue(c.finished)
        val r = c.review!!
        assertFalse(r.needed || r.canPick)
        assertEquals(18.2, r.pickedT!!, 1e-9)
        assertEquals("차13-1", c.result!!.ruleId)
        assertEquals(18.2, c.collisionT!!, 1e-9)
    }

    @Test fun pickFailedKeepsResult() {
        val c = load("pick_failed")
        assertEquals(BbCase.NO_COLLISION, c.status)
        val r = c.review!!
        assertTrue(r.needed && r.canPick)
        val last = r.lastPick!!
        assertEquals(12.0, last.t!!, 1e-9)
        assertEquals("no_collision", last.status)
        assertEquals("부딪힌 순간을 찾지 못했어요", last.message)
    }

    @Test fun ordinaryCaseNeedsNoPick() {
        val c = load("right_turn_left_straight")
        assertFalse(c.review!!.needed)
        assertFalse(c.review!!.canPick)
        assertTrue(c.review!!.candidates.isEmpty())
    }

    @Test fun listRowFlag() {
        val rows = JSONArray(res("list_pick")).let { a -> (0 until a.length()).map { BbSummary.parse(a.getJSONObject(it)) } }
        val pick = rows.first { it.collisionReviewNeeded }
        assertEquals(BbCase.NO_COLLISION, pick.status)
        assertNotNull(pick.collisionPickUntil)
        assertTrue(pick.openable && !pick.finished)
        assertTrue(rows.filterNot { it.collisionReviewNeeded }.all { it.collisionPickUntil == null })
    }

    @Test fun errorShapes() {
        val e = JSONObject(res("pick_errors"))
        assertEquals(409, e.getJSONObject("not_needed").getInt("status"))
        assertEquals("collision_not_needed", e.getJSONObject("not_needed").getJSONObject("body").getString("error"))
        assertEquals("collision_invalid", e.getJSONObject("invalid").getJSONObject("body").getString("error"))
    }

    @Test fun putCollisionAndErrors() = runBlocking {
        var body = ""
        var path = ""
        val server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(r: RecordedRequest): MockResponse = when {
                r.path == "/api/auth/dev" -> MockResponse().setBody("""{"access":"a","refresh":"r","user":{"needs_signup":false}}""")
                r.path!!.endsWith("/gone/collision") -> MockResponse().setResponseCode(410)
                    .setBody("""{"error":"video_gone","message":"영상 보관 기간(7일)이 지나 영상을 지웠어요. 영상을 다시 올려 주세요"}""")
                r.method == "PUT" -> {
                    path = r.path!!
                    body = r.body.readUtf8()
                    MockResponse().setResponseCode(202).setBody(res("pick_accepted"))
                }
                else -> MockResponse().setResponseCode(404)
            }
        }
        server.start()
        try {
            val api = BbApi(ApiClient(server.url("/").toString(), MemoryTokenStore(), isMainThread = { false }))
            val c = api.putCollision("abc", 18.2004)
            assertEquals("/api/bb-cases/abc/collision", path)
            assertEquals(18.2, JSONObject(body).getDouble("t"), 1e-9)   // 1/1000초까지
            assertTrue(c.analyzing)
            try {
                api.putCollision("gone", 3.0)
                fail()
            } catch (e: ApiException) {
                assertEquals(410, e.status)
                assertEquals("video_gone", e.code)
            }
        } finally {
            server.shutdown()
        }
    }

    @Test fun pickerSteps() {
        assertEquals(0, Replay.step(500, -1000, 30_000))
        assertEquals(30_000, Replay.step(29_900, 1000, 30_000))
        assertEquals(12_200, Replay.step(12_000, 200, 30_000))
        assertEquals("0:18.2", Replay.clockTenth(18_250))
    }
}
