package com.example.hmtm.ui.components

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.ArrowForward
import androidx.compose.material.icons.automirrored.outlined.DirectionsWalk
import androidx.compose.material.icons.automirrored.outlined.HelpOutline
import androidx.compose.material.icons.automirrored.outlined.ShowChart
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.DirectionsBus
import androidx.compose.material.icons.filled.DirectionsCar
import androidx.compose.material.icons.filled.LocalShipping
import androidx.compose.material.icons.filled.PedalBike
import androidx.compose.material.icons.filled.TwoWheeler
import androidx.compose.material.icons.filled.Agriculture
import androidx.compose.material.icons.automirrored.filled.DirectionsWalk
import androidx.compose.material.icons.filled.North
import androidx.compose.material.icons.filled.South
import androidx.compose.material.icons.filled.East
import androidx.compose.material.icons.filled.West
import androidx.compose.material.icons.outlined.Agriculture
import androidx.compose.material.icons.outlined.ArrowDownward
import androidx.compose.material.icons.outlined.ArrowUpward
import androidx.compose.material.icons.outlined.CenterFocusWeak
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.DirectionsBus
import androidx.compose.material.icons.outlined.DirectionsCar
import androidx.compose.material.icons.outlined.East
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.History
import androidx.compose.material.icons.outlined.LocalShipping
import androidx.compose.material.icons.outlined.North
import androidx.compose.material.icons.outlined.Pause
import androidx.compose.material.icons.outlined.PedalBike
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.PlayArrow
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Replay
import androidx.compose.material.icons.outlined.South
import androidx.compose.material.icons.outlined.SwapHoriz
import androidx.compose.material.icons.outlined.TwoWheeler
import androidx.compose.material.icons.outlined.Usb
import androidx.compose.material.icons.outlined.Videocam
import androidx.compose.material.icons.outlined.WarningAmber
import androidx.compose.material.icons.outlined.West
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp

/**
 * 앱 아이콘 한 계열 (docs/app-ui.md 1절 "아이콘"): Material Icons (Material Symbols와 같은 24dp 격자·모양).
 * 기본은 Outlined, 선택·켜짐(고른 보기, 체크)만 Filled. 색은 Icon(tint=)으로, 크기는 [IconSize] (버튼 규격).
 * 아이콘만 있는 버튼은 뒤로 가기만 (Back).
 */
object HmtmIcons {
    val Back = Icons.AutoMirrored.Outlined.ArrowBack
    val ArrowRight = Icons.AutoMirrored.Outlined.ArrowForward
    /** 지난 분석 */
    val History = Icons.Outlined.History
    val Warning = Icons.Outlined.WarningAmber
    val Play = Icons.Outlined.PlayArrow
    val Pause = Icons.Outlined.Pause
    /** 체크 상자 안·완료 표시 (켜짐이라 Filled) */
    val Check = Icons.Filled.Check
    val Usb = Icons.Outlined.Usb
    val Video = Icons.Outlined.Videocam
    val Refresh = Icons.Outlined.Refresh
    /** 처음부터·다시 고르기 */
    val Replay = Icons.Outlined.Replay
    /** 사고 순간 (고르기, 사고 순간으로) */
    val Target = Icons.Outlined.CenterFocusWeak
    /** 기록 보기 (꺾은선) */
    val Chart = Icons.AutoMirrored.Outlined.ShowChart
    val Edit = Icons.Outlined.Edit
    val Trash = Icons.Outlined.Delete

    // ---------- 배지 (아이콘 방식, BadgeStyle.Icon) ----------
    val Car = Icons.Outlined.DirectionsCar
    val Person = Icons.Outlined.Person
    val Unknown = Icons.AutoMirrored.Outlined.HelpOutline
    val Up = Icons.Outlined.ArrowUpward
    val Down = Icons.Outlined.ArrowDownward
    val Swap = Icons.Outlined.SwapHoriz

    /** (기본 Outlined, 고름 Filled) */
    data class Pair(val outlined: ImageVector, val filled: ImageVector) {
        fun of(selected: Boolean) = if (selected) filled else outlined
    }

    /** 상대 종류 보기 (parties.other.cls 값) */
    private val CLS = mapOf(
        "car" to Pair(Icons.Outlined.DirectionsCar, Icons.Filled.DirectionsCar),
        "truck" to Pair(Icons.Outlined.LocalShipping, Icons.Filled.LocalShipping),
        "bus" to Pair(Icons.Outlined.DirectionsBus, Icons.Filled.DirectionsBus),
        "two_wheeler" to Pair(Icons.Outlined.TwoWheeler, Icons.Filled.TwoWheeler),
        "bicycle" to Pair(Icons.Outlined.PedalBike, Icons.Filled.PedalBike),
        "farm_machine" to Pair(Icons.Outlined.Agriculture, Icons.Filled.Agriculture),
        "pedestrian" to Pair(Icons.AutoMirrored.Outlined.DirectionsWalk, Icons.AutoMirrored.Filled.DirectionsWalk),
    )

    /** 상대가 온 방향 보기 (parties.other.entry_from 값, 내 차 기준): 왼쪽 ←, 오른쪽 →, 맞은편 ↑, 같은 방향(앞이나 뒤) ↓ */
    private val FROM = mapOf(
        "left" to Pair(Icons.Outlined.West, Icons.Filled.West),
        "right" to Pair(Icons.Outlined.East, Icons.Filled.East),
        "opposite" to Pair(Icons.Outlined.North, Icons.Filled.North),
        "same" to Pair(Icons.Outlined.South, Icons.Filled.South),
    )

    /** 질문 보기 아이콘 (상대 종류·온 방향만, 그 밖은 null) */
    fun option(field: String, value: Any?): Pair? = when {
        field == "parties.other.cls" -> CLS[value]
        field.endsWith(".entry_from") -> FROM[value]
        else -> null
    }
}

/** 아이콘 크기 = 버튼 규격의 아이콘 (pleos-design-rules 5절): 큰 52 / 중간 40 / 작은 32 */
object IconSize {
    val Large = 52.dp
    val Medium = 40.dp
    val Small = 32.dp
}
