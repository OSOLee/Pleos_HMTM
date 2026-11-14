package com.example.hmtm.ui.questions

import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import com.example.hmtm.ui.theme.Hmtm
import kotlin.math.min

/**
 * 질문 그림 (docs/app-ui.md 2.4): 교차로를 위에서 본 모습, 내 차는 강조색으로 아래에서 진입.
 * otherFrom(상대가 온 길: left/right/opposite/same) 쪽에 상대를 그린다. 보행자 장 질문이면 횡단보도와 보행자.
 * crossing이 거짓이면(사고 장소가 교차로 아닌 길) 가로 길을 그리지 않는다.
 */
@Composable
fun QuestionPicture(
    otherFrom: Any?,
    pedestrian: Boolean,
    crossing: Boolean,
    modifier: Modifier = Modifier,
) {
    val c = Hmtm.colors
    // basic/200 (라이트 #E0E1E6, 다크 #44464E)
    val road = if (c.dark) Color(0xFF44464E) else Color(0xFFE0E1E6)
    val line = c.surface
    Canvas(modifier) {
        val s = min(size.width, size.height)
        val o = Offset((size.width - s) / 2, (size.height - s) / 2)
        val w = s * 0.30f                      // 도로 폭
        val mid = o + Offset(s / 2, s / 2)
        // 세로 길
        drawRect(road, Offset(mid.x - w / 2, o.y), Size(w, s))
        // 가로 길 (교차로가 아닌 질문이면 생략)
        if (crossing) drawRect(road, Offset(o.x, mid.y - w / 2), Size(s, w))
        val dash = PathEffect.dashPathEffect(floatArrayOf(s * 0.03f, s * 0.025f))
        drawLine(line, Offset(mid.x, o.y), Offset(mid.x, if (crossing) mid.y - w / 2 else o.y + s), 3f, pathEffect = dash)
        drawLine(line, Offset(mid.x, mid.y + w / 2), Offset(mid.x, o.y + s), 3f, pathEffect = dash)
        if (crossing) {
            drawLine(line, Offset(o.x, mid.y), Offset(mid.x - w / 2, mid.y), 3f, pathEffect = dash)
            drawLine(line, Offset(mid.x + w / 2, mid.y), Offset(o.x + s, mid.y), 3f, pathEffect = dash)
        }
        if (pedestrian) crosswalk(mid, w, s, line)

        // 내 차: 아래에서 위로 (오른쪽 차로)
        car(Offset(mid.x + w / 4, mid.y + w * 0.95f), s, c.accent, 0f)

        // 상대
        val other = c.otherParty
        if (pedestrian) {
            drawCircle(other, s * 0.03f, Offset(mid.x - w * 0.1f, mid.y - w * 0.62f))
        } else {
            when (otherFrom) {
                "left" -> car(Offset(mid.x - w * 1.0f, mid.y + w / 4), s, other, 90f)
                "right" -> car(Offset(mid.x + w * 1.0f, mid.y - w / 4), s, other, -90f)
                "opposite" -> car(Offset(mid.x - w / 4, mid.y - w * 0.95f), s, other, 180f)
                "same" -> car(Offset(mid.x + w / 4, mid.y - w * 0.15f), s, other, 0f)
                else -> Unit
            }
        }
        // 테두리
        drawRoundRect(c.divider, o, Size(s, s), CornerRadius(s * 0.04f), style = Stroke(2f))
    }
}

/** 차 한 대 (위에서 본 둥근 사각형 + 앞 유리). angle 0 = 위쪽으로 달림 */
private fun DrawScope.car(center: Offset, s: Float, color: Color, angle: Float) {
    val cw = s * 0.075f
    val ch = s * 0.13f
    rotate(angle, center) {
        drawRoundRect(color, Offset(center.x - cw / 2, center.y - ch / 2), Size(cw, ch), CornerRadius(cw * 0.3f))
        drawRoundRect(
            Color.White.copy(alpha = 0.7f), Offset(center.x - cw * 0.35f, center.y - ch * 0.32f),
            Size(cw * 0.7f, ch * 0.18f), CornerRadius(cw * 0.1f),
        )
    }
}

/** 교차로 위쪽 횡단보도 */
private fun DrawScope.crosswalk(mid: Offset, w: Float, s: Float, color: Color) {
    val y = mid.y - w * 0.62f
    val n = 6
    val stripe = w / (n * 2f)
    for (i in 0 until n) {
        drawRect(color, Offset(mid.x - w / 2 + stripe * (2 * i + 0.5f), y - s * 0.04f), Size(stripe, s * 0.08f))
    }
}
