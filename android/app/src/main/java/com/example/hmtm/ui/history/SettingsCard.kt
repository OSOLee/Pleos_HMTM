package com.example.hmtm.ui.history

import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import com.example.hmtm.R
import com.example.hmtm.ui.components.ButtonKind
import com.example.hmtm.ui.components.CardTitle
import com.example.hmtm.ui.components.ConfirmDialog
import com.example.hmtm.ui.components.HmtmButton
import com.example.hmtm.ui.components.HmtmCard
import com.example.hmtm.ui.components.HmtmCheckRow
import com.example.hmtm.ui.components.HmtmIcons
import com.example.hmtm.ui.components.HmtmSwitch
import com.example.hmtm.ui.components.InfoRow
import com.example.hmtm.ui.components.rememberHaptic
import com.example.hmtm.ui.theme.Hmtm
import com.example.hmtm.ui.theme.HmtmDimens

data class SettingsState(
    val autoRecord: Boolean = true,
    val confirmWipe: Boolean = false,
    /** 확인 대화상자의 "서버의 분석 사건도 함께 지우기" */
    val wipeServer: Boolean = false,
    val wiping: Boolean = false,
)

/** docs/app-ui.md 2.6 오른쪽 "기록 설정" (세로 창은 "설정" 탭) */
@Composable
fun SettingsCard(
    state: SettingsState,
    onAutoRecord: (Boolean) -> Unit,
    onWipe: () -> Unit,
    onWipeServer: (Boolean) -> Unit,
    onConfirmWipe: () -> Unit,
    onCancelWipe: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val c = Hmtm.colors
    val haptic = rememberHaptic()
    HmtmCard(modifier) {
        Column(Modifier.weight(1f, fill = false).verticalScroll(rememberScrollState())) {
            CardTitle(stringResource(R.string.settings_title))
            Spacer(Modifier.height(HmtmDimens.gapMedium))
            Row(
                Modifier.fillMaxWidth().heightIn(min = 80.dp)
                    .toggleable(
                        state.autoRecord, role = Role.Switch, indication = null,
                        interactionSource = remember { MutableInteractionSource() },
                    ) { haptic(); onAutoRecord(it) },
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text(stringResource(R.string.settings_auto), style = Hmtm.type.bodyStrong, color = c.text)
                    Text(stringResource(R.string.settings_auto_desc), style = Hmtm.type.label, color = c.textSecondary)
                }
                Spacer(Modifier.width(HmtmDimens.gapMedium))
                HmtmSwitch(state.autoRecord)
            }
            Spacer(Modifier.height(HmtmDimens.gapSmall))
            InfoRow(stringResource(R.string.record_keep_label), stringResource(R.string.settings_keep_value))
            Spacer(Modifier.height(HmtmDimens.gapSmall))
            Text(stringResource(R.string.settings_privacy), style = Hmtm.type.body, color = c.textSecondary)
        }
        Spacer(Modifier.height(HmtmDimens.cardGap))
        HmtmButton(
            stringResource(R.string.settings_wipe), onWipe, Modifier.fillMaxWidth(),
            kind = ButtonKind.Danger, icon = HmtmIcons.Trash, loading = state.wiping,
        )
    }
    if (state.confirmWipe) {
        ConfirmDialog(
            title = stringResource(R.string.wipe_confirm_title),
            text = stringResource(R.string.wipe_confirm_text),
            confirm = stringResource(R.string.wipe_confirm),
            onConfirm = onConfirmWipe,
            onDismiss = onCancelWipe,
            busy = state.wiping,
        ) {
            Spacer(Modifier.height(HmtmDimens.gapMedium))
            HmtmCheckRow(stringResource(R.string.wipe_server), state.wipeServer, enabled = !state.wiping, onChange = onWipeServer)
        }
    }
}

