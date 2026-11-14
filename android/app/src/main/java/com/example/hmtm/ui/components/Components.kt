package com.example.hmtm.ui.components

import androidx.compose.runtime.staticCompositionLocalOf
import android.view.HapticFeedbackConstants
import androidx.annotation.StringRes
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.example.hmtm.R
import com.example.hmtm.ui.theme.Hmtm
import com.example.hmtm.ui.theme.HmtmColors
import com.example.hmtm.ui.theme.HmtmDimens

// ---------- 터치 ----------

/** 터치 햅틱 (docs/pleos-design-rules.md 2절: 모든 버튼·선택지). 시스템 햅틱 설정을 따른다 */
@Composable
fun rememberHaptic(): () -> Unit {
    val view = LocalView.current
    return remember(view) { { view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY) } }
}

/**
 * 한 번 탭 (물결 애니메이션 없음, 2절 "진행 표시 외 애니메이션 없음") + 햅틱.
 * 눌림 색은 부르는 쪽이 interaction으로 정한다.
 */
@Composable
fun Modifier.tap(
    enabled: Boolean = true,
    role: Role = Role.Button,
    interaction: MutableInteractionSource? = null,
    onClick: () -> Unit,
): Modifier {
    val haptic = rememberHaptic()
    val source = interaction ?: remember { MutableInteractionSource() }
    return this.clickable(source, indication = null, enabled = enabled, role = role) {
        haptic()
        onClick()
    }
}

// ---------- 카드·행 ----------

/** 카드: surface/basic, 둥글기 level5(16), 안 여백 32. 라이트는 그림자 level1, 다크는 바탕과 색이 같아 구분선 테두리 */
@Composable
fun HmtmCard(
    modifier: Modifier = Modifier,
    padding: Dp = HmtmDimens.cardPadding,
    content: @Composable ColumnScope.() -> Unit,
) {
    val c = Hmtm.colors
    val shape = RoundedCornerShape(HmtmDimens.cardRadius)
    Column(
        modifier
            .then(
                if (c.dark) Modifier.border(1.dp, c.divider, shape)
                else Modifier.shadow(6.dp, shape, ambientColor = SHADOW, spotColor = SHADOW),
            )
            .clip(shape)
            .background(c.surface)
            .padding(padding),
        content = content,
    )
}

private val SHADOW = Color(0x14131417)

@Composable
fun CardTitle(text: String, modifier: Modifier = Modifier) {
    Text(text, modifier, style = Hmtm.type.cardTitle, color = Hmtm.colors.text)
}

/** 카드 안 "이름 / 값" 행 (구분선 위). 좁으면 값이 아래 줄로 */
@Composable
fun InfoRow(label: String, value: String, showDivider: Boolean = true, stacked: Boolean = false) {
    val c = Hmtm.colors
    Column {
        if (showDivider) HorizontalDivider(color = c.divider, thickness = 1.dp)
        if (stacked) {
            Column(Modifier.fillMaxWidth().padding(vertical = HmtmDimens.rowPadV)) {
                Text(label, style = Hmtm.type.label, color = c.textSecondary)
                Text(value, style = Hmtm.type.body, color = c.text)
            }
        } else {
            Row(
                Modifier.fillMaxWidth().padding(vertical = HmtmDimens.rowPadV),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(label, style = Hmtm.type.label, color = c.textSecondary)
                Spacer(Modifier.width(HmtmDimens.gapMedium))
                Text(value, Modifier.weight(1f, fill = false), style = Hmtm.type.body, color = c.text, textAlign = TextAlign.End)
            }
        }
    }
}

/** 카드 안 강조 영역 행 (surface/high, 둥글기 level4) */
@Composable
fun ListRow(modifier: Modifier = Modifier, content: @Composable RowScope.() -> Unit) {
    Row(
        modifier
            .fillMaxWidth()
            .heightIn(min = 80.dp)
            .clip(RoundedCornerShape(HmtmDimens.rowRadius))
            .background(Hmtm.colors.surfaceHigh)
            .padding(horizontal = HmtmDimens.rowPadH, vertical = HmtmDimens.rowPadV),
        verticalAlignment = Alignment.CenterVertically,
        content = content,
    )
}

/** 카드 안 강조 상자 (적용한 기준 등) */
@Composable
fun HighBox(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(HmtmDimens.rowRadius))
            .background(Hmtm.colors.surfaceHigh)
            .padding(horizontal = HmtmDimens.rowPadH, vertical = HmtmDimens.rowPadV),
        content = content,
    )
}

// ---------- 버튼 (5절) ----------

/** 버튼 규격 (Connect-S): 높이, 좌우 여백, 최소 폭, 아이콘, 아이콘-글자 간격, 둥글기 */
enum class ButtonSize(val height: Dp, val padH: Dp, val minWidth: Dp, val icon: Dp, val gap: Dp, val radius: Dp) {
    /** 주 행동 (분석 시작, 결과 확정) */
    Large(100.dp, 40.dp, 140.dp, 52.dp, 16.dp, 32.dp),
    /** 일반 */
    Medium(80.dp, 32.dp, 120.dp, 40.dp, 14.dp, 24.dp),
    /** 보조 */
    Small(64.dp, 24.dp, 100.dp, 32.dp, 12.dp, 16.dp),
}

/** Filled: 주 버튼 (button/filled). Basic: 보조 버튼 (button/basic). Danger: 보조 바탕 + 위험 글자 */
enum class ButtonKind { Filled, Basic, Danger }

/**
 * 공통 버튼. 상태: 기본 / 눌림(Pressed 색) / 비활성(Disabled 색, 터치 안 됨) / 로딩(버튼 안 로더, 터치 안 됨).
 * 서버를 부르는 버튼은 응답 전까지 loading = true. 모든 탭에 햅틱.
 */
@Composable
fun HmtmButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    size: ButtonSize = ButtonSize.Medium,
    kind: ButtonKind = ButtonKind.Basic,
    icon: ImageVector? = null,
    enabled: Boolean = true,
    loading: Boolean = false,
) {
    val c = Hmtm.colors
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val active = enabled && !loading
    val (bg, fg) = buttonColors(c, kind, active || loading, pressed)
    Row(
        modifier
            .heightIn(min = size.height)
            .widthIn(min = size.minWidth)
            .clip(RoundedCornerShape(size.radius))
            .background(bg)
            .tap(enabled = active, interaction = interaction, onClick = onClick)
            .padding(PaddingValues(horizontal = size.padH, vertical = 8.dp)),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (loading) {
            CircularProgressIndicator(Modifier.size(size.icon * 0.7f), color = fg, strokeWidth = 4.dp)
            Spacer(Modifier.width(size.gap))
        } else if (icon != null) {
            Icon(icon, null, Modifier.size(size.icon), tint = fg)
            Spacer(Modifier.width(size.gap))
        }
        Text(
            text, style = Hmtm.type.bodyStrong, color = fg, textAlign = TextAlign.Center,
            maxLines = 2, overflow = TextOverflow.Ellipsis,
        )
    }
}

/** (바탕, 글자) 색. 로딩 중에는 비활성 색을 쓰지 않고 그대로 둔다 */
internal fun buttonColors(c: HmtmColors, kind: ButtonKind, enabled: Boolean, pressed: Boolean): Pair<Color, Color> =
    when {
        !enabled -> c.buttonDisabled to c.textDisabled
        kind == ButtonKind.Filled -> (if (pressed) c.filledPressed else c.filled) to c.onFilled
        kind == ButtonKind.Danger -> (if (pressed) c.basicPressed else c.basic) to c.dangerText
        else -> (if (pressed) c.basicPressed else c.basic) to c.text
    }

/** 아이콘만 있는 버튼 (뒤로 가기만): 80×80 원형 */
@Composable
fun HmtmIconButton(
    icon: ImageVector,
    contentDescription: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    size: Dp = HmtmDimens.iconButton,
    tint: Color = Hmtm.colors.text,
    enabled: Boolean = true,
) {
    val c = Hmtm.colors
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    Box(
        modifier
            .size(size)
            .clip(CircleShape)
            .background(if (pressed) c.basicPressed else c.basic)
            .tap(enabled = enabled, interaction = interaction, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(icon, contentDescription, Modifier.size(size / 2), tint = if (enabled) tint else c.textDisabled)
    }
}

/** 화면 위 제목 줄 (page_navigation): 뒤로 + 제목 (+ 보조 문구, 오른쪽 칸) */
@Composable
fun ScreenHeader(
    title: String,
    onBack: (() -> Unit)?,
    subtitle: String? = null,
    trailing: @Composable RowScope.() -> Unit = {},
) {
    Row(Modifier.fillMaxWidth().heightIn(min = HmtmDimens.headerHeight), verticalAlignment = Alignment.CenterVertically) {
        if (onBack != null) {
            HmtmIconButton(HmtmIcons.Back, stringResource(R.string.back), onBack)
            Spacer(Modifier.width(HmtmDimens.headerGap))
        }
        Column(Modifier.weight(1f)) {
            Text(title, style = Hmtm.type.title, color = Hmtm.colors.text, maxLines = 2, overflow = TextOverflow.Ellipsis)
            if (subtitle != null) {
                Text(subtitle, style = Hmtm.type.label, color = Hmtm.colors.textSecondary, maxLines = 2,
                    overflow = TextOverflow.Ellipsis)
            }
        }
        trailing()
    }
}

// ---------- 배지 ----------

/** 배지 색 갈래 (docs/pleos-design-rules.md 4절 배지 표) */
enum class BadgeTone { Vehicle, Video, User, Assumed }

/**
 * 배지 방식 (docs/app-ui.md 1절 "배지 두 방식").
 * Color: 갈래마다 다른 바탕색 + 글자 (지금 방식). Icon: 모두 같은 회색 바탕 + 갈래 아이콘 + 글자 (색에 기대지 않음).
 */
enum class BadgeStyle { Color, Icon }

/** 앱 전체 배지 방식. 바꾸려면 이 상수 하나만 (기본 Color) */
val BADGE_STYLE = BadgeStyle.Color

/** 미리보기·화면 캡처용으로 한 화면만 바꿀 때 */
val LocalBadgeStyle = staticCompositionLocalOf { BADGE_STYLE }

/** 아이콘 방식의 기본 아이콘: 차량 기록 = 차, 영상 = 카메라, 내 답변 = 사람, 가정·추정 = 물음표 */
val BadgeTone.icon: ImageVector
    get() = when (this) {
        BadgeTone.Vehicle -> HmtmIcons.Car
        BadgeTone.Video -> HmtmIcons.Video
        BadgeTone.User -> HmtmIcons.Person
        BadgeTone.Assumed -> HmtmIcons.Unknown
    }

@Composable
fun BadgeTone.colors(): Pair<Color, Color> {
    val c = Hmtm.colors
    return when (this) {
        BadgeTone.Vehicle -> c.vehicleBg to c.vehicleFg
        BadgeTone.Video -> c.videoBg to c.videoFg
        BadgeTone.User -> c.userBg to c.userFg
        BadgeTone.Assumed -> c.assumedBg to c.assumedFg
    }
}

/** 출처 (판단 근거 배지) */
enum class Source(@StringRes val label: Int, val tone: BadgeTone) {
    VEHICLE(R.string.source_vehicle, BadgeTone.Vehicle),
    /** 내 차 종류 (차량 정보). 기록이 아니라 입증 대상이 아님 */
    INFO(R.string.source_info, BadgeTone.Vehicle),
    VIDEO(R.string.source_video, BadgeTone.Video),
    USER(R.string.source_user, BadgeTone.User),
    /** 기본값으로 채운 값 */
    DEFAULT(R.string.source_default, BadgeTone.Assumed),
    /** 영상·차량 기록 추정값으로 채운 값 (answers[].basis == guess, other_cls.source == guess) */
    GUESS(R.string.source_guess, BadgeTone.Assumed);

    /** 다르면 결과가 바뀔 수 있는 출처 */
    val assumed get() = this == DEFAULT || this == GUESS

    companion object {
        fun of(api: String?): Source = when (api) {
            "vehicle" -> VEHICLE
            "vehicle_info" -> INFO
            "video" -> VIDEO
            "user" -> USER
            "guess" -> GUESS
            else -> DEFAULT
        }
    }
}

/** 출처 배지: 최소 폭 100, 둥글기 12, Label/Small */
@Composable
fun SourceBadge(source: Source, modifier: Modifier = Modifier) {
    Badge(stringResource(source.label), source.tone, modifier.widthIn(min = HmtmDimens.badgeMinWidth))
}

/** 배지. [icon]은 아이콘 방식에서만 쓰고, 없으면 갈래 아이콘 ([BadgeTone.icon]) */
@Composable
fun Badge(text: String, tone: BadgeTone, modifier: Modifier = Modifier, icon: ImageVector? = null) {
    if (LocalBadgeStyle.current == BadgeStyle.Icon) {
        IconBadge(text, icon ?: tone.icon, modifier)
    } else {
        val (bg, fg) = tone.colors()
        Pill(text, bg, fg, modifier)
    }
}

/** 아이콘 방식 배지: 회색 바탕(surfaceHigh) + 아이콘 24 + Label/Small, 글자·아이콘 textSecondary (대비 시험에 있는 짝) */
@Composable
private fun IconBadge(text: String, icon: ImageVector, modifier: Modifier) {
    val c = Hmtm.colors
    Row(
        modifier
            .clip(RoundedCornerShape(HmtmDimens.badgeRadius))
            .background(c.surfaceHigh)
            .padding(start = 8.dp, end = 12.dp, top = 4.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center,
    ) {
        Icon(icon, null, Modifier.size(24.dp), tint = c.textSecondary)
        Spacer(Modifier.width(6.dp))
        Text(text, style = Hmtm.type.labelSmall, color = c.textSecondary, maxLines = 1)
    }
}

/** 글자 알약 (배지·상태 표시). 폭을 정하지 않으면 글자만큼 */
@Composable
fun Pill(text: String, bg: Color, fg: Color, modifier: Modifier = Modifier) {
    Box(
        modifier
            .clip(RoundedCornerShape(HmtmDimens.badgeRadius))
            .background(bg)
            .padding(horizontal = 12.dp, vertical = 6.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(text, style = Hmtm.type.labelSmall, color = fg, textAlign = TextAlign.Center, maxLines = 1)
    }
}

// ---------- 작은 표시 ----------

/** 번호 원 (영상 가져오기 단계 안내) */
@Composable
fun NumberCircle(n: Int) {
    Box(
        Modifier.size(48.dp).clip(CircleShape).background(Hmtm.colors.surfaceHigh),
        contentAlignment = Alignment.Center,
    ) {
        Text("$n", style = Hmtm.type.bodyStrong, color = Hmtm.colors.text)
    }
}

/** 상태 원 (분석 단계): 완료 = 초록 체크, 진행 = 파랑 테두리, 대기 = 회색 테두리 */
enum class StepState { Done, Active, Waiting }

@Composable
fun StepCircle(state: StepState) {
    val c = Hmtm.colors
    val m = Modifier.size(40.dp).clip(CircleShape)
    when (state) {
        StepState.Done -> Box(m.background(c.active), contentAlignment = Alignment.Center) {
            Icon(HmtmIcons.Check, null, Modifier.size(IconSize.Small), tint = c.thumbnail)
        }
        StepState.Active -> Box(m.border(4.dp, c.accent, CircleShape))
        StepState.Waiting -> Box(m.border(2.dp, c.textDisabled, CircleShape))
    }
}

/** 상태 점 (기록 중 = informative/active, 꺼짐 = 회색) */
@Composable
fun Dot(color: Color, size: Dp = 16.dp) {
    Box(Modifier.size(size).clip(CircleShape).background(color))
}

/** 스위치 (selections/switch/medium): 80 폭, 손잡이 32. 움직임 없이 바로 바뀐다 */
@Composable
fun HmtmSwitch(on: Boolean, modifier: Modifier = Modifier) {
    val c = Hmtm.colors
    val h = HmtmDimens.switchKnob + HmtmDimens.switchPad * 2
    Box(
        modifier.size(HmtmDimens.switchWidth, h).clip(RoundedCornerShape(HmtmDimens.switchRadius))
            .background(if (on) c.switchOn else c.switchOff)
            .padding(HmtmDimens.switchPad),
        contentAlignment = if (on) Alignment.CenterEnd else Alignment.CenterStart,
    ) {
        Box(Modifier.size(HmtmDimens.switchKnob).clip(RoundedCornerShape(8.dp)).background(if (on) c.knobOn else c.knobOff))
    }
}

/** 체크 상자 (selections/checkbox): 48, 둥글기 12 */
@Composable
fun HmtmCheckRow(text: String, checked: Boolean, enabled: Boolean, onChange: (Boolean) -> Unit) {
    val c = Hmtm.colors
    val haptic = rememberHaptic()
    Row(
        Modifier.fillMaxWidth().heightIn(min = 64.dp).clip(RoundedCornerShape(HmtmDimens.rowRadius))
            .toggleable(checked, enabled = enabled, role = Role.Checkbox, indication = null,
                interactionSource = remember { MutableInteractionSource() }) { haptic(); onChange(it) },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(48.dp).clip(RoundedCornerShape(12.dp))
                .then(if (checked) Modifier.background(c.filled) else Modifier.border(4.dp, c.textTertiary, RoundedCornerShape(12.dp))),
            contentAlignment = Alignment.Center,
        ) {
            if (checked) Icon(HmtmIcons.Check, null, Modifier.size(IconSize.Small), tint = c.onFilled)
        }
        Spacer(Modifier.width(HmtmDimens.gapMedium))
        Text(text, style = Hmtm.type.body, color = if (enabled) c.text else c.textDisabled)
    }
}

// ---------- 팝업·토스트 ----------

/**
 * 확인 팝업 (시스템 팝업 규격: 폭 808, 둥글기 48, 안 여백 48). 되돌릴 수 없는 일(삭제 등).
 * busy면 확인 버튼이 Loading이고 닫히지 않는다. extra: 문구 아래 더 넣을 것
 */
@Composable
fun ConfirmDialog(
    title: String,
    text: String,
    confirm: String,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
    busy: Boolean = false,
    error: String? = null,
    extra: @Composable ColumnScope.() -> Unit = {},
) {
    val c = Hmtm.colors
    Dialog(
        onDismissRequest = { if (!busy) onDismiss() },
        properties = DialogProperties(usePlatformDefaultWidth = false, dismissOnClickOutside = !busy),
    ) {
        Column(
            Modifier
                .padding(HmtmDimens.cardGap)
                .widthIn(max = HmtmDimens.popupWidth)
                .fillMaxWidth()
                .clip(RoundedCornerShape(HmtmDimens.popupRadius))
                .background(c.popup)
                .padding(HmtmDimens.popupPadding),
        ) {
            Text(title, style = Hmtm.type.title, color = c.text)
            Spacer(Modifier.height(HmtmDimens.gapMedium))
            Text(text, style = Hmtm.type.body, color = c.textSecondary)
            extra()
            if (error != null) {
                Spacer(Modifier.height(HmtmDimens.gapMedium))
                Text(error, style = Hmtm.type.body, color = c.dangerText)
            }
            Spacer(Modifier.height(HmtmDimens.popupPadding))
            Row(horizontalArrangement = Arrangement.spacedBy(HmtmDimens.gapMedium)) {
                HmtmButton(stringResource(R.string.cancel), onDismiss, Modifier.weight(1f), enabled = !busy)
                HmtmButton(confirm, onConfirm, Modifier.weight(1f), kind = ButtonKind.Danger, loading = busy)
            }
        }
    }
}

/** 토스트 (최대 폭 792, 둥글기 16, 좌우 40·위아래 24, 아래 간격 24). 화면 아래 가운데에 바로 나타나고 바로 사라진다 */
@Composable
fun BoxScope.HmtmToast(text: String?) {
    if (text == null) return
    val c = Hmtm.colors
    Box(
        Modifier
            .align(Alignment.BottomCenter)
            .padding(start = HmtmDimens.toastBottom, end = HmtmDimens.toastBottom, bottom = HmtmDimens.toastBottom)
            .widthIn(max = HmtmDimens.toastMaxWidth)
            .wrapContentSize()
            .clip(RoundedCornerShape(HmtmDimens.toastRadius))
            .background(c.filled)
            .padding(horizontal = HmtmDimens.toastPadH, vertical = HmtmDimens.toastPadV),
    ) {
        Text(text, style = Hmtm.type.body, color = c.onFilled, textAlign = TextAlign.Center)
    }
}
