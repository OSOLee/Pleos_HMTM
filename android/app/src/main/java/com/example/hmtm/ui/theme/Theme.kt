package com.example.hmtm.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.ExperimentalTextApi
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.hmtm.R

/**
 * Pleos Connect 색 토큰 (docs/pleos-design-rules.md 4절, docs/pleos-tokens.json `colors`).
 * 토큰 파일은 #RRGGBBAA, 여기는 Android 0xAARRGGBB.
 * 라이트·다크 두 벌이고 시스템 야간 모드를 따른다 (HmtmTheme).
 */
@Immutable
data class HmtmColors(
    val dark: Boolean,
    /** background/primary: 화면 바탕 */
    val background: Color,
    /** surface/basic: 카드 */
    val surface: Color,
    /** surface/high: 카드 안 강조 영역 (목록 행, 기준 상자) */
    val surfaceHigh: Color,
    /** background/popup: 팝업·토스트 바탕 */
    val popup: Color,
    /** text/dark/primary */
    val text: Color,
    /** text/dark/secondary (84%) */
    val textSecondary: Color,
    /** text/dark/tertiary (64%) */
    val textTertiary: Color,
    /** text/dark/quaternary (32%): 비활성 표시에만 */
    val textDisabled: Color,
    /** divider/secondary */
    val divider: Color,
    /** informative/positive: 진행 표시, 비율 막대, 그림의 내 차 (그래픽) */
    val accent: Color,
    /** 강조 글자 (내 차 과실 숫자). 다크의 informative/positive는 카드 위 대비 4.47:1이라 밝힌 값 (app-bb-notes 12절) */
    val accentText: Color,
    /** informative/active: 기록 중 점, 스위치 켬, 완료 표시 (그래픽) */
    val active: Color,
    /** regulation/red: 부딪힌 순간 선 등 그래픽 */
    val danger: Color,
    /** 삭제 글자·아이콘. 라이트의 regulation/red는 흰 바탕 대비 3.9:1이라 진하게 (app-bb-notes 12절) */
    val dangerText: Color,
    /** button/filled/enabled·pressed, text/light/primary: 주 버튼 */
    val filled: Color,
    val filledPressed: Color,
    val onFilled: Color,
    /** button/basic/enabled·pressed: 보조 버튼 */
    val basic: Color,
    val basicPressed: Color,
    /** button/filled/disabled */
    val buttonDisabled: Color,
    /** switch/on·off, knob */
    val switchOn: Color,
    val switchOff: Color,
    val knobOn: Color,
    val knobOff: Color,
    /** 그림·비율 막대의 상대 (basic/600) */
    val otherParty: Color,
    /** 영상 썸네일·재생 바탕 (static/dark/100) */
    val thumbnail: Color,
    /** overlay/default: 팝업 뒤 */
    val overlay: Color,
    /** 배지 (Pleos에 대응 토큰이 없는 HMTM 고유 요소, 4절 배지 표) */
    val vehicleBg: Color,
    val vehicleFg: Color,
    val videoBg: Color,
    val videoFg: Color,
    val assumedBg: Color,
    val assumedFg: Color,
) {
    /** 내 답변 배지: surface/high + text/dark/primary */
    val userBg get() = surfaceHigh
    val userFg get() = text
    /** 고른 보기 바탕 (차량 기록 배지 바탕과 같은 옅은 파랑) */
    val selectedBg get() = vehicleBg
    /** 썸네일·재생 바탕 위 글자 (static/light/100) */
    val onThumbnail get() = Color(0xFFFFFFFF)
    /** 주의 글자 ("정차 후 사용할 수 있어요", 추정·임시 표시) */
    val warningText get() = assumedFg

    companion object {
        fun light() = HmtmColors(
            dark = false,
            background = Color(0xFFF7F8FA),
            surface = Color(0xFFFFFFFF),
            surfaceHigh = Color(0xFFEDEEF2),
            popup = Color(0xFFFFFFFF),
            text = Color(0xFF131417),
            textSecondary = Color(0xD6131417),
            textTertiary = Color(0xA3131417),
            textDisabled = Color(0x52131417),
            divider = Color(0x1A131417),
            accent = Color(0xFF0064FF),
            accentText = Color(0xFF0064FF),
            active = Color(0xFF02C265),
            danger = Color(0xFFF62E24),
            dangerText = Color(0xFFB3201A),
            filled = Color(0xFF44464E),
            filledPressed = Color(0xFF313236),
            onFilled = Color(0xFFFFFFFF),
            basic = Color(0x0D131417),
            basicPressed = Color(0x1A131417),
            buttonDisabled = Color(0x0D131417),
            switchOn = Color(0xFF02C265),
            switchOff = Color(0x4D131417),
            knobOn = Color(0xFFFFFFFF),
            knobOff = Color(0xFFFFFFFF),
            otherParty = Color(0xFF44464E),
            thumbnail = Color(0xFF131417),
            overlay = Color(0x33131417),
            vehicleBg = Color(0xFFE7EEFF), vehicleFg = Color(0xFF1A47B8),
            videoBg = Color(0xFFE4F4EA), videoFg = Color(0xFF0B6B3A),
            assumedBg = Color(0xFFFFF1DC), assumedFg = Color(0xFF9A4A00),
        )

        fun dark() = HmtmColors(
            dark = true,
            background = Color(0xFF1D1E21),
            surface = Color(0xFF1D1E21),
            surfaceHigh = Color(0xFF313236),
            popup = Color(0xFF313236),
            text = Color(0xFFFFFFFF),
            textSecondary = Color(0xD6FFFFFF),
            textTertiary = Color(0xA3FFFFFF),
            textDisabled = Color(0x52FFFFFF),
            divider = Color(0x1AFFFFFF),
            accent = Color(0xFF0082FF),
            accentText = Color(0xFF3392FF),
            active = Color(0xFF00E074),
            danger = Color(0xFFFF4339),
            dangerText = Color(0xFFFF9F98),
            filled = Color(0xFFE0E1E6),
            filledPressed = Color(0xFFC7C9CE),
            onFilled = Color(0xFF131417),
            basic = Color(0x0DFFFFFF),
            basicPressed = Color(0x1AFFFFFF),
            buttonDisabled = Color(0x0DFFFFFF),
            switchOn = Color(0xFF00E074),
            switchOff = Color(0x1AFFFFFF),
            knobOn = Color(0xFFFFFFFF),
            knobOff = Color(0xFFA4A8AE),
            otherParty = Color(0xFFE0E1E6),
            thumbnail = Color(0xFF131417),
            overlay = Color(0x80131417),
            vehicleBg = Color(0xFF1E2A4A), vehicleFg = Color(0xFFA9C1FF),
            videoBg = Color(0xFF173226), videoFg = Color(0xFF8FD9AE),
            assumedBg = Color(0xFF3A2A14), assumedFg = Color(0xFFFFC27A),
        )
    }
}

/** Asta Sans (가변 글꼴 하나를 굵기별로). 파일이 없으면 시스템 기본 */
@OptIn(ExperimentalTextApi::class)
val AstaSans: FontFamily = runCatching {
    FontFamily(
        Font(R.font.asta_sans, FontWeight.Normal, variationSettings = FontVariation.Settings(FontVariation.weight(400))),
        Font(R.font.asta_sans, FontWeight.Bold, variationSettings = FontVariation.Settings(FontVariation.weight(700))),
        Font(R.font.asta_sans, FontWeight.ExtraBold, variationSettings = FontVariation.Settings(FontVariation.weight(800))),
    )
}.getOrDefault(FontFamily.Default)

private fun style(size: Int, line: Int, weight: FontWeight, family: FontFamily) =
    TextStyle(fontFamily = family, fontSize = size.sp, lineHeight = line.sp, fontWeight = weight)

/**
 * 글자 단계 (docs/pleos-design-rules.md 3절, Connect-S). 이 밖의 크기는 만들지 않는다.
 * 같은 크기의 Normal/Strong 짝은 Pleos 스타일에 있는 것만 (Body/Small/Strong).
 */
@Immutable
data class HmtmType(
    /** Headline/Large/Extra_Strong 60/80 (ExtraBold 800): 과실비율 숫자 — 화면에서 가장 먼저 읽히는 값 */
    val headline: TextStyle,
    /** Title/Small/Strong 32/40: 화면 제목 */
    val title: TextStyle,
    /** Body/Large/Strong 30/38: 카드 제목, 질문 문장 */
    val cardTitle: TextStyle,
    /** Body/Medium/Strong 28/36: 강조 본문, 버튼·선택지 글자 */
    val bodyStrong: TextStyle,
    /** Body/Small/Normal 26/34: 본문 */
    val body: TextStyle,
    /** Body/Small/Strong 26/34: 본문 안 강조 */
    val bodyBold: TextStyle,
    /** Label/Medium 24/28: 보조 (설명, 축 글자) */
    val label: TextStyle,
    /** Label/Small 20/24: 최소 (배지, 작은 표시) */
    val labelSmall: TextStyle,
) {
    companion object {
        fun of(family: FontFamily = AstaSans) = HmtmType(
            headline = style(60, 80, FontWeight.ExtraBold, family),
            title = style(32, 40, FontWeight.Bold, family),
            cardTitle = style(30, 38, FontWeight.Bold, family),
            bodyStrong = style(28, 36, FontWeight.Bold, family),
            body = style(26, 34, FontWeight.Normal, family),
            bodyBold = style(26, 34, FontWeight.Bold, family),
            label = style(24, 28, FontWeight.Normal, family),
            labelSmall = style(20, 24, FontWeight.Normal, family),
        )

        /** 쓰는 글자 크기 (sp). 단위 시험이 이 밖의 크기를 막는다 */
        val SIZES: Set<TextUnit> = setOf(60.sp, 32.sp, 30.sp, 28.sp, 26.sp, 24.sp, 20.sp)
    }
}

/** 모양·크기 (docs/pleos-design-rules.md 5절, Connect-S). 단위 dp */
object HmtmDimens {
    val screenPadding = 40.dp          // page_navigation/padding_extralarge
    val cardGap = 24.dp                // page_navigation/gap_large
    val cardPadding = 32.dp            // notification/padding_large
    val cardRadius = 16.dp             // radius level5
    val rowRadius = 12.dp              // radius level4
    val rowPadH = 24.dp
    val rowPadV = 16.dp
    val gapSmall = 12.dp
    val gapMedium = 16.dp

    /** 화면 상단 제목 줄 (page_navigation): 높이 80, 앞 아이콘 56, 간격 24 */
    val headerHeight = 80.dp
    val headerGap = 24.dp

    /** 아이콘 버튼 (뒤로 가기) 80×80, 작은 것 64×64, 원형 */
    val iconButton = 80.dp
    val iconButtonSmall = 64.dp
    val iconButtonGlyph = 40.dp

    /** 시스템 팝업: 폭 808(중간)·1200(큰), 둥글기 48, 안 여백 48, 아이콘 80 */
    val popupWidth = 808.dp
    val popupRadius = 48.dp
    val popupPadding = 48.dp
    val popupGap = 24.dp

    /** 토스트: 최대 폭 792, 둥글기 16, 좌우 40, 위아래 24, 아래 간격 24 */
    val toastMaxWidth = 792.dp
    val toastRadius = 16.dp
    val toastPadH = 40.dp
    val toastPadV = 24.dp
    val toastBottom = 24.dp

    /** 배지 */
    val badgeRadius = 12.dp
    val badgeMinWidth = 100.dp

    /** 스위치 (selections/switch/medium): 폭 80, 손잡이 32, 안 여백 8, 둥글기 16 */
    val switchWidth = 80.dp
    val switchKnob = 32.dp
    val switchPad = 8.dp
    val switchRadius = 16.dp
}

val LocalHmtmColors = staticCompositionLocalOf { HmtmColors.light() }
val LocalHmtmType = staticCompositionLocalOf { HmtmType.of(FontFamily.Default) }

object Hmtm {
    val colors: HmtmColors @Composable get() = LocalHmtmColors.current
    val type: HmtmType @Composable get() = LocalHmtmType.current
}

/** 시스템 야간 모드를 따른다 (darkTheme을 넘기면 그 값) */
@Composable
fun HmtmTheme(darkTheme: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    val c = if (darkTheme) HmtmColors.dark() else HmtmColors.light()
    val type = HmtmType.of()
    val base = if (darkTheme) darkColorScheme() else lightColorScheme()
    val scheme = base.copy(
        primary = c.accent,
        onPrimary = Color.White,
        background = c.background,
        onBackground = c.text,
        surface = c.surface,
        onSurface = c.text,
        onSurfaceVariant = c.textSecondary,
        outline = c.divider,
        error = c.dangerText,
    )
    CompositionLocalProvider(
        LocalHmtmColors provides c,
        LocalHmtmType provides type,
    ) {
        MaterialTheme(
            colorScheme = scheme,
            typography = Typography(bodyLarge = type.body, bodyMedium = type.body, labelLarge = type.bodyStrong),
            shapes = Shapes(
                small = RoundedCornerShape(HmtmDimens.rowRadius),
                medium = RoundedCornerShape(HmtmDimens.rowRadius),
                large = RoundedCornerShape(HmtmDimens.cardRadius),
            ),
            content = content,
        )
    }
}
