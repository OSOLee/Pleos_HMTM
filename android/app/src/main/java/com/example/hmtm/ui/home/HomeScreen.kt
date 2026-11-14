package com.example.hmtm.ui.home

import androidx.compose.foundation.background
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.example.hmtm.R
import com.example.hmtm.data.record.Bookmark
import com.example.hmtm.ui.Format
import com.example.hmtm.ui.LocalWide
import com.example.hmtm.ui.components.ButtonKind
import com.example.hmtm.ui.components.ButtonSize
import com.example.hmtm.ui.components.CardTitle
import com.example.hmtm.ui.components.Dot
import com.example.hmtm.ui.components.HmtmButton
import com.example.hmtm.ui.components.HmtmCard
import com.example.hmtm.ui.components.HmtmIcons
import com.example.hmtm.ui.components.IconSize
import com.example.hmtm.ui.components.InfoRow
import com.example.hmtm.ui.components.ListRow
import com.example.hmtm.ui.components.tap
import com.example.hmtm.ui.theme.Hmtm
import com.example.hmtm.ui.theme.HmtmDimens
import com.example.hmtm.ui.theme.HmtmTheme
import java.util.Locale

data class HomeState(
    val recording: Boolean = false,
    val bookmarks: List<Bookmark> = emptyList(),
    val driving: Boolean = false,
)

/** 홈에 보이는 사고 의심 순간 수 (카드 높이를 내용에 맞추므로 많으면 "지난 분석"에서) */
private const val MAX_BOOKMARKS = 4

/**
 * docs/app-ui.md 2.1 홈. 운전 중 1~2초에 파악할 핵심은 "기록 중" 하나 (pleos-design-rules 2절).
 * 가로 창: 기록 상태 / 사고 의심 순간 2열 + 아래 큰 버튼. 세로 창: 한 열, 기록 항목은 한 줄 요약.
 */
@Composable
fun HomeScreen(
    state: HomeState,
    onAnalyze: () -> Unit,
    onHistory: (() -> Unit)?,
) {
    val c = Hmtm.colors
    val wide = LocalWide.current
    Column(
        Modifier.fillMaxSize().background(c.background).padding(HmtmDimens.screenPadding),
        verticalArrangement = Arrangement.spacedBy(HmtmDimens.cardGap),
    ) {
        Row(Modifier.fillMaxWidth().heightIn(min = HmtmDimens.headerHeight), verticalAlignment = Alignment.CenterVertically) {
            Text(stringResource(R.string.home_title), Modifier.weight(1f), style = Hmtm.type.title, color = c.text)
            HmtmButton(
                stringResource(R.string.home_history), onClick = { onHistory?.invoke() }, enabled = onHistory != null,
                icon = HmtmIcons.History, size = ButtonSize.Small,
            )
        }
        // 카드는 내용 높이. 남는 곳은 비우고 큰 버튼은 맨 아래가 아니라 카드 바로 아래 (시스템 패널이 가장자리를 가릴 수 있음)
        Column(
            Modifier.fillMaxWidth().weight(1f, fill = false).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(HmtmDimens.cardGap),
        ) {
            if (wide) {
                Row(
                    Modifier.fillMaxWidth().height(IntrinsicSize.Min),
                    horizontalArrangement = Arrangement.spacedBy(HmtmDimens.cardGap),
                ) {
                    RecordCard(state.recording, compact = false, Modifier.weight(1f).fillMaxHeight())
                    BookmarkCard(state.bookmarks, Modifier.weight(1f).fillMaxHeight())
                }
            } else {
                RecordCard(state.recording, compact = true, Modifier.fillMaxWidth())
                BookmarkCard(state.bookmarks, Modifier.fillMaxWidth())
            }
            AnalyzeButton(state.driving, onAnalyze)
        }
    }
}

@Composable
private fun RecordCard(recording: Boolean, compact: Boolean, modifier: Modifier) {
    val c = Hmtm.colors
    HmtmCard(modifier) {
        CardTitle(stringResource(R.string.home_record_card))
        Spacer(Modifier.height(HmtmDimens.gapMedium))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Dot(if (recording) c.active else c.textDisabled, 20.dp)
            Spacer(Modifier.width(HmtmDimens.gapSmall))
            // 초록(informative/active)은 흰 바탕 글자 대비가 모자라 점에만 쓰고 글자는 본문색 (app-bb-notes 12절)
            Text(
                stringResource(if (recording) R.string.home_recording else R.string.home_not_recording),
                style = Hmtm.type.title, color = if (recording) c.text else c.textSecondary,
            )
        }
        Spacer(Modifier.height(HmtmDimens.gapSmall))
        Text(stringResource(R.string.home_record_desc), style = Hmtm.type.body, color = c.textSecondary)
        Spacer(Modifier.height(HmtmDimens.gapMedium))
        if (compact) {
            // 세로 창: 기록 항목 표를 접어 한 줄로
            InfoRow(stringResource(R.string.home_record_summary_label), stringResource(R.string.home_record_summary), stacked = true)
        } else {
            InfoRow(stringResource(R.string.record_keep_label), stringResource(R.string.record_keep_value))
            InfoRow(stringResource(R.string.record_items_label), stringResource(R.string.record_items_value))
            InfoRow(stringResource(R.string.record_where_label), stringResource(R.string.record_where_value))
        }
    }
}

@Composable
private fun BookmarkCard(items: List<Bookmark>, modifier: Modifier) {
    val c = Hmtm.colors
    HmtmCard(modifier) {
        CardTitle(stringResource(R.string.home_bookmarks))
        Spacer(Modifier.height(HmtmDimens.gapMedium))
        if (items.isEmpty()) {
            Row(Modifier.fillMaxWidth().padding(vertical = HmtmDimens.gapSmall), verticalAlignment = Alignment.CenterVertically) {
                Icon(HmtmIcons.Warning, null, Modifier.size(IconSize.Medium), tint = c.textTertiary)
                Spacer(Modifier.width(HmtmDimens.gapMedium))
                Text(stringResource(R.string.home_bookmarks_empty), style = Hmtm.type.body, color = c.textSecondary)
            }
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(HmtmDimens.gapSmall)) {
                items.take(MAX_BOOKMARKS).forEach { b ->
                    ListRow {
                        Icon(HmtmIcons.Warning, null, Modifier.size(IconSize.Small), tint = c.warningText)
                        Spacer(Modifier.width(HmtmDimens.gapMedium))
                        Column(Modifier.weight(1f)) {
                            Text(Format.dayTime(b.triggerAt), style = Hmtm.type.bodyStrong, color = c.text)
                            Text(bookmarkText(b), style = Hmtm.type.label, color = c.textSecondary)
                        }
                    }
                }
            }
        }
    }
}

internal fun bookmarkText(b: Bookmark): String {
    val label = if (b.reason == "hard_brake") "급제동" else b.reason
    val before = b.speedBefore ?: return label
    val after = b.speedAfter ?: return label
    return String.format(Locale.US, "%s · %.0f → %.0f km/h", label, before, after)
}

/** 주 행동 큰 버튼 (button/filled, 높이 100 이상, 둥글기 32) */
@Composable
private fun AnalyzeButton(driving: Boolean, onClick: () -> Unit) {
    val c = Hmtm.colors
    val enabled = !driving
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val bg = when {
        !enabled -> c.buttonDisabled
        pressed -> c.filledPressed
        else -> c.filled
    }
    val fg = if (enabled) c.onFilled else c.textDisabled
    Row(
        Modifier
            .fillMaxWidth()
            .heightIn(min = 120.dp)
            .clip(RoundedCornerShape(32.dp))
            .background(bg)
            .tap(enabled = enabled, interaction = interaction, onClick = onClick)
            .padding(horizontal = 40.dp, vertical = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(HmtmIcons.Video, null, Modifier.size(IconSize.Large), tint = fg)
        Spacer(Modifier.width(16.dp))
        Column(Modifier.weight(1f)) {
            Text(stringResource(R.string.home_analyze), style = Hmtm.type.cardTitle, color = fg)
            Text(
                stringResource(if (driving) R.string.stop_first else R.string.home_analyze_sub),
                style = Hmtm.type.label, color = fg,
            )
        }
        Icon(HmtmIcons.ArrowRight, null, Modifier.size(IconSize.Medium), tint = fg)
    }
}

@Preview(widthDp = 1682, heightDp = 1210)
@Composable
private fun HomePreview() {
    HmtmTheme(darkTheme = false) {
        HomeScreen(
            HomeState(
                recording = true,
                bookmarks = listOf(Bookmark(System.currentTimeMillis() - 3_600_000, "hard_brake", 62f, 8f)),
            ),
            onAnalyze = {}, onHistory = {},
        )
    }
}
