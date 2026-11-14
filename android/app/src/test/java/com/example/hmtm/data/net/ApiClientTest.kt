package com.example.hmtm.data.net

import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test

/** 가짜 서버로 로그인·가입·재발급 흐름 확인 (서버 규칙은 backend/src/server/auth.py) */
class ApiClientTest {
    private lateinit var server: MockWebServer
    private val tokens = MemoryTokenStore()
    private val log = mutableListOf<String>()

    // 가짜 서버 상태
    private var signedUp = false
    private var validAccess = "a1"
    private var validRefresh = "r1"
    private var issued = 1
    private var takenNick: String? = null

    private fun json(code: Int, body: JSONObject) = MockResponse().setResponseCode(code).setBody(body.toString())
    private fun err(code: Int, e: String) = json(code, JSONObject().put("error", e).put("message", "메시지 $e"))
    private fun issue(): MockResponse {
        issued++
        validAccess = "a$issued"; validRefresh = "r$issued"
        return json(200, JSONObject().put("access", validAccess).put("refresh", validRefresh)
            .put("user", JSONObject().put("needs_signup", !signedUp)))
    }

    @Before fun setUp() {
        server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(r: RecordedRequest): MockResponse {
                val path = r.path!!
                log += "${r.method} $path"
                val body = r.body.readUtf8()
                val bearer = r.getHeader("Authorization")?.removePrefix("Bearer ")
                return when (path) {
                    "/api/auth/dev" -> issue()
                    "/api/token/refresh" ->
                        if (JSONObject(body).getString("refresh") == validRefresh) issue() else err(401, "token_invalid")
                    "/api/me" -> when {
                        bearer != validAccess -> err(401, "token_expired")
                        JSONObject(body).getString("nickname") == takenNick -> err(409, "nickname_taken")
                        else -> { signedUp = true; json(200, JSONObject().put("needs_signup", false)) }
                    }
                    else -> when {
                        bearer != validAccess -> err(401, "token_expired")
                        !signedUp -> err(403, "signup_required")
                        else -> json(200, JSONObject().put("ok", true))
                    }
                }
            }
        }
        server.start()
    }

    @After fun tearDown() = server.shutdown()

    private fun client() = ApiClient(server.url("/").toString(), tokens, isMainThread = { false })

    @Test fun firstCallLogsInAndSignsUp() = runBlocking {
        val r = client().getJson("/api/bb-cases/x")
        assertTrue(r.getBoolean("ok"))
        assertEquals(listOf("POST /api/auth/dev", "PUT /api/me", "GET /api/bb-cases/x"), log)
        assertNotNull(tokens.devName)
        assertEquals(validAccess, tokens.access)
    }

    @Test fun expiredAccessIsRefreshed() = runBlocking {
        client().getJson("/x")
        log.clear()
        validAccess = "server-restarted"        // 기존 access 무효
        client().getJson("/x")
        assertEquals(listOf("GET /x", "POST /api/token/refresh", "GET /x"), log)
    }

    @Test fun badRefreshFallsBackToLogin() = runBlocking {
        client().getJson("/x")
        val name = tokens.devName
        log.clear()
        validAccess = "x"; validRefresh = "y"  // 둘 다 무효 (서버 비밀이 바뀜)
        client().getJson("/x")
        assertEquals(listOf("GET /x", "POST /api/token/refresh", "POST /api/auth/dev", "GET /x"), log)
        assertEquals(name, tokens.devName)      // 같은 이름 = 같은 회원
    }

    @Test fun nicknameTakenRetries() = runBlocking {
        tokens.devName = "hmtm-abcd1234"
        takenNick = ApiClient.nickname("hmtm-abcd1234")
        client().getJson("/x")
        assertEquals(2, log.count { it == "PUT /api/me" })
    }

    @Test fun serverErrorKeepsCodeAndMessage() = runBlocking {
        signedUp = true
        server.dispatcher.let { inner ->
            server.dispatcher = object : Dispatcher() {
                override fun dispatch(r: RecordedRequest) =
                    if (r.path == "/api/bb-cases/none") err(404, "bb_case_not_found") else inner.dispatch(r)
            }
        }
        try {
            client().getJson("/api/bb-cases/none")
            fail()
        } catch (e: ApiException) {
            assertEquals(404, e.status)
            assertEquals("bb_case_not_found", e.code)
            assertEquals("메시지 bb_case_not_found", e.message)
        }
    }

    @Test fun networkFailure() = runBlocking {
        val c = ApiClient("http://127.0.0.1:1", tokens, isMainThread = { false })
        try {
            c.getJson("/x"); fail()
        } catch (e: ApiException) {
            assertEquals(ApiException.NETWORK, e.code)
        }
    }

    @Test(expected = IllegalStateException::class)
    fun mainThreadIsRefused() {
        runBlocking { ApiClient(server.url("/").toString(), tokens, isMainThread = { true }).getJson("/x") }
    }
}
