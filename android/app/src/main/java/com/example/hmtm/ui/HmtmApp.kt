package com.example.hmtm.ui

import android.content.ActivityNotFoundException
import android.content.pm.PackageManager
import android.net.Uri
import androidx.activity.compose.ManagedActivityResultLauncher
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.example.hmtm.R
import com.example.hmtm.ui.components.HmtmToast
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.hmtm.MainActivity
import com.example.hmtm.service.Collector
import com.example.hmtm.ui.analyzing.AnalyzingScreen
import com.example.hmtm.ui.onboarding.OnboardingScreen
import com.example.hmtm.ui.player.PlayerScreen
import com.example.hmtm.ui.components.ConfirmDialog
import com.example.hmtm.ui.history.HistoryScreen
import com.example.hmtm.ui.history.SettingsCard
import com.example.hmtm.ui.home.HomeScreen
import com.example.hmtm.ui.importvideo.ImportScreen
import com.example.hmtm.ui.questions.QuestionScreen
import com.example.hmtm.ui.record.RecordScreen
import com.example.hmtm.ui.result.ResultScreen
import com.example.hmtm.ui.result.vehicleSummary

@Composable
fun HmtmApp(vm: AppViewModel = viewModel()) {
    val context = LocalContext.current
    val picker = rememberLauncherForActivityResult(vm.videoSource.contract) { vm.onPicked(it) }

    // 첫 실행 안내에서 동의한 뒤 속도 권한 → 거부해도 서비스는 시작 (속도 없이 Pleos 값만 기록)
    val askSpeed = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        Collector.startIfAllowed(context)
    }

    BackHandler(enabled = vm.screen != Screen.Home) { vm.back() }

    // 창 크기로 가로/세로 배치를 고른다 (기기 회전이 아님, pleos-design-rules 1절)
    BoxWithConstraints(Modifier.fillMaxSize()) {
        CompositionLocalProvider(LocalWide provides WindowShape.isWide(maxWidth.value, maxHeight.value)) {
            Screens(vm, picker, askSpeed)
        }
        HmtmToast(vm.toast)
    }
}

@Composable
private fun Screens(
    vm: AppViewModel,
    picker: ManagedActivityResultLauncher<Unit, Uri?>,
    askSpeed: ManagedActivityResultLauncher<String, Boolean>,
) {
    val context = LocalContext.current
    val cannotOpenPicker = stringResource(R.string.toast_no_picker)
    when (vm.screen) {
        Screen.Onboarding -> OnboardingScreen(
            onAgree = {
                vm.consent()
                if (context.checkSelfPermission(MainActivity.SPEED) == PackageManager.PERMISSION_GRANTED) {
                    Collector.startIfAllowed(context)
                } else {
                    askSpeed.launch(MainActivity.SPEED)
                }
            },
            onLater = vm::back,
        )
        Screen.Home -> HomeScreen(vm.home, onAnalyze = vm::openImport, onHistory = vm::openHistory)
        Screen.Import -> ImportScreen(
            vm.import, vm.driving,
            onBack = vm::back,
            onPick = {
                try {
                    picker.launch(Unit)
                } catch (e: ActivityNotFoundException) {
                    vm.showToast(cannotOpenPicker)
                }
            },
            onStart = vm::startAnalysis,
        )
        Screen.Analyzing -> AnalyzingScreen(vm.analyzing, onBack = vm::back, onRetry = vm::retry, onHome = vm::goHome)
        Screen.Result -> vm.result?.let { case ->
            val video = vm.resultVideo
            // 서버는 영상을 지우므로 기기의 원본을 앱 안에서 재생 (설계 3.2, Q13)
            ResultScreen(
                case, onBack = vm::back,
                onAnswer = vm::answerRemaining,
                onWrongCls = vm::askOtherCls,
                onEdit = if (vm.canEdit(case)) vm::editAnswers else null,
                onDelete = { vm.askDelete(case.id, case.accidentAt) },
                onReplay = if (video != null) vm::openPlayer else null,
                onRecord = if (case.timeline != null) vm::openRecord else null,
                onPick = if (case.review?.canPick == true) vm::openPick else null,
            )
        } ?: HomeScreen(vm.home, onAnalyze = vm::openImport, onHistory = vm::openHistory)
        Screen.Record -> vm.result?.let { case ->
            case.timeline?.let { RecordScreen(it, vehicleSummary(case), onBack = vm::back) }
        } ?: HomeScreen(vm.home, onAnalyze = vm::openImport, onHistory = vm::openHistory)
        Screen.Player -> PlayerScreen(
            vm.player, vm.driving, onBack = vm::back, onRetry = vm::retryPlayer, onError = vm::playerFailed,
            onChoose = vm::choosePick, onUnchoose = vm::unchoosePick, onConfirm = vm::confirmPick,
        )
        Screen.History -> HistoryScreen(
            vm.history, onBack = vm::back, onOpen = vm::openCase, onMore = vm::moreHistory,
            onReload = vm::refreshHistory, onDelete = { vm.askDelete(it.id, it.accidentAt) },
        ) { modifier ->
            SettingsCard(
                vm.settings, onAutoRecord = vm::setAutoRecord, onWipe = vm::askWipe,
                onWipeServer = vm::setWipeServer, onConfirmWipe = vm::confirmWipe, onCancelWipe = vm::cancelWipe,
                modifier = modifier,
            )
        }
        Screen.Questions -> vm.questions?.let { q ->
            QuestionScreen(
                q, vm.driving, onBack = vm::back, onPick = vm::pick, onDontKnow = vm::dontKnow,
                onNext = vm::nextQuestion, onRetry = vm::submitAnswers,
                onToggle = vm::toggle, onBundleNone = vm::bundleNone,
            )
        } ?: HomeScreen(vm.home, onAnalyze = vm::openImport, onHistory = vm::openHistory)
    }
    vm.deleting?.let { (_, at) ->
        ConfirmDialog(
            title = stringResource(R.string.delete_confirm_title),
            text = (at?.let { stringResource(R.string.delete_confirm_when, Format.dayTime(it)) } ?: "") +
                stringResource(R.string.delete_confirm_text),
            confirm = stringResource(R.string.delete),
            onConfirm = vm::confirmDelete,
            onDismiss = vm::cancelDelete,
            busy = vm.deleteBusy,
            error = vm.deleteError,
        )
    }
}

/**
 * 주행 중 판단 (docs/app-ui.md 1절 "주행 중"). 영상 선택·분석 시작·질문 답변은 정차 중에만.
 *  - 기어 P면 정차
 *  - 속도를 알면 3km/h 이상이 주행
 *  - 속도를 모르면 기어로: R·D(수동 단수 포함)면 주행, 그 밖(N·모름)은 정차
 * gear는 VehicleGear 정수 (P 4, R 2, N 1, D 8, 수동 1단 16~)
 */
object DrivingState {
    const val DRIVING_KMH = 3f
    private const val GEAR_PARK = 4
    private const val GEAR_REVERSE = 2
    private const val GEAR_DRIVE = 8
    private const val GEAR_FIRST = 16

    fun isDriving(speedKmh: Float?, gear: Int? = null): Boolean {
        if (gear == GEAR_PARK) return false
        if (speedKmh != null && !speedKmh.isNaN()) return speedKmh >= DRIVING_KMH
        return gear == GEAR_REVERSE || gear == GEAR_DRIVE || (gear != null && gear >= GEAR_FIRST)
    }
}
