package com.example.hmtm.ui.onboarding

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.example.hmtm.R
import com.example.hmtm.ui.LocalWide
import com.example.hmtm.ui.components.ButtonKind
import com.example.hmtm.ui.components.ButtonSize
import com.example.hmtm.ui.components.HmtmButton
import com.example.hmtm.ui.components.HmtmCard
import com.example.hmtm.ui.components.InfoRow
import com.example.hmtm.ui.theme.Hmtm
import com.example.hmtm.ui.theme.HmtmDimens
import com.example.hmtm.ui.theme.HmtmTheme

/**
 * 첫 실행 안내: 기록 항목·보관 기간·저장 위치, 동의, 속도 권한 요청.
 * 동의 전에는 수집 서비스를 시작하지 않는다 (시안에 없는 화면이라 홈 "기록 상태" 카드 문구·모양을 따름).
 */
@Composable
fun OnboardingScreen(onAgree: () -> Unit, onLater: () -> Unit) {
    val c = Hmtm.colors
    val stacked = !LocalWide.current
    Box(
        Modifier.fillMaxSize().background(c.background).padding(HmtmDimens.screenPadding).verticalScroll(rememberScrollState()),
        contentAlignment = Alignment.TopCenter,
    ) {
        HmtmCard(Modifier.widthIn(max = 1000.dp).fillMaxWidth(), padding = 48.dp) {
            Text(stringResource(R.string.onboarding_title), style = Hmtm.type.title, color = c.text)
            Spacer(Modifier.height(HmtmDimens.gapMedium))
            Text(stringResource(R.string.onboarding_desc), style = Hmtm.type.body, color = c.textSecondary)
            Spacer(Modifier.height(HmtmDimens.gapMedium))
            InfoRow(stringResource(R.string.record_items_label), stringResource(R.string.record_items_value), stacked = stacked)
            InfoRow(stringResource(R.string.record_keep_label), stringResource(R.string.onboarding_keep), stacked = stacked)
            InfoRow(stringResource(R.string.record_where_label), stringResource(R.string.record_where_value), stacked = stacked)
            InfoRow(stringResource(R.string.onboarding_send_label), stringResource(R.string.onboarding_send), stacked = stacked)
            Spacer(Modifier.height(HmtmDimens.gapMedium))
            Text(stringResource(R.string.onboarding_permission), style = Hmtm.type.label, color = c.textSecondary)
            Spacer(Modifier.height(HmtmDimens.cardGap))
            Row(horizontalArrangement = Arrangement.spacedBy(HmtmDimens.gapMedium)) {
                HmtmButton(stringResource(R.string.onboarding_later), onLater, Modifier.weight(1f), size = ButtonSize.Large)
                HmtmButton(
                    stringResource(R.string.onboarding_agree), onAgree, Modifier.weight(if (stacked) 1f else 2f),
                    size = ButtonSize.Large, kind = ButtonKind.Filled,
                )
            }
        }
    }
}

@Preview(widthDp = 1682, heightDp = 1210)
@Composable
private fun OnboardingPreview() {
    HmtmTheme(darkTheme = false) { OnboardingScreen(onAgree = {}, onLater = {}) }
}
