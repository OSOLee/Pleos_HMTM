package com.example.hmtm.ui.questions

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import com.example.hmtm.R
import com.example.hmtm.data.bb.Bundles
import com.example.hmtm.data.bb.Page
import com.example.hmtm.data.bb.Question
import com.example.hmtm.data.bb.QuestionSession
import com.example.hmtm.ui.LocalWide
import com.example.hmtm.ui.components.Badge
import com.example.hmtm.ui.components.BadgeTone
import com.example.hmtm.ui.components.HmtmCard
import com.example.hmtm.ui.components.HmtmIcons
import com.example.hmtm.ui.components.IconSize
import com.example.hmtm.ui.components.tap
import com.example.hmtm.ui.theme.Hmtm
import com.example.hmtm.ui.theme.HmtmDimens

/**
 * docs/app-ui.md 2.8 여러 개 고르기 (운전자 요인·특수 상황).
 * "해당하는 것을 모두 고르세요" + 보기(묶음 이름이 있으면 묶음별) + 맨 아래 "해당 없음" (다른 보기와 같이 못 고름).
 */
@Composable
fun MultiBody(q: Question, s: QuestionSession, enabled: Boolean, onToggle: (String, Any?) -> Unit, modifier: Modifier) {
    val c = Hmtm.colors
    val chosen = s.chosen(q.field)
    val none = q.noneIndex
    val items = q.options.indices.filter { it != none }
    val groups = q.optionGroups?.takeIf { g -> items.map { g[it] }.distinct().size > 1 }
    HmtmCard(modifier) {
        Text(stringResource(R.string.multi_pick_all), style = Hmtm.type.bodyBold, color = c.textSecondary)
        if (groups == null) {
            Spacer(Modifier.height(HmtmDimens.gapMedium))
            OptionGrid(items.map { i -> Opt(q.choices[i], chosen.any { Question.sameValue(it, q.options[i]) }, null) {
                onToggle(q.field, q.options[i])
            } }, enabled)
        } else {
            // 묶음 이름이 처음 나온 순서대로
            items.groupBy { groups[it] }.forEach { (name, idx) ->
                Spacer(Modifier.height(HmtmDimens.cardGap))
                Text(name, style = Hmtm.type.label, color = c.textSecondary)
                Spacer(Modifier.height(HmtmDimens.gapSmall))
                OptionGrid(idx.map { i -> Opt(q.choices[i], chosen.any { Question.sameValue(it, q.options[i]) }, null) {
                    onToggle(q.field, q.options[i])
                } }, enabled)
            }
        }
        if (none >= 0) {
            NoneRow(q.choices[none], chosen == listOf(Question.NONE), enabled) { onToggle(q.field, Question.NONE) }
        }
    }
}

/**
 * 묶음 (보행자 가감 요소 셋). 질문마다 제목 + 보기(그 질문 안에서는 하나만), 맨 아래 공통 "해당 없음".
 * 고르지 않은 질문은 답하지 않은 것으로 보낸다 (QuestionSession.next).
 */
@Composable
fun BundleBody(
    p: Page.Bundle,
    s: QuestionSession,
    enabled: Boolean,
    onToggle: (String, Any?) -> Unit,
    onNone: () -> Unit,
    modifier: Modifier,
) {
    val c = Hmtm.colors
    val allNone = s.bundleNone(p)
    HmtmCard(modifier) {
        Text(stringResource(R.string.multi_bundle_hint), style = Hmtm.type.label, color = c.textSecondary)
        p.questions.forEachIndexed { n, q ->
            Spacer(Modifier.height(if (n == 0) HmtmDimens.gapMedium else HmtmDimens.cardGap))
            Text(q.question, style = Hmtm.type.bodyBold, color = c.text)
            if (q.guessEvidence != null) Text(q.guessEvidence, style = Hmtm.type.label, color = c.textSecondary)
            Spacer(Modifier.height(HmtmDimens.gapSmall))
            val noneValue = Bundles.NONE_VALUE[q.field]
            val guess = q.guessIndex
            val items = q.options.indices.filterNot { Question.sameValue(q.options[it], noneValue) }
            OptionGrid(items.map { i ->
                val v = q.options[i]
                Opt(
                    q.choices[i],
                    !allNone && s.picked.containsKey(q.field) && Question.sameValue(s.picked[q.field], v),
                    if (i == guess) guessLabel(q.guessSource) else null,
                ) { onToggle(q.field, v) }
            }, enabled)
            q.vehicleHint?.let {
                Spacer(Modifier.height(HmtmDimens.gapSmall))
                VehicleHintBox(it)
            }
        }
        NoneRow(stringResource(R.string.multi_none), allNone, enabled, onNone)
    }
}

private data class Opt(val text: String, val checked: Boolean, val guessLabel: Int?, val onClick: () -> Unit)

/** 보기 칸: 가로 창 2열, 세로 창 1열 (보기 글자가 길다) */
@Composable
private fun OptionGrid(opts: List<Opt>, enabled: Boolean) {
    val cols = if (LocalWide.current) 2 else 1
    Column(verticalArrangement = Arrangement.spacedBy(HmtmDimens.gapSmall)) {
        opts.chunked(cols).forEach { row ->
            Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(HmtmDimens.gapSmall)) {
                row.forEach { o ->
                    CheckOption(o.text, o.checked, o.guessLabel, enabled, o.onClick, Modifier.weight(1f).fillMaxHeight())
                }
                repeat(cols - row.size) { Spacer(Modifier.weight(1f)) }
            }
        }
    }
}

/** 맨 아래 "해당 없음": 구분선 아래 한 줄 전체 */
@Composable
private fun NoneRow(text: String, checked: Boolean, enabled: Boolean, onClick: () -> Unit) {
    Spacer(Modifier.height(HmtmDimens.cardGap))
    HorizontalDivider(color = Hmtm.colors.divider, thickness = 1.dp)
    Spacer(Modifier.height(HmtmDimens.cardGap))
    CheckOption(text, checked, null, enabled, onClick, Modifier.fillMaxWidth())
}

/**
 * 고르기 칸 (체크 상자 + 글자, 최소 높이 80 = 중간 버튼). 고르면 강조색 4dp 테두리 + 옅은 파랑 바탕,
 * 체크 상자는 selections/checkbox 규격(48, 둥글기 12). 눌림 색, 햅틱
 */
@Composable
private fun CheckOption(
    text: String,
    checked: Boolean,
    guessLabel: Int?,
    enabled: Boolean,
    onClick: () -> Unit,
    modifier: Modifier,
) {
    val c = Hmtm.colors
    val shape = RoundedCornerShape(HmtmDimens.rowRadius * 2)
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    Row(
        modifier
            .heightIn(min = 80.dp)
            .clip(shape)
            .background(
                when {
                    checked -> c.selectedBg
                    pressed && enabled -> c.basicPressed
                    else -> c.surface
                },
            )
            .border(if (checked) 4.dp else 2.dp, if (checked) c.accent else c.divider, shape)
            .tap(enabled = enabled, role = Role.Checkbox, interaction = interaction, onClick = onClick)
            .padding(horizontal = HmtmDimens.rowPadH, vertical = HmtmDimens.gapSmall),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        val box = RoundedCornerShape(12.dp)
        Box(
            Modifier.size(48.dp).clip(box)
                .then(if (checked) Modifier.background(c.filled) else Modifier.border(4.dp, c.textTertiary, box)),
            contentAlignment = Alignment.Center,
        ) {
            if (checked) Icon(HmtmIcons.Check, null, Modifier.size(IconSize.Small), tint = c.onFilled)
        }
        Spacer(Modifier.width(HmtmDimens.gapMedium))
        Column(Modifier.weight(1f)) {
            if (guessLabel != null) {
                Badge(stringResource(guessLabel), BadgeTone.Assumed)
                Spacer(Modifier.height(4.dp))
            }
            Text(text, style = Hmtm.type.bodyStrong, color = if (enabled) c.text else c.textDisabled)
        }
    }
}
