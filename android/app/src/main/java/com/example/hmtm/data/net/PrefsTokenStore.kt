package com.example.hmtm.data.net

import android.content.Context

/** 앱 저장소(SharedPreferences)에 토큰을 둔다. 기기 안에만 있음 */
class PrefsTokenStore(context: Context) : TokenStore {
    private val prefs = context.applicationContext.getSharedPreferences("auth", Context.MODE_PRIVATE)

    override var access: String?
        get() = prefs.getString("access", null)
        set(v) = prefs.edit().putString("access", v).apply()
    override var refresh: String?
        get() = prefs.getString("refresh", null)
        set(v) = prefs.edit().putString("refresh", v).apply()
    override var devName: String?
        get() = prefs.getString("dev_name", null)
        set(v) = prefs.edit().putString("dev_name", v).apply()
}
