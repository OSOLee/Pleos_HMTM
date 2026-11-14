package com.example.hmtm.ui.theme

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow

/**
 * 글자·아이콘 색 짝의 대비 4.5:1 이상 (docs/pleos-design-rules.md 4절), 라이트·다크 모두.
 * 반투명 색(84%, 64%, 버튼 바탕 5%)은 실제 바탕 위에 섞은 색으로 계산한다.
 * 비활성 표시(text/dark/quaternary 32%)는 WCAG 예외라 넣지 않는다.
 */
class ContrastTest {

    /** (이름, 글자·아이콘 색, 바탕 색들). 바탕은 위에서 아래로 겹친 순서 (맨 뒤가 불투명) */
    private data class Pair(val name: String, val fg: Color, val bg: List<Color>)

    private fun pairs(c: HmtmColors): List<Pair> {
        val out = ArrayList<Pair>()
        fun add(name: String, fg: Color, bg: List<Color>) = out.add(Pair(name, fg, bg))
        val plain = listOf("background" to listOf(c.background), "surface" to listOf(c.surface),
            "surfaceHigh" to listOf(c.surfaceHigh), "popup" to listOf(c.popup))
        // 본문·보조·덜 중요한 글자: 모든 바탕, 보조 버튼 바탕 위
        for ((n, bg) in plain) {
            add("text on $n", c.text, bg)
            add("textSecondary on $n", c.textSecondary, bg)
            add("textTertiary on $n", c.textTertiary, bg)
            add("text on basic over $n", c.text, listOf(c.basic) + bg)
            add("text on basicPressed over $n", c.text, listOf(c.basicPressed) + bg)
            add("dangerText on basic over $n", c.dangerText, listOf(c.basic) + bg)
            add("dangerText on basicPressed over $n", c.dangerText, listOf(c.basicPressed) + bg)
        }
        // 강조 숫자·진행 단계 글자
        add("accentText on surface", c.accentText, listOf(c.surface))
        add("accentText on background", c.accentText, listOf(c.background))
        // 오류 글자
        add("dangerText on surface", c.dangerText, listOf(c.surface))
        add("dangerText on popup", c.dangerText, listOf(c.popup))
        // 주의 글자·아이콘 ("정차 후", 임시 결과, 급제동 아이콘)
        add("warningText on surface", c.warningText, listOf(c.surface))
        add("warningText on background", c.warningText, listOf(c.background))
        add("warningText on surfaceHigh", c.warningText, listOf(c.surfaceHigh))
        // 주 버튼·토스트·고른 탭
        add("onFilled on filled", c.onFilled, listOf(c.filled))
        add("onFilled on filledPressed", c.onFilled, listOf(c.filledPressed))
        // 고른 보기
        add("text on selectedBg", c.text, listOf(c.selectedBg))
        // 배지 (4절 배지 표)
        add("vehicle badge", c.vehicleFg, listOf(c.vehicleBg))
        add("video badge", c.videoFg, listOf(c.videoBg))
        add("assumed badge", c.assumedFg, listOf(c.assumedBg))
        add("user badge", c.userFg, listOf(c.userBg))
        // 차량 기록 색 글자 (바뀐 비율, 지난 분석 "기록 입증 시")
        add("vehicleFg on surface", c.vehicleFg, listOf(c.surface))
        add("vehicleFg on surfaceHigh", c.vehicleFg, listOf(c.surfaceHigh))
        // 그래프 지시등 띠 안 글자, 완료 체크 아이콘
        add("thumbnail on active", c.thumbnail, listOf(c.active))
        return out
    }

    @Test
    fun lightPairsMeetAa() = check(HmtmColors.light())

    @Test
    fun darkPairsMeetAa() = check(HmtmColors.dark())

    private fun check(c: HmtmColors) {
        val bad = pairs(c).map { p -> p.name to ratio(p.fg, p.bg) }.filter { it.second < 4.5 }
        assertTrue(
            (if (c.dark) "다크" else "라이트") + " 대비 4.5:1 미만: " +
                bad.joinToString { "${it.first} ${"%.2f".format(it.second)}" },
            bad.isEmpty(),
        )
    }

    @Test
    fun blendingTranslucentText() {
        // #131417 84%를 흰 바탕에 섞으면 #393A3D 안팎
        val mixed = flatten(listOf(Color(0xD6131417), Color.White))
        val argb = mixed.toArgb()
        assertTrue(((argb shr 16) and 0xFF) in 0x36..0x3A)
    }

    companion object {
        /** 위 색부터 차례로 덮은 결과 (맨 뒤는 불투명이어야 함) */
        fun flatten(layers: List<Color>): Color {
            var base = layers.last()
            for (top in layers.dropLast(1).reversed()) base = over(top, base)
            return base
        }

        fun over(top: Color, base: Color): Color {
            val a = top.alpha
            return Color(
                red = top.red * a + base.red * (1 - a),
                green = top.green * a + base.green * (1 - a),
                blue = top.blue * a + base.blue * (1 - a),
                alpha = 1f,
            )
        }

        private fun lin(v: Float): Double = if (v <= 0.03928) v / 12.92 else ((v + 0.055) / 1.055).pow(2.4)

        fun luminance(c: Color): Double = 0.2126 * lin(c.red) + 0.7152 * lin(c.green) + 0.0722 * lin(c.blue)

        /** fg를 bg 겹(위→아래) 위에 섞어 WCAG 대비 */
        fun ratio(fg: Color, bg: List<Color>): Double {
            val back = flatten(bg)
            val front = over(fg, back)
            val a = luminance(front)
            val b = luminance(back)
            return (max(a, b) + 0.05) / (min(a, b) + 0.05)
        }
    }
}
