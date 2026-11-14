package com.example.hmtm.ui.importvideo

import androidx.compose.foundation.background
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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.example.hmtm.R
import com.example.hmtm.data.record.VehicleAttachment
import com.example.hmtm.data.video.PickedVideo
import com.example.hmtm.data.video.StartTime
import com.example.hmtm.ui.Format
import com.example.hmtm.ui.ImportState
import com.example.hmtm.ui.LocalWide
import com.example.hmtm.ui.SyncHint
import com.example.hmtm.ui.components.Badge
import com.example.hmtm.ui.components.BadgeTone
import com.example.hmtm.ui.components.ButtonKind
import com.example.hmtm.ui.components.ButtonSize
import com.example.hmtm.ui.components.CardTitle
import com.example.hmtm.ui.components.HmtmButton
import com.example.hmtm.ui.components.HmtmCard
import com.example.hmtm.ui.components.HmtmIcons
import com.example.hmtm.ui.components.IconSize
import com.example.hmtm.ui.components.NumberCircle
import com.example.hmtm.ui.components.ScreenHeader
import com.example.hmtm.ui.theme.Hmtm
import com.example.hmtm.ui.theme.HmtmDimens
import com.example.hmtm.ui.theme.HmtmTheme

/**
 * docs/app-ui.md 2.2 영상 가져오기.
 * 가로 창: 단계 안내 / 선택한 영상 2열. 세로 창: 단계 안내 → 선택한 영상 → 분석 시작 한 열.
 */
@Composable
fun ImportScreen(
    state: ImportState,
    driving: Boolean,
    onBack: () -> Unit,
    onPick: () -> Unit,
    onStart: () -> Unit,
) {
    val c = Hmtm.colors
    Column(
        Modifier.fillMaxSize().background(c.background).padding(HmtmDimens.screenPadding),
        verticalArrangement = Arrangement.spacedBy(HmtmDimens.cardGap),
    ) {
        ScreenHeader(stringResource(R.string.import_title), onBack)
        if (LocalWide.current) {
            Row(Modifier.fillMaxWidth().weight(1f), horizontalArrangement = Arrangement.spacedBy(HmtmDimens.cardGap)) {
                GuideCard(state, driving, onPick, Modifier.weight(1f).fillMaxHeight(), fill = true)
                SelectedCard(state, driving, onStart, Modifier.weight(1f).fillMaxHeight(), fill = true)
            }
        } else {
            Column(
                Modifier.fillMaxWidth().weight(1f).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(HmtmDimens.cardGap),
            ) {
                GuideCard(state, driving, onPick, Modifier.fillMaxWidth(), fill = false)
                SelectedCard(state, driving, onStart, Modifier.fillMaxWidth(), fill = false)
            }
        }
    }
}

/** fill: 카드가 정해진 높이를 채우면 버튼을 아래로 민다 (가로 창) */
@Composable
private fun GuideCard(state: ImportState, driving: Boolean, onPick: () -> Unit, modifier: Modifier, fill: Boolean) {
    val c = Hmtm.colors
    HmtmCard(modifier) {
        Step(1, stringResource(R.string.import_step1), stringResource(R.string.import_step1_desc))
        Spacer(Modifier.height(HmtmDimens.cardPadding))
        Step(2, stringResource(R.string.import_step2), stringResource(R.string.import_step2_desc))
        if (fill) Spacer(Modifier.weight(1f)) else Spacer(Modifier.height(HmtmDimens.cardPadding))
        HmtmButton(
            stringResource(R.string.import_pick), onPick, Modifier.fillMaxWidth(), enabled = !driving,
            loading = state.inspecting, icon = HmtmIcons.Usb,
        )
        val hint = when {
            driving -> stringResource(R.string.stop_first)
            state.pickCancelled -> stringResource(R.string.import_check_usb)
            else -> null
        }
        if (hint != null) {
            Spacer(Modifier.height(HmtmDimens.gapSmall))
            Text(hint, style = Hmtm.type.label, color = c.warningText)
        }
    }
}

@Composable
private fun Step(n: Int, title: String, body: String) {
    Row {
        NumberCircle(n)
        Spacer(Modifier.width(HmtmDimens.gapMedium))
        Column {
            Text(title, style = Hmtm.type.bodyStrong, color = Hmtm.colors.text)
            Spacer(Modifier.height(4.dp))
            Text(body, style = Hmtm.type.body, color = Hmtm.colors.textSecondary)
        }
    }
}

@Composable
private fun SelectedCard(state: ImportState, driving: Boolean, onStart: () -> Unit, modifier: Modifier, fill: Boolean) {
    val c = Hmtm.colors
    HmtmCard(modifier) {
        CardTitle(stringResource(R.string.import_selected))
        Spacer(Modifier.height(HmtmDimens.gapMedium))
        val v = state.video
        val body = if (fill) Modifier.fillMaxWidth().weight(1f) else Modifier.fillMaxWidth().heightIn(min = 120.dp)
        when {
            state.inspecting -> Box(body, contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = c.accent)
            }
            v == null -> Box(body, contentAlignment = Alignment.Center) {
                Text(
                    state.error ?: stringResource(R.string.import_none), style = Hmtm.type.body,
                    color = if (state.error != null) c.dangerText else c.textSecondary,
                )
            }
            else -> Column(if (fill) Modifier.weight(1f).verticalScroll(rememberScrollState()) else Modifier) {
                VideoRow(v)
                Spacer(Modifier.height(HmtmDimens.gapMedium))
                HorizontalDivider(color = c.divider)
                VehicleRow(v, state.vehicle, state.syncHint)
                HorizontalDivider(color = c.divider)
                Spacer(Modifier.height(HmtmDimens.gapMedium))
                Text(stringResource(R.string.import_privacy), style = Hmtm.type.label, color = c.textSecondary)
            }
        }
        Spacer(Modifier.height(HmtmDimens.gapMedium))
        // 분석 시작은 누르면 바로 분석 중 화면으로 넘어가고 그 화면의 진행 막대가 응답 표시다 (app-bb-notes 12절)
        HmtmButton(
            stringResource(R.string.import_start), onStart, Modifier.fillMaxWidth(), size = ButtonSize.Large,
            kind = ButtonKind.Filled, enabled = v != null && !driving && !state.inspecting,
        )
        if (driving) {
            Spacer(Modifier.height(HmtmDimens.gapSmall))
            Text(stringResource(R.string.stop_first), style = Hmtm.type.label, color = c.warningText)
        }
    }
}

@Composable
private fun VideoRow(v: PickedVideo) {
    val c = Hmtm.colors
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier.size(width = 160.dp, height = 96.dp).clip(RoundedCornerShape(HmtmDimens.rowRadius)).background(c.thumbnail),
            contentAlignment = Alignment.Center,
        ) {
            Icon(HmtmIcons.Play, null, Modifier.size(IconSize.Medium), tint = Color.White)
        }
        Spacer(Modifier.width(HmtmDimens.gapMedium))
        Column {
            Text(v.name, style = Hmtm.type.bodyStrong, color = c.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Spacer(Modifier.height(4.dp))
            Text(videoLine(v), style = Hmtm.type.label, color = c.textSecondary)
            if (StartTime.suspicious(v.startMs)) {
                Text(stringResource(R.string.import_check_time), style = Hmtm.type.label, color = c.warningText)
            }
        }
    }
}

internal fun videoLine(v: PickedVideo): String = listOfNotNull(
    v.durationMs?.let { "길이 ${Format.duration(it)}" },
    v.startMs?.let { "촬영 시작 ${Format.clock(it)}" } ?: "촬영 시각 모름",
    v.sizeBytes.takeIf { it > 0 }?.let { Format.size(it) },
).joinToString(" · ")

@Composable
private fun VehicleRow(v: PickedVideo, vehicle: VehicleAttachment?, hint: SyncHint) {
    val c = Hmtm.colors
    Column(Modifier.fillMaxWidth().padding(vertical = HmtmDimens.gapMedium)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(stringResource(R.string.source_vehicle), Modifier.weight(1f), style = Hmtm.type.label, color = c.textSecondary)
            val (label, tone) = when {
                vehicle == null -> R.string.sync_no_record to BadgeTone.User
                hint == SyncHint.Coarse -> R.string.sync_coarse to BadgeTone.Video
                else -> R.string.sync_none to BadgeTone.Assumed
            }
            Badge(stringResource(label), tone)
        }
        Spacer(Modifier.height(4.dp))
        Text(
            when {
                vehicle != null -> stringResource(
                    R.string.import_vehicle_range, Format.clock(vehicle.from), Format.clock(vehicle.to), vehicle.samples.size,
                )
                v.startMs == null -> stringResource(R.string.import_vehicle_no_time)
                else -> stringResource(R.string.import_vehicle_none)
            },
            style = Hmtm.type.body, color = c.text,
        )
    }
}

@Preview(widthDp = 1682, heightDp = 1210)
@Composable
private fun ImportPreview() {
    HmtmTheme(darkTheme = false) {
        ImportScreen(ImportState(), driving = false, onBack = {}, onPick = {}, onStart = {})
    }
}
