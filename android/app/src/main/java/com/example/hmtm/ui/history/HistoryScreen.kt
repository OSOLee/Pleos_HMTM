package com.example.hmtm.ui.history

import androidx.compose.foundation.background
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.example.hmtm.R
import com.example.hmtm.data.bb.BbCase
import com.example.hmtm.data.bb.BbSummary
import com.example.hmtm.ui.Format
import com.example.hmtm.ui.LocalWide
import com.example.hmtm.ui.components.Badge
import com.example.hmtm.ui.components.BadgeTone
import com.example.hmtm.ui.components.ButtonKind
import com.example.hmtm.ui.components.ButtonSize
import com.example.hmtm.ui.components.CardTitle
import com.example.hmtm.ui.components.HmtmButton
import com.example.hmtm.ui.components.HmtmCard
import com.example.hmtm.ui.components.HmtmIcons
import com.example.hmtm.ui.components.ScreenHeader
import com.example.hmtm.ui.components.tap
import com.example.hmtm.ui.theme.Hmtm
import com.example.hmtm.ui.theme.HmtmDimens
import com.example.hmtm.ui.theme.HmtmTheme

data class HistoryState(
    val items: List<BbSummary> = emptyList(),
    val loading: Boolean = false,
    /** 다음 쪽이 있을 수 있음 (마지막으로 받은 쪽이 꽉 참) */
    val more: Boolean = false,
    val error: String? = null,
    /** 사건을 여는 중 */
    val opening: String? = null,
)

/**
 * docs/app-ui.md 2.6 지난 분석. 오른쪽 설정 카드는 settings로 받는다 (없으면 목록만).
 * 가로 창: 목록 / 설정 2열. 세로 창: 탭 2개 (지난 분석 / 설정).
 */
@Composable
fun HistoryScreen(
    state: HistoryState,
    onBack: () -> Unit,
    onOpen: (BbSummary) -> Unit,
    onMore: () -> Unit,
    onReload: () -> Unit,
    onDelete: ((BbSummary) -> Unit)?,
    settings: (@Composable (Modifier) -> Unit)? = null,
) {
    val c = Hmtm.colors
    val wide = LocalWide.current
    Column(
        Modifier.fillMaxSize().background(c.background).padding(HmtmDimens.screenPadding),
        verticalArrangement = Arrangement.spacedBy(HmtmDimens.cardGap),
    ) {
        ScreenHeader(stringResource(R.string.history_title), onBack)
        if (wide || settings == null) {
            Row(Modifier.fillMaxWidth().weight(1f), horizontalArrangement = Arrangement.spacedBy(HmtmDimens.cardGap)) {
                CaseList(state, onOpen, onMore, onReload, onDelete, Modifier.weight(3f).fillMaxHeight())
                settings?.invoke(Modifier.weight(2f).fillMaxHeight())
            }
        } else {
            var tab by rememberSaveable { mutableIntStateOf(0) }
            Tabs(listOf(stringResource(R.string.history_tab_list), stringResource(R.string.history_tab_settings)), tab) { tab = it }
            if (tab == 0) CaseList(state, onOpen, onMore, onReload, onDelete, Modifier.fillMaxWidth().weight(1f))
            else settings(Modifier.fillMaxWidth().weight(1f))
        }
    }
}

/** 탭 (tabs/solid/medium: 높이 80, 안 여백 8, 버튼 64, 둥글기 24/16). 고른 탭은 주 버튼 색 */
@Composable
private fun Tabs(labels: List<String>, selected: Int, onSelect: (Int) -> Unit) {
    val c = Hmtm.colors
    Row(
        Modifier.fillMaxWidth().height(80.dp).clip(RoundedCornerShape(24.dp)).background(c.basic).padding(8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        labels.forEachIndexed { i, label ->
            val on = i == selected
            val interaction = remember { MutableInteractionSource() }
            val pressed by interaction.collectIsPressedAsState()
            Box(
                Modifier.weight(1f).fillMaxHeight().clip(RoundedCornerShape(16.dp))
                    .background(if (on) c.filled else if (pressed) c.basicPressed else c.basic)
                    .tap(role = Role.Tab, interaction = interaction) { onSelect(i) },
                contentAlignment = Alignment.Center,
            ) {
                Text(label, style = Hmtm.type.bodyStrong, color = if (on) c.onFilled else c.text, textAlign = TextAlign.Center)
            }
        }
    }
}

@Composable
private fun CaseList(
    state: HistoryState,
    onOpen: (BbSummary) -> Unit,
    onMore: () -> Unit,
    onReload: () -> Unit,
    onDelete: ((BbSummary) -> Unit)?,
    modifier: Modifier,
) {
    val c = Hmtm.colors
    HmtmCard(modifier) {
        CardTitle(stringResource(R.string.history_cases))
        if (state.error != null && state.items.isNotEmpty()) {
            Text(state.error, style = Hmtm.type.label, color = c.dangerText)
        }
        Spacer(Modifier.height(HmtmDimens.gapMedium))
        when {
            state.items.isEmpty() && state.loading -> Center(stringResource(R.string.loading))
            state.items.isEmpty() && state.error != null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(state.error, style = Hmtm.type.body, color = c.dangerText, textAlign = TextAlign.Center)
                    Spacer(Modifier.height(HmtmDimens.gapMedium))
                    HmtmButton(stringResource(R.string.reload), onReload, icon = HmtmIcons.Refresh, loading = state.loading)
                }
            }
            state.items.isEmpty() -> Center(stringResource(R.string.history_empty))
            else -> LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(HmtmDimens.gapSmall)) {
                items(state.items, key = { it.id }) { item ->
                    CaseRow(item, state.opening == item.id, onOpen, onDelete)
                }
                if (state.more) item {
                    Box(Modifier.fillMaxWidth().padding(8.dp), contentAlignment = Alignment.Center) {
                        HmtmButton(stringResource(R.string.more), onMore, loading = state.loading)
                    }
                }
            }
        }
    }
}

@Composable
private fun Center(text: String) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text(text, style = Hmtm.type.body, color = Hmtm.colors.textSecondary)
    }
}

@Composable
private fun CaseRow(s: BbSummary, opening: Boolean, onOpen: (BbSummary) -> Unit, onDelete: ((BbSummary) -> Unit)?) {
    val c = Hmtm.colors
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    Row(
        Modifier
            .fillMaxWidth()
            .heightIn(min = 100.dp)
            .clip(RoundedCornerShape(HmtmDimens.rowRadius))
            .background(if (pressed) c.basicPressed else c.surfaceHigh)
            .tap(enabled = !opening, interaction = interaction) { onOpen(s) }
            .padding(start = HmtmDimens.rowPadH, end = 8.dp, top = HmtmDimens.rowPadV, bottom = HmtmDimens.rowPadV),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                "${Format.dayTime(s.accidentAt)} · ${summaryText(s)}",
                style = Hmtm.type.bodyStrong, color = c.text, maxLines = 2, overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (s.vehicleRecord) Badge(stringResource(R.string.badge_vehicle_record), BadgeTone.Vehicle)
                else Badge(stringResource(R.string.badge_video_only), BadgeTone.User)
                if (s.collisionReviewNeeded) {
                    // 사고 순간 확인 필요 (collision_review_needed): 눌러 열면 결과 화면의 "사고 순간 고르기"
                    Spacer(Modifier.width(HmtmDimens.gapSmall))
                    Badge(stringResource(R.string.badge_pick_needed), BadgeTone.Assumed, icon = HmtmIcons.Warning)
                }
                if (s.ruleId != null) {
                    Spacer(Modifier.width(HmtmDimens.gapSmall))
                    Text(s.ruleId, style = Hmtm.type.label, color = c.textSecondary)
                }
            }
            if (s.finished && (s.provisional || s.remainingCount > 0)) {
                Spacer(Modifier.height(4.dp))
                Text(
                    if (s.remainingCount > 0) stringResource(R.string.provisional_n, s.remainingCount)
                    else stringResource(R.string.provisional),
                    style = Hmtm.type.label, color = c.warningText,
                )
            }
        }
        Spacer(Modifier.width(HmtmDimens.gapSmall))
        Column(horizontalAlignment = Alignment.End) {
            Text(
                if (opening) stringResource(R.string.opening) else faultText(s),
                style = Hmtm.type.cardTitle, color = if (s.egoFault != null) c.text else c.textSecondary,
            )
            val alt = vehicleText(s)
            if (!opening && alt != null) Text(alt, style = Hmtm.type.label, color = c.vehicleFg)
        }
        if (onDelete != null) {
            Spacer(Modifier.width(HmtmDimens.gapSmall))
            // 아이콘만 있는 버튼은 뒤로 가기만 → 작은 버튼에 글자 (5절)
            HmtmButton(
                stringResource(R.string.delete), { onDelete(s) },
                size = ButtonSize.Small, kind = ButtonKind.Danger, icon = HmtmIcons.Trash,
            )
        }
    }
}

/** 사고 요약: 판정 제목 > 상대 종류 > 상태 */
internal fun summaryText(s: BbSummary): String = when {
    s.analyzing -> "분석 중"
    s.status == BbCase.NO_COLLISION -> "부딪힌 순간을 찾지 못함"
    s.status == BbCase.UNSUPPORTED -> "지원하지 않는 영상"
    s.status == BbCase.FAILED -> "분석 실패"
    s.title != null -> s.title
    s.otherLabel != null -> "상대 ${s.otherLabel} · 기준 찾는 중"
    else -> "기준 찾는 중"
}

/** 오른쪽 과실비율: 보행자 장이면 서버 표기("보행자 과실 30%"), 아니면 "60 : 40" */
internal fun faultText(s: BbSummary): String {
    val d = s.display
    return when {
        d != null && d.pedestrianOnly -> d.text
        s.egoFault != null && s.otherFault != null -> "${s.egoFault} : ${s.otherFault}"
        else -> "—"
    }
}

/** 차량 기록을 입증하면 바뀌는 비율: "기록 입증 시 70 : 30" (바뀌지 않으면 null) */
internal fun vehicleText(s: BbSummary): String? {
    if (!s.vehicleChanges) return null
    val d = s.displayWithVehicle ?: return "기록 입증 시 달라짐"
    return "기록 입증 시 " + d.text.removePrefix("내 차 ").replace(" : 상대 ", " : ")
}

@Preview(widthDp = 1682, heightDp = 1210)
@Composable
private fun HistoryPreview() {
    val now = System.currentTimeMillis()
    HmtmTheme(darkTheme = false) {
        HistoryScreen(
            HistoryState(
                items = listOf(
                    BbSummary(
                        "a", "needs_answers", now, now, 6.0, "승용차", "car_car", "차16-1",
                        "왼쪽 좌회전 대 왼쪽 길 직진", 60, 40,
                        BbCase.FaultDisplay("ratio", "내 차 60 : 상대 40", null), true, 5, null,
                        vehicleRecord = true, vehicleChanges = true,
                        displayWithVehicle = BbCase.FaultDisplay("ratio", "내 차 70 : 상대 30", null),
                    ),
                ),
            ),
            onBack = {}, onOpen = {}, onMore = {}, onReload = {}, onDelete = {},
        )
    }
}
