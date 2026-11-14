package com.example.hmtm.ui

import androidx.compose.runtime.staticCompositionLocalOf

/**
 * 가로 창(true) / 세로 창(false). 기기 회전이 아니라 **앱 창 크기**로 정한다 (docs/pleos-design-rules.md 1절).
 * Pleos는 앱 창을 1개 또는 2개로 나눠 보여 주므로 같은 화면에서도 창이 세로로 좁아질 수 있다.
 */
val LocalWide = staticCompositionLocalOf { true }

object WindowShape {
    /** 폭이 높이보다 크고 2열 카드가 들어갈 만큼 넓으면 가로 배치 */
    const val MIN_WIDE_DP = 1000f

    fun isWide(widthDp: Float, heightDp: Float): Boolean = widthDp >= heightDp && widthDp >= MIN_WIDE_DP
}
