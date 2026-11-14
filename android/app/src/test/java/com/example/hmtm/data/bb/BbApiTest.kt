package com.example.hmtm.data.bb

import com.example.hmtm.data.net.ApiClient
import com.example.hmtm.data.net.ApiException
import com.example.hmtm.data.net.MemoryTokenStore
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import java.io.ByteArrayInputStream

class BbApiTest {
    private lateinit var server: MockWebServer
    private var gets = 0
    private var posted: String = ""
    private var postedType: String = ""
    private var puts = 0
    private var busyPuts = 0
    private var putBody = ""
    private val deleted = mutableListOf<String>()
    private var listPath = ""

    private fun res(name: String) = javaClass.getResource("/bb/$name.json")!!.readText(Charsets.UTF_8)

    @Before fun setUp() {
        server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(r: RecordedRequest): MockResponse = when {
                r.path == "/api/auth/dev" -> MockResponse().setBody(
                    """{"access":"a","refresh":"r","user":{"needs_signup":false}}""")
                r.method == "POST" && r.path == "/api/bb-cases" -> {
                    postedType = r.getHeader("Content-Type").orEmpty()
                    posted = r.body.readUtf8()
                    MockResponse().setResponseCode(202).setBody(res("analyzing"))
                }
                r.method == "PUT" && r.path!!.endsWith("/answers") -> {
                    puts++
                    putBody = r.body.readUtf8()
                    if (puts <= busyPuts) MockResponse().setResponseCode(409)
                        .setBody("""{"error":"bb_case_analyzing","message":"아직 분석 중이에요"}""")
                    else MockResponse().setBody(res("answered"))
                }
                r.method == "DELETE" && r.path == "/api/bb-cases" -> {
                    deleted += r.path!!
                    MockResponse().setBody("""{"deleted": 3}""")
                }
                r.method == "DELETE" -> {
                    deleted += r.path!!
                    if (r.path!!.endsWith("/gone")) MockResponse().setResponseCode(404)
                        .setBody("""{"error":"bb_case_not_found","message":"없어요"}""")
                    else MockResponse().setResponseCode(204)
                }
                r.method == "GET" && r.path!!.startsWith("/api/bb-cases?") -> {
                    listPath = r.path!!
                    MockResponse().setBody(res("list"))
                }
                r.path!!.startsWith("/api/bb-cases/") -> {
                    gets++
                    MockResponse().setBody(if (gets < 3) res("analyzing") else res("right_turn_left_straight"))
                }
                else -> MockResponse().setResponseCode(404)
            }
        }
        server.start()
    }

    @After fun tearDown() = server.shutdown()

    private fun api() = BbApi(ApiClient(server.url("/").toString(), MemoryTokenStore(), isMainThread = { false }))

    @Test fun uploadMultipartWithProgress() = runBlocking {
        val video = ByteArray(300_000) { (it % 251).toByte() }
        val meta = BbApi.meta("20261109_143012_F.mp4", video.size.toLong(), 30_000, emptyList(), null, 540)
        val progress = mutableListOf<Float>()
        val vehicle = JSONObject().put("range", JSONObject().put("from", 1).put("to", 2))
        val c = api().createRaw("20261109_143012_F.mp4", "video/mp4", video.size.toLong(),
            { ByteArrayInputStream(video) }, meta, vehicle, "no_collision") { progress += it }
        assertTrue(c.analyzing)
        assertTrue(postedType.startsWith("multipart/form-data"))
        for (part in listOf("name=\"video\"; filename=\"20261109_143012_F.mp4\"", "name=\"meta\"", "name=\"vehicle\"",
            "name=\"scenario\"", "no_collision", "\"tz_offset_min\":540")) {
            assertTrue(part, posted.contains(part))
        }
        assertEquals(1f, progress.last(), 0f)
        assertTrue(progress.size in 2..101)
        assertEquals(progress.sorted(), progress)
    }

    @Test fun pollsUntilFinished() = runBlocking {
        val seen = mutableListOf<String>()
        val c = api().await("abc", onUpdate = { seen += it.status }, intervalMs = 1)
        assertEquals(listOf("analyzing", "analyzing", "needs_answers"), seen)
        assertEquals("차13-1", c.result!!.ruleId)
    }

    @Test fun pollTimeout() = runBlocking {
        gets = -1_000_000
        try {
            api().await("abc", intervalMs = 1, timeoutMs = 20); fail()
        } catch (e: ApiException) {
            assertEquals("analysis_timeout", e.code)
        }
    }

    @Test fun putAnswersRetriesWhileAnalyzing() = runBlocking {
        busyPuts = 2
        var busy = 0
        val c = api().putAnswers(
            "abc", linkedMapOf("road.signal_present" to true, "road.wider_road" to "equal"),
            onBusy = { busy++ }, busyWaitMs = 1,
        )
        assertEquals(2, busy)
        assertEquals(3, puts)
        assertEquals(4, c.remainingCount)
        val sent = JSONObject(putBody).getJSONObject("answers")
        assertEquals(true, sent.get("road.signal_present"))
        assertEquals("equal", sent.get("road.wider_road"))
    }

    @Test fun putAnswersGivesUpAfterTries() = runBlocking {
        busyPuts = 100
        try {
            api().putAnswers("abc", emptyMap(), busyWaitMs = 1, busyTries = 3); fail()
        } catch (e: ApiException) {
            assertEquals(409, e.status)
            assertEquals("bb_case_analyzing", e.code)
        }
        assertEquals(3, puts)
    }

    @Test fun deleteAcceptsNoContentAndMissing() = runBlocking {
        api().delete("abc")
        api().delete("gone")
        assertEquals(listOf("/api/bb-cases/abc", "/api/bb-cases/gone"), deleted)
    }

    @Test fun deleteAllMine() = runBlocking {
        assertEquals(3, api().deleteAll())
        assertEquals(listOf("/api/bb-cases"), deleted)
    }

    @Test fun listWithPaging() = runBlocking {
        val items = api().list(before = 123L, limit = 20)
        assertEquals("/api/bb-cases?limit=20&before=123", listPath)
        assertTrue(items.isNotEmpty())
        val bike = items.first { it.chapter == "car_bicycle" }
        assertEquals("거42-1", bike.ruleId)
        assertEquals("내 차 100 : 상대 0", bike.display!!.text)
        assertEquals(1794202212000L + 18200, bike.accidentAt)
        assertEquals("자전거", bike.otherLabel)
        val ped = items.first { it.chapter == "car_pedestrian" && it.ruleId == null }
        assertEquals(8, ped.remainingCount)
        assertEquals(null, ped.display)
    }
}
