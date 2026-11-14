package com.example.hmtm.ui.record

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.example.hmtm.R
import com.example.hmtm.data.bb.TimelineText
import com.example.hmtm.data.bb.VehicleTimeline
import com.example.hmtm.ui.LocalWide
import com.example.hmtm.ui.components.CardTitle
import com.example.hmtm.ui.components.HighBox
import com.example.hmtm.ui.components.HmtmCard
import com.example.hmtm.ui.components.InfoRow
import com.example.hmtm.ui.components.ScreenHeader
import com.example.hmtm.ui.result.VehicleRows
import com.example.hmtm.ui.result.VehicleSummary
import com.example.hmtm.ui.theme.Hmtm
import com.example.hmtm.ui.theme.HmtmDimens
import com.example.hmtm.ui.theme.HmtmTheme
import kotlin.math.ceil
import kotlin.math.max

/**
 * docs/app-ui.md 2.7 기록 보기: 충돌 전후 차량 기록 그래프 (vehicle_timeline). 정차 중에 보는 화면 (2절).
 * 가로 창: 그래프 3칸 / 요약 2칸. 세로 창: 그래프 → 요약 한 열.
 */
@Composable
fun RecordScreen(timeline: VehicleTimeline, vehicle: VehicleSummary?, onBack: () -> Unit) {
    val c = Hmtm.colors
    val wide = LocalWide.current
    Column(
        Modifier.fillMaxSize().background(c.background).padding(HmtmDimens.screenPadding),
        verticalArrangement = Arrangement.spacedBy(HmtmDimens.cardGap),
    ) {
        ScreenHeader(
            stringResource(R.string.record_title), onBack,
            subtitle = stringResource(R.string.record_subtitle, (-timeline.fromS).toInt(), timeline.toS.toInt()),
        )
        if (wide) {
            Row(Modifier.fillMaxWidth().weight(1f), horizontalArrangement = Arrangement.spacedBy(HmtmDimens.cardGap)) {
                ChartCard(timeline, Modifier.weight(3f).fillMaxHeight(), chart = Modifier.fillMaxWidth().weight(1f))
                SummaryCard(timeline, vehicle, Modifier.weight(2f).fillMaxHeight(), scroll = true)
            }
        } else {
            Column(
                Modifier.fillMaxWidth().weight(1f).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(HmtmDimens.cardGap),
            ) {
                ChartCard(timeline, Modifier.fillMaxWidth(), chart = Modifier.fillMaxWidth().height(520.dp))
                SummaryCard(timeline, vehicle, Modifier.fillMaxWidth(), scroll = false)
            }
        }
    }
}

@Composable
private fun ChartCard(timeline: VehicleTimeline, modifier: Modifier, chart: Modifier) {
    val c = Hmtm.colors
    HmtmCard(modifier) {
        CardTitle(stringResource(R.string.record_chart))
        Spacer(Modifier.height(HmtmDimens.gapSmall))
        Legend()
        Spacer(Modifier.height(HmtmDimens.gapMedium))
        TimelineChart(timeline, chart)
        if (!timeline.aligned) {
            Spacer(Modifier.height(HmtmDimens.gapSmall))
            Text(stringResource(R.string.record_coarse), style = Hmtm.type.label, color = c.warningText)
        }
    }
}

@Composable
private fun SummaryCard(timeline: VehicleTimeline, vehicle: VehicleSummary?, modifier: Modifier, scroll: Boolean) {
    val c = Hmtm.colors
    HmtmCard(modifier) {
        Column(if (scroll) Modifier.weight(1f, fill = false).verticalScroll(rememberScrollState()) else Modifier) {
            CardTitle(stringResource(R.string.record_summary))
            Spacer(Modifier.height(HmtmDimens.gapSmall))
            InfoRow(stringResource(R.string.record_speed), TimelineText.speed(timeline), showDivider = false, stacked = true)
            InfoRow(stringResource(R.string.record_signal), TimelineText.turnSignal(timeline), stacked = true)
            InfoRow(stringResource(R.string.record_brake), TimelineText.brake(timeline), stacked = true)
            if (timeline.gear.isNotEmpty()) {
                InfoRow(stringResource(R.string.record_gear), timeline.gear.joinToString(" → ") { it.label ?: "?" }, stacked = true)
            }
            if (vehicle != null) {
                Spacer(Modifier.height(HmtmDimens.cardGap))
                CardTitle(stringResource(R.string.record_effect))
                vehicle.headline?.let {
                    Spacer(Modifier.height(HmtmDimens.gapSmall))
                    Text(stringResource(R.string.record_if_proven, it), style = Hmtm.type.bodyStrong, color = c.vehicleFg)
                }
                VehicleRows(vehicle)
            }
        }
        Spacer(Modifier.height(HmtmDimens.gapMedium))
        // 참고 자료 안내 (기본 판정은 바뀌지 않음, design-blackbox 4.4)
        HighBox { Text(stringResource(R.string.record_note), style = Hmtm.type.label, color = c.textSecondary) }
    }
}

/** 범례: 색 막대 + 글자 (글자는 본문색이라 대비 걱정 없음) */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Legend() {
    val c = Hmtm.colors
    FlowRow(horizontalArrangement = Arrangement.spacedBy(HmtmDimens.cardGap), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        LegendItem(stringResource(R.string.record_speed), c.accent)
        LegendItem(stringResource(R.string.record_signal_short), c.active)
        LegendItem(stringResource(R.string.record_brake), c.danger)
    }
}

@Composable
private fun LegendItem(label: String, color: Color) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(width = 28.dp, height = 8.dp).clip(RoundedCornerShape(4.dp)).background(color))
        Spacer(Modifier.width(8.dp))
        Text(label, style = Hmtm.type.label, color = Hmtm.colors.text)
    }
}

/** 그래프 눈금: 속도 최댓값을 10km/h 단위로 올림 (최소 20) */
internal fun speedScale(max: Double?): Double = max(20.0, ceil((max ?: 0.0) / 10.0) * 10.0)

/** x 눈금 (5초 간격, 범위 안) */
internal fun timeTicks(from: Double, to: Double): List<Double> {
    val out = ArrayList<Double>()
    var t = ceil(from / 5.0) * 5.0
    while (t <= to + 1e-9) {
        out.add(t); t += 5.0
    }
    return out
}

@Composable
private fun TimelineChart(t: VehicleTimeline, modifier: Modifier) {
    val c = Hmtm.colors
    val measurer = rememberTextMeasurer()
    // 축 글자 Label/Medium (24), 표시 글자 Label/Small (20)
    val label: TextStyle = Hmtm.type.label.copy(color = c.textSecondary)
    val strong: TextStyle = Hmtm.type.label.copy(color = c.dangerText)
    val inLane: TextStyle = Hmtm.type.labelSmall.copy(color = c.thumbnail)
    val empty: TextStyle = Hmtm.type.labelSmall.copy(color = c.textSecondary)
    val sigName = stringResource(R.string.record_signal_short)
    val brakeName = stringResource(R.string.record_brake)
    val sigOff = stringResource(R.string.record_signal_off)
    val brakeOff = stringResource(R.string.record_brake_off)
    val hit = stringResource(R.string.record_hit)
    Canvas(modifier) {
        val left = 120.dp.toPx()
        val right = 16.dp.toPx()
        val top = 40.dp.toPx()
        val lane = 36.dp.toPx()
        val laneGap = 10.dp.toPx()
        val bottom = 40.dp.toPx()
        val plotBottom = size.height - bottom - 2 * (lane + laneGap)
        val w = size.width - left - right
        val span = (t.toS - t.fromS).coerceAtLeast(1.0)
        fun x(s: Double) = left + ((s - t.fromS) / span * w).toFloat()
        val yMax = speedScale(t.speedMax)
        fun y(v: Double) = plotBottom - ((v / yMax) * (plotBottom - top)).toFloat()

        // 기록 빈 곳
        t.gaps.forEach { g ->
            drawRect(c.surfaceHigh, Offset(x(g.from), top), Size(x(g.to) - x(g.from), plotBottom - top))
        }
        // 속도 눈금
        val step = if (yMax > 60) 20.0 else 10.0
        var v = 0.0
        while (v <= yMax + 1e-9) {
            drawLine(c.divider, Offset(left, y(v)), Offset(left + w, y(v)), strokeWidth = 1.dp.toPx())
            text(measurer, "${v.toInt()}", label, Offset(left - 12.dp.toPx(), y(v)), alignEnd = true)
            v += step
        }
        text(measurer, "km/h", label, Offset(left - 12.dp.toPx(), top - 24.dp.toPx()), alignEnd = true)
        // 시각 눈금
        timeTicks(t.fromS, t.toS).forEach { s ->
            text(measurer, if (s == 0.0) "0초" else "${s.toInt()}초", label,
                Offset(x(s), size.height - bottom / 2), center = true)
        }
        // 속도 꺾은선 (기록 없는 점에서 끊음)
        val path = Path()
        var pen = false
        t.speed.forEach { (s, kmh) ->
            if (kmh == null) {
                pen = false
            } else if (!pen) {
                path.moveTo(x(s), y(kmh)); pen = true
            } else {
                path.lineTo(x(s), y(kmh))
            }
        }
        drawPath(path, c.accent, style = Stroke(4.dp.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round))
        // 지시등·브레이크 띠. 비었으면 "켜지 않음"·"밟지 않음"
        val laneTop1 = plotBottom + laneGap
        val laneTop2 = laneTop1 + lane + laneGap
        drawLane(measurer, sigName, label, laneTop1, lane, left, w, c.surfaceHigh)
        drawLane(measurer, brakeName, label, laneTop2, lane, left, w, c.surfaceHigh)
        if (t.turnSignal.isEmpty()) text(measurer, sigOff, empty, Offset(left + 12.dp.toPx(), laneTop1 + lane / 2))
        if (t.brake.isEmpty()) text(measurer, brakeOff, empty, Offset(left + 12.dp.toPx(), laneTop2 + lane / 2))
        t.turnSignal.forEach { s ->
            val x0 = x(s.from); val x1 = x(s.to)
            drawRoundRect(c.active, Offset(x0, laneTop1), Size(max(x1 - x0, 2f), lane), CornerRadius(6.dp.toPx()))
            text(measurer, TimelineText.dir(s.label), inLane, Offset(x0 + 8.dp.toPx(), laneTop1 + lane / 2))
        }
        t.brake.forEach { s ->
            val x0 = x(s.from); val x1 = x(s.to)
            drawRoundRect(c.danger, Offset(x0, laneTop2), Size(max(x1 - x0, 2f), lane), CornerRadius(6.dp.toPx()))
        }
        // 부딪힌 순간
        val xc = x(0.0)
        drawLine(c.danger, Offset(xc, top), Offset(xc, laneTop2 + lane), strokeWidth = 3.dp.toPx(),
            pathEffect = PathEffect.dashPathEffect(floatArrayOf(10.dp.toPx(), 8.dp.toPx())))
        text(measurer, hit, strong, Offset(xc, top - 24.dp.toPx()), center = true)
    }
}

private fun DrawScope.drawLane(m: TextMeasurer, name: String, style: TextStyle, top: Float, h: Float, left: Float, w: Float,
                               bg: Color) {
    drawRoundRect(bg, Offset(left, top), Size(w, h), CornerRadius(6.dp.toPx()))
    text(m, name, style, Offset(left - 12.dp.toPx(), top + h / 2), alignEnd = true)
}

/** 글자: 기본은 왼쪽·세로 가운데, alignEnd면 오른쪽 끝을, center면 가운데를 at에 */
private fun DrawScope.text(
    m: TextMeasurer, s: String, style: TextStyle, at: Offset, alignEnd: Boolean = false, center: Boolean = false,
) {
    val r = m.measure(s, style)
    val x = when {
        alignEnd -> at.x - r.size.width
        center -> at.x - r.size.width / 2
        else -> at.x
    }
    drawText(r, topLeft = Offset(x, at.y - r.size.height / 2))
}

@Preview(widthDp = 1682, heightDp = 1210)
@Composable
private fun RecordPreview() {
    val speed = (0..100).map { i ->
        val s = -15.0 + i * 0.2
        s to (if (s < 0) 40.0 - max(0.0, s + 4) * 4 else 0.0)
    }
    HmtmTheme(darkTheme = false) {
        RecordScreen(
            VehicleTimeline(
                -15.0, 5.0, speed, 40.0,
                emptyList(), listOf(VehicleTimeline.Span(-1.2, 5.0)),
                listOf(VehicleTimeline.Span(-15.0, 5.0, "D")), emptyList(), "fine", true, 0L,
            ),
            VehicleSummary(null, "차량 기록은 이 사고의 과실에 영향을 주지 않아요", emptyList(), true),
            onBack = {},
        )
    }
}
