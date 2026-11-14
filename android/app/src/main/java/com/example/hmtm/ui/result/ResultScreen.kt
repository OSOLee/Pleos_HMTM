package com.example.hmtm.ui.result

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.example.hmtm.R
import com.example.hmtm.data.bb.BbCase
import com.example.hmtm.data.bb.CollisionReview
import com.example.hmtm.data.bb.VehicleEffect
import com.example.hmtm.ui.Format
import com.example.hmtm.ui.LocalWide
import com.example.hmtm.ui.components.Badge
import com.example.hmtm.ui.components.BadgeTone
import com.example.hmtm.ui.components.ButtonKind
import com.example.hmtm.ui.components.ButtonSize
import com.example.hmtm.ui.components.CardTitle
import com.example.hmtm.ui.components.HighBox
import com.example.hmtm.ui.components.HmtmButton
import com.example.hmtm.ui.components.HmtmCard
import com.example.hmtm.ui.components.HmtmIcons
import com.example.hmtm.ui.components.IconSize
import com.example.hmtm.ui.components.ListRow
import com.example.hmtm.ui.components.ScreenHeader
import com.example.hmtm.ui.components.Source
import com.example.hmtm.ui.components.SourceBadge
import com.example.hmtm.ui.theme.Hmtm
import com.example.hmtm.ui.theme.HmtmDimens
import com.example.hmtm.ui.theme.HmtmTheme

/**
 * docs/app-ui.md 2.5 결과. 숫자·근거 문장·남은 질문 수는 서버 값 그대로 (design-blackbox 3.6).
 * 가로 창: 왼쪽 열 = 과실비율 + 차량 기록 카드, 오른쪽 열 = 판단 근거 (전체 높이, 넘치면 스크롤).
 * 세로 창: 과실비율 → 차량 기록 → 판단 근거(접힘) 한 열.
 * 콜백이 null이면 그 버튼을 끈다.
 */
@Composable
fun ResultScreen(
    case: BbCase,
    onBack: () -> Unit,
    onReplay: (() -> Unit)?,
    onAnswer: (() -> Unit)? = null,
    onWrongCls: (() -> Unit)? = null,
    onEdit: (() -> Unit)? = null,
    onDelete: (() -> Unit)? = null,
    onRecord: (() -> Unit)? = null,
    onPick: (() -> Unit)? = null,
) {
    val c = Hmtm.colors
    val wide = LocalWide.current
    val review = case.review?.takeIf { it.needed }
    val vehicle = vehicleSummary(case)
    val notices = notices(case)
    Column(
        Modifier.fillMaxSize().background(c.background).padding(HmtmDimens.screenPadding),
        verticalArrangement = Arrangement.spacedBy(HmtmDimens.cardGap),
    ) {
        ScreenHeader(
            stringResource(R.string.result_title), onBack,
            subtitle = case.accidentAt?.let { stringResource(R.string.result_subtitle, Format.dayTime(it)) },
        )
        if (wide) {
            Row(Modifier.fillMaxWidth().weight(1f), horizontalArrangement = Arrangement.spacedBy(HmtmDimens.cardGap)) {
                Column(
                    Modifier.weight(1f).fillMaxHeight().verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(HmtmDimens.cardGap),
                ) {
                    if (review != null) PickCard(review, onPick, Modifier.fillMaxWidth())
                    FaultCard(case, onAnswer, onWrongCls, Modifier.fillMaxWidth())
                    if (notices.isNotEmpty()) NoticeCard(notices, Modifier.fillMaxWidth())
                    if (vehicle != null) VehicleCard(vehicle, onRecord, Modifier.fillMaxWidth())
                }
                EvidenceCard(case, Modifier.weight(1f).fillMaxHeight())
            }
            Actions(onReplay, onEdit, onDelete)
        } else {
            Column(
                Modifier.fillMaxWidth().weight(1f).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(HmtmDimens.cardGap),
            ) {
                if (review != null) PickCard(review, onPick, Modifier.fillMaxWidth())
                FaultCard(case, onAnswer, onWrongCls, Modifier.fillMaxWidth())
                if (notices.isNotEmpty()) NoticeCard(notices, Modifier.fillMaxWidth())
                if (vehicle != null) VehicleCard(vehicle, onRecord, Modifier.fillMaxWidth())
                EvidenceFolded(case, Modifier.fillMaxWidth())
                Actions(onReplay, onEdit, onDelete)
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Actions(onReplay: (() -> Unit)?, onEdit: (() -> Unit)?, onDelete: (() -> Unit)?) {
    FlowRow(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(HmtmDimens.gapMedium),
        verticalArrangement = Arrangement.spacedBy(HmtmDimens.gapMedium),
    ) {
        // 최소 폭: 1:1 분할 창(약 840dp)에서 세 개가 한 줄에 끼면 글자가 두 줄로 꺾여 → 넘치면 줄바꿈 (2 + 1)
        val m = Modifier.widthIn(min = 300.dp).weight(1f)
        HmtmButton(stringResource(R.string.result_replay), { onReplay?.invoke() }, m,
            enabled = onReplay != null, icon = HmtmIcons.Video)
        HmtmButton(stringResource(R.string.result_edit), { onEdit?.invoke() }, m,
            enabled = onEdit != null, icon = HmtmIcons.Edit)
        HmtmButton(stringResource(R.string.result_delete), { onDelete?.invoke() }, m,
            enabled = onDelete != null, kind = ButtonKind.Danger, icon = HmtmIcons.Trash)
    }
}

@Composable
private fun FaultCard(case: BbCase, onAnswer: (() -> Unit)?, onWrongCls: (() -> Unit)?, modifier: Modifier) {
    val c = Hmtm.colors
    val r = case.result
    HmtmCard(modifier) {
        Text(stringResource(R.string.result_fault), style = Hmtm.type.cardTitle, color = c.text)
        val provisional = case.remainingCount > 0 || r?.provisional == true
        if (provisional) {
            Spacer(Modifier.height(HmtmDimens.gapMedium))
            // 임시 결과 표시 바로 옆에 "질문 N개 답하기" (남은 질문을 답하면 결과가 정해짐)
            ProvisionalRow(case.remainingCount, onAnswer)
        }
        Spacer(Modifier.height(HmtmDimens.gapMedium))
        val ego = r?.egoFault
        val other = r?.otherFault
        if (r != null && ego != null && other != null) {
            val d = r.display
            if (d != null && d.pedestrianOnly) {
                // 차대보행자: 인정기준이 보행자 과실만 정함 → 서버 표기 그대로 크게
                Text(d.text, style = Hmtm.type.headline, color = c.accentText)
            } else {
                Row(verticalAlignment = Alignment.Bottom) {
                    Party(stringResource(R.string.party_me), ego, c.accentText)
                    Text(" : ", style = Hmtm.type.headline, color = c.textSecondary)
                    Party(stringResource(R.string.party_other), other, c.text)
                }
            }
            Spacer(Modifier.height(HmtmDimens.gapSmall))
            FaultBar(ego, other)
            if (d?.note != null) {
                Spacer(Modifier.height(HmtmDimens.gapSmall))
                Text(d.note, style = Hmtm.type.label, color = c.textSecondary)
            }
            Spacer(Modifier.height(HmtmDimens.gapMedium))
            HighBox {
                Text(stringResource(R.string.result_rule), style = Hmtm.type.label, color = c.textSecondary)
                Text(listOfNotNull(r.ruleId, r.title).joinToString(" · "), style = Hmtm.type.bodyBold, color = c.text)
            }
        } else {
            Text(stringResource(R.string.result_undecided), style = Hmtm.type.cardTitle, color = c.text)
            Spacer(Modifier.height(HmtmDimens.gapSmall))
            Text(
                // 사고 순간을 못 찾은 사건(no_collision)은 서버 안내 ("영상에서 사고 순간을 찾지 못했어요…")
                (if (r == null) case.analysis?.message else null) ?: r?.notice ?: stringResource(
                    if (case.remainingCount > 0) R.string.result_undecided_more else R.string.result_undecided_none,
                ),
                style = Hmtm.type.body, color = c.textSecondary,
            )
        }
        val otherCls = case.otherCls
        if (otherCls != null && otherCls.askable && onWrongCls != null) {
            Spacer(Modifier.height(HmtmDimens.gapMedium))
            HmtmButton(Format.notOtherCls(otherCls.label!!), onWrongCls, size = ButtonSize.Small)
        }
        Spacer(Modifier.height(HmtmDimens.gapMedium))
        Text(stringResource(R.string.result_disclaimer), style = Hmtm.type.label, color = c.textSecondary)
    }
}

/** "임시 결과 · 질문 N개 남음" 배지 + "질문 N개 답하기" */
@Composable
private fun ProvisionalRow(remaining: Int, onAnswer: (() -> Unit)?) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        ProvisionalPill(remaining, Modifier.weight(1f, fill = false))
        if (remaining > 0 && onAnswer != null) {
            Spacer(Modifier.width(HmtmDimens.gapMedium))
            HmtmButton(
                stringResource(R.string.result_answer, remaining), onAnswer,
                size = ButtonSize.Small, kind = ButtonKind.Filled,
            )
        }
    }
}

@Composable
fun ProvisionalPill(remaining: Int, modifier: Modifier = Modifier) {
    Badge(
        if (remaining > 0) stringResource(R.string.provisional_n, remaining) else stringResource(R.string.provisional),
        BadgeTone.Assumed, modifier,
    )
}

@Composable
private fun Party(label: String, value: Int, color: Color) {
    Column {
        Text(label, style = Hmtm.type.label, color = Hmtm.colors.textSecondary)
        Text("$value", style = Hmtm.type.headline, color = color)
    }
}

@Composable
private fun FaultBar(ego: Int, other: Int) {
    val c = Hmtm.colors
    val total = (ego + other).coerceAtLeast(1)
    Row(Modifier.fillMaxWidth().height(16.dp).clip(RoundedCornerShape(8.dp)).background(c.divider)) {
        if (ego > 0) Box(Modifier.weight(ego.toFloat() / total).fillMaxHeight().background(c.accent))
        if (other > 0) Box(Modifier.weight(other.toFloat() / total).fillMaxHeight().background(c.otherParty))
    }
}

/**
 * "사고 순간 확인 필요" 카드 (design-blackbox 3.6 collision_review). 서버 안내 문장, 고른 순간으로도 판정 못 했으면(last_pick) 그 안내,
 * 고를 수 있으면 기한과 "사고 순간 고르기", 기한이 지났으면(expired) 다시 올리라는 안내
 */
@Composable
private fun PickCard(review: CollisionReview, onPick: (() -> Unit)?, modifier: Modifier) {
    val c = Hmtm.colors
    HmtmCard(modifier) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(HmtmIcons.Warning, null, Modifier.size(IconSize.Medium), tint = c.assumedFg)
            Spacer(Modifier.width(HmtmDimens.gapSmall))
            CardTitle(stringResource(R.string.pick_card_title), Modifier.weight(1f))
        }
        review.message?.let {
            Spacer(Modifier.height(HmtmDimens.gapSmall))
            Text(it, style = Hmtm.type.body, color = c.text)
        }
        review.lastPick?.let { last ->
            Spacer(Modifier.height(HmtmDimens.gapMedium))
            Column(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(HmtmDimens.rowRadius)).background(c.assumedBg)
                    .padding(horizontal = HmtmDimens.rowPadH, vertical = HmtmDimens.rowPadV),
            ) {
                Text(stringResource(R.string.pick_last_failed, Format.seconds(last.t)), style = Hmtm.type.bodyBold, color = c.assumedFg)
                last.message?.let { Text(it, style = Hmtm.type.label, color = c.assumedFg) }
                if (review.canPick) Text(stringResource(R.string.pick_last_again), style = Hmtm.type.label, color = c.assumedFg)
            }
        }
        Spacer(Modifier.height(HmtmDimens.gapMedium))
        when {
            review.canPick -> {
                review.pickUntil?.let {
                    Text(stringResource(R.string.pick_until, Format.dayTime(it)), style = Hmtm.type.label, color = c.textSecondary)
                    Spacer(Modifier.height(HmtmDimens.gapMedium))
                }
                HmtmButton(
                    stringResource(R.string.pick_open), { onPick?.invoke() }, Modifier.fillMaxWidth(),
                    kind = ButtonKind.Filled, icon = HmtmIcons.Target, enabled = onPick != null,
                )
            }
            review.expired -> Text(stringResource(R.string.pick_expired), style = Hmtm.type.bodyBold, color = c.warningText)
            else -> Text(stringResource(R.string.pick_cannot), style = Hmtm.type.body, color = c.textSecondary)
        }
    }
}

/** 결과 화면 안내 한 줄: 짧은 제목(문구 리소스) + 서버 문장 */
data class Notice(val title: Int, val text: String)

/**
 * 확인해 달라는 안내 (docs/app-ui.md 2.5 "확인해 주세요"). 판정은 바꾸지 않는 경고.
 *  - 시계 경고(clock_warnings): 영상 촬영 시각 / 차량 기록 시각이 서버 시각과 하루 넘게 다름
 *  - 올린 차량 기록을 시각이 안 맞아 쓰지 않음(vehicle_clock_mismatch 등): "차량 기록 없음" 대신 서버 이유 문장
 */
internal fun notices(case: BbCase): List<Notice> {
    val out = case.clockWarnings.map {
        Notice(if (it.video) R.string.notice_video_clock else R.string.notice_vehicle_clock, it.message)
    }.toMutableList()
    case.vehicleUnusedText?.let { out.add(Notice(R.string.notice_vehicle_unused, it)) }
    return out
}

@Composable
private fun NoticeCard(items: List<Notice>, modifier: Modifier) {
    val c = Hmtm.colors
    HmtmCard(modifier) {
        CardTitle(stringResource(R.string.notice_title))
        items.forEach { n ->
            Spacer(Modifier.height(HmtmDimens.gapMedium))
            Column(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(HmtmDimens.rowRadius)).background(c.assumedBg)
                    .padding(horizontal = HmtmDimens.rowPadH, vertical = HmtmDimens.rowPadV),
            ) {
                Text(stringResource(n.title), style = Hmtm.type.bodyBold, color = c.assumedFg)
                Text(n.text, style = Hmtm.type.label, color = c.assumedFg)
            }
        }
    }
}

/** "차량 기록을 입증할 수 있으면" 카드 내용 (docs/app-ui.md 2.5). 차량 기록이 없으면 null */
data class VehicleSummary(
    /** 바뀐 비율 ("내 차 70 : 상대 30"). 바뀌지 않으면 null */
    val headline: String?,
    /** 한 줄 안내 (영향 없음, 시각을 대략만 맞춤) */
    val message: String?,
    val rows: List<Row>,
    val canOpenRecord: Boolean,
) {
    /**
     * badge: "내 차 과실 +10" / "반영 안 함", text: 서버 요약 문장, sub: 차량 규칙 문장이나 정확히 맞았다면의 비율.
     * tone: 내 과실 증가 = 주황(Assumed), 감소 = 초록(Video), 기준이 바뀜 = 차량 기록, 반영 안 함 = 주황
     */
    data class Row(
        val badge: String, val text: String, val sub: String?, val applied: Boolean, val tone: BadgeTone,
        /** 아이콘 방식 배지의 아이콘: 내 과실 증가 ↑, 감소 ↓, 기준이 바뀜 ⇄, 반영 안 함 ? */
        val icon: ImageVector? = null,
    )
}

/** 효과 배지 아이콘 (아이콘 방식): 내 과실 증가 ↑, 감소 ↓, 그 밖 ⇄ */
internal fun effectIcon(e: VehicleEffect): ImageVector = when (effectTone(e)) {
    BadgeTone.Assumed -> HmtmIcons.Up
    BadgeTone.Video -> HmtmIcons.Down
    else -> HmtmIcons.Swap
}

/** 효과 배지 색: 내 과실 증가 주황, 감소 초록, 그 밖(기준이 바뀜) 차량 기록 색 */
internal fun effectTone(e: VehicleEffect): BadgeTone = when {
    e.egoDelta != null && e.egoDelta > 0 && e.direction != VehicleEffect.CHANGED -> BadgeTone.Assumed
    e.egoDelta != null && e.egoDelta < 0 && e.direction != VehicleEffect.CHANGED -> BadgeTone.Video
    else -> BadgeTone.Vehicle
}

internal fun vehicleSummary(case: BbCase): VehicleSummary? {
    val w = case.resultWithVehicle
    if (w == null && case.timeline == null) return null
    val applied = case.appliedEffects
    val skipped = case.vehicleEffects.filterNot { it.applied }
    val rows = applied.map { VehicleSummary.Row(it.deltaText, it.summary, it.text, true, effectTone(it), effectIcon(it)) } +
        skipped.map { e ->
            VehicleSummary.Row(
                "반영 안 함", e.summary,
                e.ifApplied?.let { (ego, other) -> "시각이 정확히 맞으면 내 차 $ego : 상대 $other" }, false, BadgeTone.Assumed,
            )
        }
    val headline = if (applied.isEmpty() || w == null) null else verdictText(w)
    val message = when {
        applied.isNotEmpty() -> null
        skipped.isNotEmpty() -> skipped.first().reasonText ?: "차량 기록 시각을 정확히 맞추지 못해 결과에 넣지 않았어요"
        else -> NO_EFFECT
    }
    return VehicleSummary(headline, message, rows, case.timeline != null)
}

const val NO_EFFECT = "차량 기록은 이 사고의 과실에 영향을 주지 않아요"

/** 판정을 한 줄로: 서버 비율 표기 > "내 차 a : 상대 b" > 기준 없음 */
internal fun verdictText(v: BbCase.Verdict): String = v.display?.text
    ?: if (v.egoFault != null && v.otherFault != null) "내 차 ${v.egoFault} : 상대 ${v.otherFault}"
    else "맞는 기준을 찾지 못함"

@Composable
private fun VehicleCard(s: VehicleSummary, onRecord: (() -> Unit)?, modifier: Modifier) {
    val c = Hmtm.colors
    HmtmCard(modifier) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            CardTitle(stringResource(R.string.vehicle_card_title), Modifier.weight(1f))
            if (s.canOpenRecord) {
                Spacer(Modifier.width(HmtmDimens.gapMedium))
                HmtmButton(stringResource(R.string.vehicle_open_record), { onRecord?.invoke() },
                    enabled = onRecord != null, icon = HmtmIcons.Chart, size = ButtonSize.Small)
            }
        }
        if (s.headline != null) {
            Spacer(Modifier.height(HmtmDimens.gapSmall))
            Text(s.headline, style = Hmtm.type.cardTitle, color = c.vehicleFg)
        }
        VehicleRows(s)
    }
}

/** 안내 문장 + 효과 행 (결과 화면 카드와 기록 보기 화면이 같이 씀) */
@Composable
fun ColumnScope.VehicleRows(s: VehicleSummary) {
    val c = Hmtm.colors
    if (s.message != null) {
        Spacer(Modifier.height(HmtmDimens.gapSmall))
        Text(s.message, style = Hmtm.type.body, color = c.textSecondary)
    }
    s.rows.take(3).forEach { r ->
        Spacer(Modifier.height(HmtmDimens.gapMedium))
        Column {
            Badge(r.badge, r.tone, icon = r.icon)
            Spacer(Modifier.height(8.dp))
            Text(r.text, style = Hmtm.type.bodyBold, color = c.text)
            if (r.sub != null) Text(r.sub, style = Hmtm.type.label, color = c.textSecondary)
        }
    }
}

@Composable
private fun EvidenceCard(case: BbCase, modifier: Modifier) {
    val c = Hmtm.colors
    HmtmCard(modifier) {
        CardTitle(stringResource(R.string.evidence_title))
        Spacer(Modifier.height(HmtmDimens.gapMedium))
        if (case.evidence.isEmpty()) {
            Text(stringResource(R.string.evidence_empty), style = Hmtm.type.body, color = c.textSecondary)
        }
        // 넘치면 카드 안에서 스크롤 (카드는 오른쪽 열 전체 높이)
        LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(HmtmDimens.gapSmall)) {
            items(case.evidence, key = { it.field }) { e -> EvidenceRow(e) }
        }
    }
}

/** 세로 창: 접힌 상태로 시작, "근거 N개 보기" */
@Composable
private fun EvidenceFolded(case: BbCase, modifier: Modifier) {
    val c = Hmtm.colors
    var open by rememberSaveable { mutableStateOf(false) }
    HmtmCard(modifier) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            CardTitle(stringResource(R.string.evidence_title), Modifier.weight(1f))
            if (case.evidence.isNotEmpty()) {
                HmtmButton(
                    stringResource(if (open) R.string.evidence_fold else R.string.evidence_show, case.evidence.size),
                    { open = !open }, size = ButtonSize.Small,
                )
            }
        }
        if (case.evidence.isEmpty()) {
            Spacer(Modifier.height(HmtmDimens.gapMedium))
            Text(stringResource(R.string.evidence_empty), style = Hmtm.type.body, color = c.textSecondary)
        }
        if (open) {
            Spacer(Modifier.height(HmtmDimens.gapMedium))
            Column(verticalArrangement = Arrangement.spacedBy(HmtmDimens.gapSmall)) {
                case.evidence.forEach { EvidenceRow(it) }
            }
        }
    }
}

@Composable
private fun EvidenceRow(e: BbCase.Evidence) {
    val c = Hmtm.colors
    val src = Source.of(e.source)
    ListRow {
        Column(Modifier.weight(1f)) {
            SourceBadge(src)
            Spacer(Modifier.height(8.dp))
            Text(e.text, style = Hmtm.type.body, color = c.text)
            if (src.assumed) {
                Text(stringResource(R.string.evidence_may_change), style = Hmtm.type.label, color = c.warningText)
            }
        }
    }
}

@Preview(widthDp = 1682, heightDp = 1210)
@Composable
private fun ResultPreview() {
    HmtmTheme(darkTheme = false) {
        ResultScreen(
            BbCase(
                id = "x", status = "needs_answers", progress = 100, createdAt = System.currentTimeMillis(),
                analysis = null,
                result = BbCase.Verdict(
                    "ok", true, "차13-1", "오른쪽 우회전 대 왼쪽 직진 (동일폭)", 60, 40, null, "car_car",
                    BbCase.FaultDisplay("ratio", "내 차 60 : 상대 40", null),
                ),
                evidence = listOf(
                    BbCase.Evidence("a", "vehicle_info", "내 차는 승용차였어요 (차량 정보)"),
                    BbCase.Evidence("b", "video", "내 차가 우회전했어요 (5.8초)"),
                    BbCase.Evidence("c", "guess", "교차로에 신호등이 없었어요 (영상 추정)"),
                ),
                remaining = emptyList(), remainingCount = 2, userAnswers = emptyMap(),
                vehicleRecord = true, syncGrade = "fine",
                otherCls = BbCase.OtherCls("car", "승용차", "video", "car_car", listOf("car"), listOf("승용차")),
                collisionT = 18.2, startMs = null,
                resultWithVehicle = BbCase.Verdict(
                    "ok", true, "차16-1", null, 70, 30, null, "car_car",
                    BbCase.FaultDisplay("ratio", "내 차 70 : 상대 30", null),
                ),
                vehicleEffects = listOf(
                    VehicleEffect(
                        "parties.ego.turn_signal_used", "방향지시등", "안 켬", "내 차가 방향지시등을 켜지 않았어요",
                        "사고 전 10초 동안 왼쪽 지시등을 켜지 않았어요", true, null, 10, VehicleEffect.EGO_MORE, null,
                    ),
                ),
            ),
            onBack = {}, onReplay = {}, onAnswer = {}, onWrongCls = {}, onEdit = {}, onDelete = {}, onRecord = {},
        )
    }
}
