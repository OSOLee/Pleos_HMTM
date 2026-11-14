package com.example.hmtm.ui.player

import android.content.Context
import android.graphics.Bitmap
import android.media.MediaMetadataRetriever
import android.media.MediaPlayer
import android.net.Uri
import android.widget.VideoView
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.example.hmtm.R
import com.example.hmtm.ui.Format
import com.example.hmtm.ui.LocalWide
import com.example.hmtm.ui.components.ButtonKind
import com.example.hmtm.ui.components.ButtonSize
import com.example.hmtm.ui.components.CardTitle
import com.example.hmtm.ui.components.HmtmButton
import com.example.hmtm.ui.components.HmtmCard
import com.example.hmtm.ui.components.HmtmIcons
import com.example.hmtm.ui.components.IconSize
import com.example.hmtm.ui.components.ScreenHeader
import com.example.hmtm.ui.theme.Hmtm
import com.example.hmtm.ui.theme.HmtmDimens
import kotlinx.coroutines.delay
import java.util.Locale

/** 영상 다시 보기 상태: 기기의 원본(content://) + 사고 순간(초). pick이 있으면 사고 순간 고르기 화면 */
data class PlayerState(
    val uri: Uri? = null,
    val collisionT: Double? = null,
    val checking: Boolean = false,
    /** 열 수 없음 (USB를 뺐거나 읽기 권한이 끊김, 이 기기에 주소가 없음) */
    val error: String? = null,
    val pick: PickMode? = null,
)

/**
 * 사고 순간 고르기 (design-blackbox 3.2·3.6). 영상에서 멈춘 시점을 고르면(chosenMs) 그 화면을 크게 보여 주는 확인 단계,
 * 확인하면 PUT collision. candidates: 분석기가 찾은 후보(초)
 */
data class PickMode(
    val caseId: String,
    val candidates: List<Double>,
    val chosenMs: Int? = null,
    val frame: ImageBitmap? = null,
    val frameLoading: Boolean = false,
    val sending: Boolean = false,
    val error: String? = null,
    /** 확인 단계에서 돌아왔을 때 이어 볼 위치 */
    val resumeMs: Int? = null,
)

object Replay {
    const val LEAD_S = 3.0
    const val MSG_UNAVAILABLE = "영상을 열 수 없어요. USB를 다시 연결해 주세요"

    /** 사고 순간 3초 전부터 (영상 처음보다 앞이면 0) */
    fun startMs(collisionT: Double?): Int =
        if (collisionT == null || collisionT.isNaN()) 0 else ((collisionT - LEAD_S).coerceAtLeast(0.0) * 1000).toInt()

    /** "0:18" */
    fun clock(ms: Int): String = String.format(Locale.US, "%d:%02d", ms / 60_000, (ms / 1000) % 60)

    /** 고르기 화면 시각 "0:18.2" (0.1초까지) */
    fun clockTenth(ms: Int): String = String.format(Locale.US, "%d:%02d.%d", ms / 60_000, (ms / 1000) % 60, (ms % 1000) / 100)

    /** 앞뒤로 옮긴 위치 (0 ~ 길이) */
    fun step(now: Int, deltaMs: Int, duration: Int): Int = (now + deltaMs).coerceIn(0, maxOf(0, duration))
}

/** 확인 단계에 크게 보여 줄 그 순간의 화면 */
object Frames {
    private const val MAX_SIDE = 1600

    fun at(ctx: Context, uri: Uri, ms: Int): ImageBitmap? = try {
        val r = MediaMetadataRetriever()
        try {
            r.setDataSource(ctx, uri)
            val b = r.getFrameAtTime(ms * 1000L, MediaMetadataRetriever.OPTION_CLOSEST) ?: return null
            val scale = MAX_SIDE.toFloat() / maxOf(b.width, b.height)
            val out = if (scale < 1f) Bitmap.createScaledBitmap(b, (b.width * scale).toInt(), (b.height * scale).toInt(), true) else b
            out.asImageBitmap()
        } finally {
            r.release()
        }
    } catch (e: Exception) {   // USB를 뺐거나 권한이 끊김
        null
    }
}

/**
 * 결과 화면 "영상 다시 보기"와 "사고 순간 고르기": 서버는 판정 뒤 영상을 지우므로 기기에 있는 원본을 앱 안에서 재생한다
 * (설계 3.2, Q13). 추가 라이브러리 없이 android.widget.VideoView. 사고 순간 3초 전부터 시작.
 */
@Composable
fun PlayerScreen(
    state: PlayerState,
    driving: Boolean,
    onBack: () -> Unit,
    onRetry: () -> Unit,
    onError: () -> Unit,
    onChoose: (Int) -> Unit = {},
    onUnchoose: () -> Unit = {},
    onConfirm: () -> Unit = {},
) {
    val c = Hmtm.colors
    val pick = state.pick
    Column(
        Modifier.fillMaxSize().background(c.background).padding(HmtmDimens.screenPadding),
        verticalArrangement = Arrangement.spacedBy(HmtmDimens.cardGap),
    ) {
        ScreenHeader(
            stringResource(if (pick != null) R.string.pick_title else R.string.result_replay), onBack,
            subtitle = when {
                pick != null -> stringResource(R.string.pick_help)
                else -> state.collisionT?.let { stringResource(R.string.player_moment, Format.seconds(it)) }
            },
        )
        val uri = state.uri
        when {
            state.error != null || uri == null -> Message(state.error ?: Replay.MSG_UNAVAILABLE, if (uri != null) onRetry else null)
            state.checking -> Message(stringResource(R.string.player_opening), null)
            pick?.chosenMs != null -> Confirm(pick, driving, onUnchoose, onConfirm, Modifier.fillMaxWidth().weight(1f))
            else -> Video(
                uri, state.collisionT, pick, driving, onError, onChoose, Modifier.fillMaxWidth().weight(1f),
            )
        }
    }
}

@Composable
private fun Message(text: String, onRetry: (() -> Unit)?) {
    val c = Hmtm.colors
    Box(Modifier.fillMaxSize().clip(RoundedCornerShape(HmtmDimens.cardRadius)).background(c.surface), contentAlignment = Alignment.Center) {
        Column(Modifier.padding(HmtmDimens.cardPadding), horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(HmtmIcons.Usb, null, Modifier.size(IconSize.Large), tint = c.textSecondary)
            Spacer(Modifier.height(HmtmDimens.gapMedium))
            Text(text, style = Hmtm.type.bodyStrong, color = c.text, textAlign = TextAlign.Center)
            if (onRetry != null) {
                Spacer(Modifier.height(HmtmDimens.cardGap))
                HmtmButton(stringResource(R.string.player_reopen), onRetry, icon = HmtmIcons.Refresh)
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Video(
    uri: Uri,
    collisionT: Double?,
    pick: PickMode?,
    driving: Boolean,
    onError: () -> Unit,
    onChoose: (Int) -> Unit,
    modifier: Modifier,
) {
    val c = Hmtm.colors
    var view by remember { mutableStateOf<VideoView?>(null) }
    var player by remember { mutableStateOf<MediaPlayer?>(null) }
    var playing by remember { mutableStateOf(false) }
    var position by remember { mutableIntStateOf(0) }
    var duration by remember { mutableIntStateOf(0) }
    val momentMs = Replay.startMs(collisionT)
    // 고르기: 확인 단계에서 돌아오면 고른 자리, 처음이면 첫 후보에서 멈춘 채로 (재생하면 지나가 버림)
    val startMs = pick?.resumeMs ?: pick?.candidates?.firstOrNull()?.let { (it * 1000).toInt() } ?: momentMs
    /** 영상이 준비되기 전에는 옮기기·고르기를 막음 (준비 전 위치는 0이라 0.1초를 고르게 됨) */
    val ready = duration > 0

    /** 그 위치로 옮기고 멈춤 (고르기: 프레임 단위로 정확히) */
    fun seekPaused(ms: Int) {
        val v = view ?: return
        if (v.isPlaying) v.pause()
        playing = false
        val mp = player
        if (mp != null) mp.seekTo(ms.toLong(), MediaPlayer.SEEK_CLOSEST) else v.seekTo(ms)
        position = ms
    }

    Box(modifier.clip(RoundedCornerShape(HmtmDimens.cardRadius)).background(c.thumbnail), contentAlignment = Alignment.Center) {
        AndroidView(
            factory = { ctx ->
                VideoView(ctx).apply {
                    setOnPreparedListener { mp ->
                        player = mp
                        duration = mp.duration
                        val at = startMs.coerceAtMost(maxOf(0, mp.duration - 500))
                        if (pick != null) {
                            // 고르기: 고른 위치·첫 후보에 멈춘 채로
                            mp.seekTo(at.toLong(), MediaPlayer.SEEK_CLOSEST)
                            position = at
                        } else {
                            seekTo(at)
                            start()
                            playing = true
                        }
                    }
                    setOnCompletionListener { playing = false }
                    setOnErrorListener { _, _, _ ->
                        playing = false
                        onError()
                        true
                    }
                    setVideoURI(uri)
                    view = this
                }
            },
            modifier = Modifier.fillMaxSize(),
        )
    }
    DisposableEffect(uri) {
        onDispose { view?.stopPlayback() }
    }
    LaunchedEffect(view) {
        while (true) {
            view?.let { if (it.isPlaying || playing) position = it.currentPosition }
            delay(100)
        }
    }
    // 영상 재생은 정차 중에만 여는 화면 (결과 화면은 정차 중 사용, 2절). 고르기는 주행 중이면 "고르기"만 잠금
    FlowRow(
        verticalArrangement = Arrangement.spacedBy(HmtmDimens.gapMedium),
        horizontalArrangement = Arrangement.spacedBy(HmtmDimens.gapMedium),
    ) {
        HmtmButton(
            stringResource(if (playing) R.string.player_pause else R.string.player_play),
            {
                view?.let {
                    if (it.isPlaying) it.pause() else it.start()
                    playing = it.isPlaying
                }
            },
            icon = if (playing) HmtmIcons.Pause else HmtmIcons.Play, enabled = ready,
        )
        if (pick == null) {
            HmtmButton(stringResource(R.string.player_to_moment), {
                view?.let {
                    it.seekTo(momentMs)
                    it.start()
                    playing = true
                }
            }, enabled = collisionT != null, icon = HmtmIcons.Target)
            HmtmButton(stringResource(R.string.player_from_start), {
                view?.let {
                    it.seekTo(0)
                    it.start()
                    playing = true
                }
            }, icon = HmtmIcons.Replay)
        } else {
            for ((label, d) in listOf(
                R.string.pick_back_1 to -1000, R.string.pick_back_02 to -200,
                R.string.pick_fwd_02 to 200, R.string.pick_fwd_1 to 1000,
            )) {
                HmtmButton(stringResource(label), { seekPaused(Replay.step(position, d, duration)) }, enabled = ready)
            }
        }
        Text(
            if (pick != null) "${Replay.clockTenth(position)} / ${Replay.clock(duration)}"
            else "${Replay.clock(position)} / ${Replay.clock(duration)}",
            Modifier.align(Alignment.CenterVertically),
            style = Hmtm.type.bodyStrong, color = c.text,
        )
    }
    if (pick != null) {
        FlowRow(
            verticalArrangement = Arrangement.spacedBy(HmtmDimens.gapMedium),
            horizontalArrangement = Arrangement.spacedBy(HmtmDimens.gapMedium),
        ) {
            if (pick.candidates.isNotEmpty()) {
                Text(
                    stringResource(R.string.pick_candidates), Modifier.align(Alignment.CenterVertically),
                    style = Hmtm.type.label, color = c.textSecondary,
                )
                pick.candidates.forEach { t ->
                    HmtmButton(
                        stringResource(R.string.pick_candidate, Format.seconds(t)), { seekPaused((t * 1000).toInt()) },
                        size = ButtonSize.Small, icon = HmtmIcons.Target, enabled = ready,
                    )
                }
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (driving) {
                Text(stringResource(R.string.stop_first), Modifier.weight(1f), style = Hmtm.type.bodyStrong, color = c.warningText)
            } else {
                Spacer(Modifier.weight(1f))
            }
            HmtmButton(
                stringResource(R.string.pick_this), {
                    view?.let { if (it.isPlaying) it.pause() }
                    playing = false
                    onChoose(view?.currentPosition ?: position)
                },
                size = ButtonSize.Large, kind = ButtonKind.Filled, icon = HmtmIcons.Check, enabled = !driving && ready,
            )
        }
    }
}

/** 확인 단계: 고른 시점의 화면을 크게 + "이 순간이 맞나요?" + 판정되면 영상이 지워진다는 안내 */
@Composable
private fun Confirm(pick: PickMode, driving: Boolean, onBack: () -> Unit, onConfirm: () -> Unit, modifier: Modifier) {
    val c = Hmtm.colors
    val wide = LocalWide.current
    val frame: @Composable (Modifier) -> Unit = { m ->
        Box(m.clip(RoundedCornerShape(HmtmDimens.cardRadius)).background(c.thumbnail), contentAlignment = Alignment.Center) {
            val f = pick.frame
            when {
                f != null -> Image(f, null, Modifier.fillMaxSize(), contentScale = ContentScale.Fit)
                pick.frameLoading -> Text(stringResource(R.string.loading), style = Hmtm.type.body, color = c.onThumbnail)
                else -> Text(stringResource(R.string.pick_frame_failed), style = Hmtm.type.body, color = c.onThumbnail)
            }
        }
    }
    if (wide) {
        Row(modifier, horizontalArrangement = Arrangement.spacedBy(HmtmDimens.cardGap)) {
            frame(Modifier.weight(3f).fillMaxHeight())
            HmtmCard(Modifier.weight(2f).fillMaxHeight()) {
                ConfirmPanel(pick, driving, onBack, onConfirm)
            }
        }
    } else {
        Column(modifier, verticalArrangement = Arrangement.spacedBy(HmtmDimens.cardGap)) {
            frame(Modifier.fillMaxWidth().weight(1f))
            HmtmCard(Modifier.fillMaxWidth()) {
                ConfirmPanel(pick, driving, onBack, onConfirm)
            }
        }
    }
}

@Composable
private fun ColumnScope.ConfirmPanel(pick: PickMode, driving: Boolean, onBack: () -> Unit, onConfirm: () -> Unit) {
    val c = Hmtm.colors
    Column(Modifier.weight(1f, fill = false).verticalScroll(rememberScrollState())) {
        CardTitle(stringResource(R.string.pick_confirm_title))
        Spacer(Modifier.height(HmtmDimens.gapSmall))
        Text(
            stringResource(R.string.pick_confirm_time, Format.seconds((pick.chosenMs ?: 0) / 1000.0)),
            style = Hmtm.type.headline, color = c.accentText,
        )
        Spacer(Modifier.height(HmtmDimens.gapMedium))
        Column(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(HmtmDimens.rowRadius)).background(c.assumedBg)
                .padding(horizontal = HmtmDimens.rowPadH, vertical = HmtmDimens.rowPadV),
        ) {
            Row(verticalAlignment = Alignment.Top) {
                Icon(HmtmIcons.Warning, null, Modifier.size(IconSize.Small), tint = c.assumedFg)
                Spacer(Modifier.width(HmtmDimens.gapSmall))
                Text(stringResource(R.string.pick_confirm_warn), style = Hmtm.type.body, color = c.assumedFg)
            }
        }
        if (pick.error != null) {
            Spacer(Modifier.height(HmtmDimens.gapMedium))
            Text(pick.error, style = Hmtm.type.bodyBold, color = c.dangerText)
        }
        if (driving) {
            Spacer(Modifier.height(HmtmDimens.gapMedium))
            Text(stringResource(R.string.stop_first), style = Hmtm.type.bodyStrong, color = c.warningText)
        }
    }
    Spacer(Modifier.height(HmtmDimens.cardGap))
    HmtmButton(
        stringResource(R.string.pick_confirm_yes), onConfirm, Modifier.fillMaxWidth(),
        size = ButtonSize.Large, kind = ButtonKind.Filled, icon = HmtmIcons.Check,
        enabled = !driving, loading = pick.sending,
    )
    Spacer(Modifier.height(HmtmDimens.gapMedium))
    HmtmButton(
        stringResource(R.string.pick_confirm_back), onBack, Modifier.fillMaxWidth(),
        icon = HmtmIcons.Replay, enabled = !pick.sending,
    )
}
