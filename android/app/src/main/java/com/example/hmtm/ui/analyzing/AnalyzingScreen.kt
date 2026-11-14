package com.example.hmtm.ui.analyzing

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.example.hmtm.R
import com.example.hmtm.ui.AnalyzingState
import com.example.hmtm.ui.components.ButtonKind
import com.example.hmtm.ui.components.HmtmButton
import com.example.hmtm.ui.components.HmtmCard
import com.example.hmtm.ui.components.HmtmIconButton
import com.example.hmtm.ui.components.HmtmIcons
import com.example.hmtm.ui.components.StepCircle
import com.example.hmtm.ui.components.StepState
import com.example.hmtm.ui.theme.Hmtm
import com.example.hmtm.ui.theme.HmtmDimens
import com.example.hmtm.ui.theme.HmtmTheme

private val STEPS = listOf(R.string.step_upload, R.string.step_analyze, R.string.step_sync, R.string.step_judge)

/** docs/app-ui.md 2.3 분석 중. 가로·세로 같은 배치 (가운데 카드, 폭만 창에 맞춤) */
@Composable
fun AnalyzingScreen(
    state: AnalyzingState,
    onBack: () -> Unit,
    onRetry: () -> Unit,
    onHome: () -> Unit,
) {
    val c = Hmtm.colors
    Column(Modifier.fillMaxSize().background(c.background).padding(HmtmDimens.screenPadding)) {
        HmtmIconButton(HmtmIcons.Back, stringResource(R.string.back), onBack)
        Spacer(Modifier.height(HmtmDimens.cardGap))
        Box(Modifier.fillMaxWidth().weight(1f).verticalScroll(rememberScrollState()), contentAlignment = Alignment.TopCenter) {
            HmtmCard(Modifier.widthIn(max = 808.dp).fillMaxWidth(), padding = 48.dp) {
                when {
                    state.error != null -> Failure(
                        stringResource(R.string.analyze_failed), "${state.error}", state.errorCode, onRetry, onHome,
                    )
                    state.stopped != null -> Failure(state.stopped, null, state.errorCode, null, onHome)
                    else -> Progress(state)
                }
            }
        }
    }
}

@Composable
private fun Progress(state: AnalyzingState) {
    val c = Hmtm.colors
    Text(
        stringResource(if (state.picking) R.string.analyzing_pick_title else R.string.analyzing_title),
        style = Hmtm.type.title, color = c.text,
    )
    Spacer(Modifier.height(4.dp))
    // 실제 서버는 CPU(2 vCPU)라 영상 하나에 몇 분 걸릴 수 있다
    Text(stringResource(R.string.analyzing_sub), style = Hmtm.type.label, color = c.textSecondary)
    Spacer(Modifier.height(HmtmDimens.cardGap))
    // 진행 표시 (움직이는 것은 이것뿐, 2절). 분석 단계에서 서버가 진행률을 안 주면(0) 값 없는 막대 + 단계 표시만
    val bar = Modifier.fillMaxWidth().height(12.dp).clip(RoundedCornerShape(6.dp))
    if (state.indeterminate) {
        LinearProgressIndicator(bar, color = c.accent, trackColor = c.divider, strokeCap = StrokeCap.Round, gapSize = 0.dp)
    } else {
        LinearProgressIndicator(
            progress = { state.overall },
            modifier = bar,
            color = c.accent, trackColor = c.divider, strokeCap = StrokeCap.Round, gapSize = 0.dp,
            drawStopIndicator = {},
        )
    }
    Spacer(Modifier.height(HmtmDimens.cardGap))
    Column(verticalArrangement = Arrangement.spacedBy(20.dp)) {
        STEPS.forEachIndexed { i, name ->
            val st = when {
                i < state.step -> StepState.Done
                i == state.step -> StepState.Active
                else -> StepState.Waiting
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                StepCircle(st)
                Spacer(Modifier.width(HmtmDimens.gapMedium))
                val label = when {
                    i == 0 && st == StepState.Active -> stringResource(R.string.step_upload_pct, (state.uploadProgress * 100).toInt())
                    i == 1 && st == StepState.Active && state.analysisProgress > 0 ->
                        stringResource(name) + " · " + stringResource(R.string.analyzing_pct, state.analysisProgress)
                    else -> stringResource(name)
                }
                Text(
                    label, Modifier.weight(1f),
                    style = if (st == StepState.Active) Hmtm.type.bodyStrong else Hmtm.type.body,
                    color = if (st == StepState.Waiting) c.textSecondary else c.text,
                )
                Text(
                    stringResource(
                        when (st) {
                            StepState.Done -> R.string.step_done
                            StepState.Active -> R.string.step_active
                            StepState.Waiting -> R.string.step_waiting
                        },
                    ),
                    style = Hmtm.type.label,
                    color = if (st == StepState.Active) c.accentText else c.textSecondary,
                )
            }
        }
    }
    Spacer(Modifier.height(HmtmDimens.cardGap))
    Text(stringResource(R.string.analyzing_keep_going), style = Hmtm.type.label, color = c.textSecondary)
}

@Composable
private fun Failure(title: String, detail: String?, code: String?, onRetry: (() -> Unit)?, onHome: () -> Unit) {
    val c = Hmtm.colors
    Text(title, style = Hmtm.type.title, color = c.text)
    if (detail != null && detail != title) {
        Spacer(Modifier.height(HmtmDimens.gapSmall))
        Text(detail, style = Hmtm.type.body, color = c.textSecondary)
    }
    if (code != null) {
        Spacer(Modifier.height(HmtmDimens.gapSmall))
        Text(stringResource(R.string.error_code, code), style = Hmtm.type.label, color = c.textSecondary)
    }
    Spacer(Modifier.height(HmtmDimens.cardGap))
    Row(horizontalArrangement = Arrangement.spacedBy(HmtmDimens.gapMedium)) {
        HmtmButton(stringResource(R.string.go_home), onHome, Modifier.weight(1f))
        if (onRetry != null) {
            HmtmButton(stringResource(R.string.retry), onRetry, Modifier.weight(1f), kind = ButtonKind.Filled)
        }
    }
}

@Preview(widthDp = 1682, heightDp = 1210)
@Composable
private fun AnalyzingPreview() {
    HmtmTheme(darkTheme = false) {
        AnalyzingScreen(AnalyzingState(step = 1, uploadProgress = 1f, analysisProgress = 40), {}, {}, {})
    }
}
