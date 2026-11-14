package com.example.hmtm.data.net

import android.os.Looper
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.util.UUID
import java.util.concurrent.TimeUnit

/** 서버 오류 {"error", "message"} 또는 연결 실패(status 0, code "network") */
class ApiException(val status: Int, val code: String, override val message: String) : Exception(message) {
    companion object {
        const val NETWORK = "network"
        const val MSG_NETWORK = "서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요"
    }
}

/** 로그인 토큰 보관 (기기에는 SharedPreferences, 시험에는 메모리) */
interface TokenStore {
    var access: String?
    var refresh: String?
    /** dev 로그인 이름. 기기마다 한 번 정해 같은 회원으로 다시 로그인한다 */
    var devName: String?
}

class MemoryTokenStore : TokenStore {
    override var access: String? = null
    override var refresh: String? = null
    override var devName: String? = null
}

/**
 * 서버 API 바탕 (OkHttp). 모든 호출은 suspend이고 IO 스레드에서 돈다. 메인 스레드에서 부르면 바로 예외.
 *
 * 로그인 (docs/SETUP.md 2.4 "로그인"):
 *  - 토큰이 없으면 POST /api/auth/dev {"token": devName} → access·refresh 저장
 *  - needs_signup이면 PUT /api/me {nickname, agree_terms: true} (닉네임이 겹치면 다른 이름으로 다시)
 *  - 401이면 POST /api/token/refresh, 그것도 401이면 dev 로그인부터 다시 → 원래 요청 한 번 더
 *  - 403 signup_required면 가입하고 한 번 더
 */
class ApiClient(
    baseUrl: String,
    private val tokens: TokenStore,
    private val http: OkHttpClient = defaultHttp(),
    private val isMainThread: () -> Boolean = { Looper.myLooper() == Looper.getMainLooper() },
) {
    private val base = baseUrl.trimEnd('/')

    /** 인증이 필요한 요청. body를 매번 새로 만들 수 있게 함수로 받는다 (재시도 때 다시 씀) */
    suspend fun call(method: String, path: String, body: (() -> RequestBody)? = null): JSONObject =
        parseObject(callText(method, path, body))

    /** 응답 본문을 글자 그대로 (배열 응답·빈 응답용) */
    suspend fun callText(method: String, path: String, body: (() -> RequestBody)? = null): String =
        withContext(Dispatchers.IO) {
            ensureLogin()
            try {
                sendText(method, path, body?.invoke(), auth = true)
            } catch (e: ApiException) {
                when {
                    e.status == 401 -> {
                        renew()
                        sendText(method, path, body?.invoke(), auth = true)
                    }
                    e.status == 403 && e.code == "signup_required" -> {
                        signup()
                        sendText(method, path, body?.invoke(), auth = true)
                    }
                    else -> throw e
                }
            }
        }

    suspend fun getJson(path: String) = call("GET", path)

    suspend fun getArray(path: String): JSONArray = try {
        JSONArray(callText("GET", path))
    } catch (e: JSONException) {
        throw ApiException(200, "bad_response", "서버 응답을 읽지 못했어요")
    }

    suspend fun putJson(path: String, json: JSONObject) = call("PUT", path) { json.toString().toRequestBody(JSON) }

    /** 본문 없는 응답(204)도 받는다 */
    suspend fun delete(path: String) {
        callText("DELETE", path)
    }

    suspend fun postJson(path: String, json: JSONObject) = call("POST", path) { json.toString().toRequestBody(JSON) }

    // ---------- 로그인 ----------

    private fun ensureLogin() {
        if (tokens.access == null) login()
    }

    private fun renew() {
        val r = tokens.refresh
        if (r != null) {
            try {
                save(send("POST", "/api/token/refresh", JSONObject().put("refresh", r).body(), auth = false))
                return
            } catch (e: ApiException) {
                if (e.status != 401) throw e
            }
        }
        login()
    }

    private fun login() {
        val name = tokens.devName ?: ("hmtm-" + UUID.randomUUID().toString().take(8)).also { tokens.devName = it }
        val res = send("POST", "/api/auth/dev", JSONObject().put("token", name).body(), auth = false)
        save(res)
        if (res.optJSONObject("user")?.optBoolean("needs_signup") == true) signup()
    }

    private fun signup() {
        var last: ApiException? = null
        repeat(3) { i ->
            val nick = if (i == 0) nickname(tokens.devName) else "차량" + UUID.randomUUID().toString().take(6)
            try {
                send("PUT", "/api/me", JSONObject().put("nickname", nick).put("agree_terms", true).body(), auth = true)
                return
            } catch (e: ApiException) {
                if (e.code != "nickname_taken") throw e
                last = e
            }
        }
        throw last!!
    }

    private fun save(res: JSONObject) {
        tokens.access = res.getString("access")
        tokens.refresh = res.optString("refresh").ifEmpty { null }
    }

    // ---------- 보내기 ----------

    /** 막히는(blocking) 호출. 늘 IO 스레드에서 불리지만, 실수로 메인에서 부르면 바로 멈춘다 */
    private fun send(method: String, path: String, body: RequestBody?, auth: Boolean): JSONObject =
        parseObject(sendText(method, path, body, auth))

    private fun parseObject(text: String): JSONObject = try {
        if (text.isBlank()) JSONObject() else JSONObject(text)
    } catch (e: JSONException) {
        throw ApiException(200, "bad_response", "서버 응답을 읽지 못했어요")
    }

    private fun sendText(method: String, path: String, body: RequestBody?, auth: Boolean): String {
        checkNotMain()
        val b = Request.Builder().url(base + path).method(method, body ?: if (method in BODY_METHODS) EMPTY else null)
        if (auth) tokens.access?.let { b.header("Authorization", "Bearer $it") }
        val resp = try {
            http.newCall(b.build()).execute()
        } catch (e: IOException) {
            throw ApiException(0, ApiException.NETWORK, ApiException.MSG_NETWORK)
        }
        resp.use {
            val text = it.body?.string().orEmpty()
            if (!it.isSuccessful) {
                val json = try {
                    if (text.isBlank()) null else JSONObject(text)
                } catch (e: JSONException) {
                    null
                }
                throw ApiException(
                    it.code,
                    json?.optString("error")?.ifEmpty { null } ?: "http_${it.code}",
                    json?.optString("message")?.ifEmpty { null } ?: "서버 오류가 났어요 (${it.code})",
                )
            }
            return text
        }
    }

    private fun checkNotMain() {
        check(!isMainThread()) { "네트워크 요청을 메인 스레드에서 부르면 안 돼요" }
    }

    private fun JSONObject.body() = toString().toRequestBody(JSON)

    companion object {
        val JSON = "application/json; charset=utf-8".toMediaType()
        private val EMPTY = ByteArray(0).toRequestBody(null)
        private val BODY_METHODS = setOf("POST", "PUT", "PATCH")

        fun defaultHttp(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)   // 한 번 쓰기 기준. 큰 영상도 조각마다 진행하면 끊기지 않음
            .readTimeout(60, TimeUnit.SECONDS)
            .build()

        /** 닉네임 2~12자: dev 이름(hmtm-xxxxxxxx)에서 만든다 */
        fun nickname(devName: String?): String = ("차량" + (devName?.removePrefix("hmtm-") ?: "")).take(12)
    }
}
