package com.example.hmtm.ui.questions

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.example.hmtm.R
import com.example.hmtm.data.bb.Page
import com.example.hmtm.data.bb.Question
import com.example.hmtm.data.bb.QuestionSession
import com.example.hmtm.data.bb.VehicleHint
import com.example.hmtm.ui.LocalWide
import com.example.hmtm.ui.components.Badge
import com.example.hmtm.ui.components.BadgeTone
import com.example.hmtm.ui.components.ButtonKind
import com.example.hmtm.ui.components.ButtonSize
import com.example.hmtm.ui.components.HmtmButton
import com.example.hmtm.ui.components.HmtmCard
import com.example.hmtm.ui.components.HmtmIconButton
import com.example.hmtm.ui.components.HmtmIcons
import com.example.hmtm.ui.components.IconSize
import com.example.hmtm.ui.components.tap
import com.example.hmtm.ui.theme.Hmtm
import com.example.hmtm.ui.theme.HmtmDimens
import com.example.hmtm.ui.theme.HmtmTheme

/** 질문 화면 상태: 세션 + 보내는 중·기다리는 중·오류 */
data class QuestionUi(
    val session: QuestionSession,
    val pedestrian: Boolean = false,
    val sending: Boolean = false,
    /** 409 분석 중: "잠시 뒤 다시 보낼게요" */
    val waiting: String? = null,
    val error: String? = null,
    /** 답을 보낸 뒤 새로 생긴 질문을 이어서 물을지 (상대 종류 하나만 고치는 화면은 결과로 바로) */
    val followUps: Boolean = true,
    /** 이 흐름에서 이미 보인 질문 키 (이어지는 질문에서 다시 묻지 않음) */
    val asked: Set<String> = session.questions.map { it.field }.toSet(),
)

/**
 * docs/app-ui.md 2.4 질문. 보기·추정값은 서버 질문 그대로.
 * 가로 창: 그림 / 보기 2열. 세로 창: 질문 → 보기(2×2, 높이 유지) → 추정 근거·차량 기록 참고 (그림 생략).
 */
@Composable
fun QuestionScreen(
    ui: QuestionUi,
    driving: Boolean,
    onBack: () -> Unit,
    onPick: (Any?) -> Unit,
    onDontKnow: () -> Unit,
    onNext: () -> Unit,
    onRetry: () -> Unit,
    onToggle: (String, Any?) -> Unit = { _, _ -> },
    onBundleNone: () -> Unit = {},
) {
    val c = Hmtm.colors
    val wide = LocalWide.current
    val s = ui.session
    val q = s.current
    val page = s.page
    Column(
        Modifier.fillMaxSize().background(c.background).padding(HmtmDimens.screenPadding),
        verticalArrangement = Arrangement.spacedBy(HmtmDimens.cardGap),
    ) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            HmtmIconButton(HmtmIcons.Back, stringResource(R.string.back), onBack)
            Spacer(Modifier.width(HmtmDimens.headerGap))
            Column(Modifier.weight(1f)) {
                Text(
                    positionText(s) + if (page is Page.Multi && page.q.optional) stringResource(R.string.question_optional) else "",
                    style = Hmtm.type.label, color = c.textSecondary,
                )
                Text(
                    if (page is Page.Bundle) stringResource(R.string.multi_pick_all) else q?.question ?: "",
                    style = Hmtm.type.cardTitle, color = c.text,
                )
            }
        }

        val enabled = !driving && !ui.sending
        if (page is Page.Multi || page is Page.Bundle) {
            // 여러 개 고르기·묶음: 그림 없이 보기 전체 (가로 창도 한 카드, 보기 2열)
            val m = Modifier.fillMaxWidth().weight(1f).verticalScroll(rememberScrollState())
            Column(m) {
                when (page) {
                    is Page.Multi -> MultiBody(page.q, s, enabled, onToggle, Modifier.fillMaxWidth())
                    is Page.Bundle -> BundleBody(page, s, enabled, onToggle, onBundleNone, Modifier.fillMaxWidth())
                    else -> {}
                }
            }
        } else if (q != null) {
            if (wide) {
                Row(Modifier.fillMaxWidth().weight(1f), horizontalArrangement = Arrangement.spacedBy(HmtmDimens.cardGap)) {
                    HmtmCard(Modifier.weight(2f).fillMaxHeight()) {
                        Picture(ui, Modifier.fillMaxWidth().weight(1f))
                        Notes(q, first = false)
                    }
                    Options(q, s, enabled, onPick, Modifier.weight(3f).fillMaxHeight().verticalScroll(rememberScrollState()))
                }
            } else {
                Column(
                    Modifier.fillMaxWidth().weight(1f).verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(HmtmDimens.cardGap),
                ) {
                    Options(q, s, enabled, onPick, Modifier.fillMaxWidth())
                    if (q.guessEvidence != null || q.vehicleHint != null) {
                        HmtmCard(Modifier.fillMaxWidth()) { Notes(q, first = true) }
                    }
                }
            }
        } else {
            Spacer(Modifier.weight(1f))
        }

        Footer(ui, driving, wide, onDontKnow, onNext, onRetry)
    }
}

/** "질문 1 / 2", 답변 고치기, 이어지는 질문 */
@Composable
private fun positionText(s: QuestionSession): String = when {
    s.editing -> stringResource(R.string.question_edit_pos, s.position, s.total)
    s.followUp -> stringResource(R.string.question_followup_pos, s.position, s.total)
    else -> stringResource(R.string.question_pos, s.position, s.total)
}

@Composable
private fun Picture(ui: QuestionUi, modifier: Modifier) {
    val s = ui.session
    val q = s.current ?: return
    val from = if (q.field == "parties.other.entry_from") s.selected ?: q.modelGuess
    else s.valueOf("parties.other.entry_from")
    QuestionPicture(
        otherFrom = from,
        pedestrian = ui.pedestrian,
        crossing = s.valueOf("scene.place").let { it == null || it == "intersection" || it == "roundabout" },
        modifier = modifier,
    )
}

/** 그림 아래: 추정 근거 문장 + 차량 기록 참고 상자 */
@Composable
private fun ColumnScope.Notes(q: Question, first: Boolean) {
    if (q.guessEvidence != null) {
        if (!first) Spacer(Modifier.height(HmtmDimens.gapMedium))
        Text(q.guessEvidence, style = Hmtm.type.label, color = Hmtm.colors.textSecondary)
    }
    q.vehicleHint?.let { h ->
        if (!first || q.guessEvidence != null) Spacer(Modifier.height(HmtmDimens.gapMedium))
        VehicleHintBox(h)
    }
}

@Composable
private fun Footer(
    ui: QuestionUi,
    driving: Boolean,
    wide: Boolean,
    onDontKnow: () -> Unit,
    onNext: () -> Unit,
    onRetry: () -> Unit,
) {
    val c = Hmtm.colors
    val s = ui.session
    val status = when {
        driving -> stringResource(R.string.stop_first)
        ui.waiting != null -> ui.waiting
        ui.error != null -> ui.error
        ui.sending -> stringResource(R.string.question_sending)
        else -> null
    }
    val statusColor = when {
        driving -> c.warningText
        ui.error != null -> c.dangerText
        else -> c.textSecondary
    }
    // 여러 개 고르기·묶음은 "건너뛰기" (고른 것 없음 = 답 없음), 한 질문은 "잘 모르겠어요"
    val skipLabel = if (s.page is Page.Single) R.string.question_dont_know else R.string.question_skip
    val dontKnow: @Composable (Modifier) -> Unit = { m ->
        HmtmButton(stringResource(skipLabel), onDontKnow, m, enabled = !driving && !ui.sending)
    }
    val next: @Composable (Modifier) -> Unit = { m ->
        if (ui.error != null) {
            HmtmButton(
                stringResource(R.string.question_resend), onRetry, m, size = ButtonSize.Large,
                kind = ButtonKind.Filled, enabled = !driving,
            )
        } else {
            // 마지막 보기의 "결과 보기"는 답변을 보낸다 → 응답 전까지 Loading
            HmtmButton(
                stringResource(if (s.isLast) R.string.question_finish else R.string.question_next), onNext, m,
                size = ButtonSize.Large, kind = ButtonKind.Filled,
                enabled = !driving && s.hasSelection, loading = ui.sending,
            )
        }
    }
    if (wide) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            dontKnow(Modifier)
            Spacer(Modifier.width(HmtmDimens.gapMedium))
            Text(status ?: "", Modifier.weight(1f), style = Hmtm.type.label, color = statusColor)
            Spacer(Modifier.width(HmtmDimens.gapMedium))
            next(Modifier.width(320.dp))
        }
    } else {
        if (status != null) Text(status, style = Hmtm.type.label, color = statusColor)
        Row(horizontalArrangement = Arrangement.spacedBy(HmtmDimens.gapMedium), verticalAlignment = Alignment.CenterVertically) {
            dontKnow(Modifier.weight(1f))
            next(Modifier.weight(1f))
        }
    }
}

/**
 * 차량 기록 참고 (vehicle_hint). 판정에는 쓰지 않으므로 보기에 미리 고르지 않고 글로만 보여 준다 (design-blackbox 4.4).
 */
@Composable
internal fun VehicleHintBox(h: VehicleHint) {
    val c = Hmtm.colors
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(HmtmDimens.rowRadius)).background(c.vehicleBg)
            .padding(horizontal = HmtmDimens.rowPadH, vertical = HmtmDimens.rowPadV),
    ) {
        Text(
            stringResource(if (h.determined) R.string.hint_value else R.string.hint_value_guess, h.valueLabel),
            style = Hmtm.type.bodyBold, color = c.vehicleFg,
        )
        if (h.text != null) Text(h.text, style = Hmtm.type.label, color = c.vehicleFg)
        Text(hintNote(h), style = Hmtm.type.label, color = c.vehicleFg)
    }
}

/** 참고 표시 아래 한 줄: 시각을 대략만 맞췄으면 그 이유, 아니면 "참고용" 안내 */
internal fun hintNote(h: VehicleHint): String =
    if (!h.applied && h.reasonText != null && h.reason != "guess") h.reasonText
    else "참고용이에요. 결과는 고른 답으로 정해요"

/** 큰 선택 버튼 (최소 높이 100 = 큰 버튼). 보기 4개까지 2열, 그보다 많으면 3열 (세로 창은 늘 2열) */
@Composable
private fun Options(
    q: Question,
    s: QuestionSession,
    enabled: Boolean,
    onPick: (Any?) -> Unit,
    modifier: Modifier,
) {
    val cols = if (q.options.size <= 4 || !LocalWide.current) 2 else 3
    val guess = q.guessIndex
    Column(modifier, verticalArrangement = Arrangement.spacedBy(HmtmDimens.gapMedium)) {
        q.options.indices.chunked(cols).forEach { row ->
            Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(HmtmDimens.gapMedium)) {
                row.forEach { i ->
                    val value = q.options[i]
                    OptionButton(
                        text = q.choices[i],
                        icon = HmtmIcons.option(q.field, value),
                        selected = s.hasSelection && Question.sameValue(s.selected, value),
                        guessLabel = if (i == guess) guessLabel(q.guessSource) else null,
                        enabled = enabled,
                        onClick = { onPick(value) },
                        modifier = Modifier.weight(1f).fillMaxHeight(),
                    )
                }
                repeat(cols - row.size) { Spacer(Modifier.weight(1f)) }
            }
        }
    }
}

/** 추정값 표시: 영상·차량 기록이 낸 추정이면 그 출처, 기본값이면 "기본값" */
internal fun guessLabel(source: String?): Int = when (source) {
    "video" -> R.string.guess_video
    "vehicle" -> R.string.guess_vehicle
    else -> R.string.guess_default
}

/** 보기 버튼: 고르면 파랑 4dp 테두리 + 옅은 파랑 바탕. 눌림 색, 햅틱 */
@Composable
private fun OptionButton(
    text: String,
    icon: HmtmIcons.Pair?,
    selected: Boolean,
    guessLabel: Int?,
    enabled: Boolean,
    onClick: () -> Unit,
    modifier: Modifier,
) {
    val c = Hmtm.colors
    val shape = RoundedCornerShape(24.dp)
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    Box(
        modifier
            .heightIn(min = 100.dp)
            .clip(shape)
            .background(
                when {
                    selected -> c.selectedBg
                    pressed && enabled -> c.basicPressed
                    else -> c.surface
                },
            )
            .border(if (selected) 4.dp else 2.dp, if (selected) c.accent else c.divider, shape)
            .tap(enabled = enabled, role = Role.RadioButton, interaction = interaction, onClick = onClick)
            .padding(horizontal = 24.dp, vertical = 16.dp),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            if (guessLabel != null) {
                Badge(stringResource(guessLabel), BadgeTone.Assumed)
                Spacer(Modifier.height(8.dp))
            }
            // 상대 종류·온 방향 보기: 아이콘 (고르면 Filled + 강조색)
            if (icon != null) {
                Icon(
                    icon.of(selected), null, Modifier.size(IconSize.Large),
                    tint = when {
                        !enabled -> c.textDisabled
                        selected -> c.accentText
                        else -> c.text
                    },
                )
                Spacer(Modifier.height(8.dp))
            }
            Text(
                text,
                style = Hmtm.type.bodyStrong,
                color = if (!enabled) c.textDisabled else c.text,
                textAlign = TextAlign.Center,
            )
        }
    }
}

@Preview(widthDp = 1682, heightDp = 1210)
@Composable
private fun QuestionPreview() {
    val q = Question(
        "parties.other.entry_from", "상대는 어느 쪽 길에서 왔나요?", "choice",
        listOf("left", "right", "opposite", "same"),
        listOf("내 차 기준 왼쪽 길", "내 차 기준 오른쪽 길", "맞은편", "같은 방향 (내 차 앞이나 뒤)"),
        "left", "video", "영상으로는 상대가 왼쪽 길에서 온 것 같아요 (추정)", "내 차 기준 왼쪽 길", null,
    )
    HmtmTheme(darkTheme = false) {
        QuestionScreen(
            QuestionUi(QuestionSession("x", listOf(q, q)).pick("right")),
            driving = false, onBack = {}, onPick = {}, onDontKnow = {}, onNext = {}, onRetry = {},
        )
    }
}
