package com.example.hmtm.ui

import android.app.Application
import android.content.Intent
import android.net.Uri
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.hmtm.BuildConfig
import com.example.hmtm.R
import com.example.hmtm.data.bb.BbApi
import com.example.hmtm.data.bb.BbCase
import com.example.hmtm.data.bb.CaseStore
import com.example.hmtm.data.bb.Page
import com.example.hmtm.data.bb.QuestionSession
import com.example.hmtm.data.net.ApiClient
import com.example.hmtm.data.net.ApiException
import com.example.hmtm.data.net.PrefsTokenStore
import com.example.hmtm.data.record.Bookmarks
import com.example.hmtm.data.record.VehicleAttachment
import com.example.hmtm.data.record.VehicleRecord
import com.example.hmtm.data.vehicle.VehicleHub
import com.example.hmtm.data.video.DocumentsUiVideoSource
import com.example.hmtm.data.video.PickedVideo
import com.example.hmtm.data.video.StartTime
import com.example.hmtm.data.video.VideoReadException
import com.example.hmtm.data.video.VideoSource
import com.example.hmtm.data.bb.BbSummary
import com.example.hmtm.ui.history.HistoryState
import com.example.hmtm.ui.history.SettingsState
import com.example.hmtm.data.record.RecordPolicy
import com.example.hmtm.data.record.RecordSettings
import com.example.hmtm.service.Collector
import com.example.hmtm.ui.home.HomeState
import com.example.hmtm.ui.player.Frames
import com.example.hmtm.ui.player.PickMode
import com.example.hmtm.ui.player.PlayerState
import com.example.hmtm.ui.player.Replay
import com.example.hmtm.ui.questions.QuestionUi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/** 토스트를 보여 주는 시간 */
private const val TOAST_MS = 3_000L

enum class Screen { Home, Import, Analyzing, Result, Questions, History, Onboarding, Player, Record }

/** 영상 가져오기 화면의 "차량 기록" 행 (docs/app-ui.md 2.2) */
enum class SyncHint { Coarse, None, NoRecord }

data class ImportState(
    val inspecting: Boolean = false,
    val video: PickedVideo? = null,
    val vehicle: VehicleAttachment? = null,
    val syncHint: SyncHint = SyncHint.NoRecord,
    val error: String? = null,
    val pickCancelled: Boolean = false,
)

/** 분석 중 화면 4단계: 0 영상 올리기, 1 상대 차와 신호 분석, 2 차량 기록 맞춰 보기, 3 과실비율 판정 */
data class AnalyzingState(
    val step: Int = 0,
    val uploadProgress: Float = 0f,
    val analysisProgress: Int = 0,
    val error: String? = null,
    val errorCode: String? = null,
    /** unsupported / failed: 서버 문구로 안내하고 끝 (사고 순간을 고를 수 있는 no_collision은 결과 화면으로) */
    val stopped: String? = null,
    val caseId: String? = null,
    /** 고른 사고 순간으로 다시 분석 중 (PUT collision) */
    val picking: Boolean = false,
) {
    /** 분석 단계인데 서버가 진행률을 아직 안 줌 → 값 없는 막대 */
    val indeterminate: Boolean get() = step == 1 && analysisProgress <= 0

    /** 진행 막대: 올리기 0~40%, 분석 40~90%, 맞추기·판정 90~100% */
    val overall: Float
        get() = when (step) {
            0 -> 0.4f * uploadProgress
            1 -> 0.4f + 0.5f * analysisProgress / 100f
            2 -> 0.95f
            else -> 1f
        }
}

/**
 * 앱 흐름: 홈 → 영상 가져오기 → 분석 중(업로드·폴링) → 결과.
 * 업로드·폴링은 viewModelScope에서 돈다. 화면을 떠나도(출발해도) 앱이 살아 있으면 계속된다.
 */
class AppViewModel(app: Application) : AndroidViewModel(app) {
    val videoSource: VideoSource = DocumentsUiVideoSource()
    private val api = BbApi(ApiClient(BuildConfig.BACKEND_URL, PrefsTokenStore(app)))
    private val loopDir = File(app.filesDir, "loop")
    private val eventsDir = File(app.filesDir, "events")
    private val cases = CaseStore(File(app.filesDir, "cases"))

    var screen by mutableStateOf(Screen.Home)
        private set
    var home by mutableStateOf(HomeState())
        private set
    var import by mutableStateOf(ImportState())
        private set
    var analyzing by mutableStateOf(AnalyzingState())
        private set
    var result by mutableStateOf<BbCase?>(null)
        private set
    var questions by mutableStateOf<QuestionUi?>(null)
        private set
    var history by mutableStateOf(HistoryState())
        private set
    /** 결과 화면의 "영상 다시 보기": 기기에 있는 원본 (content://, 사건을 만들 때 보관) */
    var resultVideo by mutableStateOf<Pair<Uri, String>?>(null)
        private set
    private val recordSettings = RecordSettings(app)
    var settings by mutableStateOf(SettingsState(autoRecord = recordSettings.autoRecord))
        private set

    /** 짧은 알림 (토스트 규격). 3초 뒤 저절로 사라진다 (움직임 없이 바로) */
    var toast by mutableStateOf<String?>(null)
        private set
    private var toastJob: Job? = null

    fun showToast(text: String?) {
        if (text.isNullOrBlank()) return
        toast = text
        toastJob?.cancel()
        toastJob = viewModelScope.launch {
            delay(TOAST_MS)
            toast = null
        }
    }

    private fun text(id: Int, vararg args: Any): String = getApplication<Application>().getString(id, *args)

    init {
        // 첫 실행: 기록 안내·동의 전에는 수집 서비스를 시작하지 않는다
        if (!recordSettings.consented) screen = Screen.Onboarding
    }

    /** 첫 실행 안내 "동의하고 시작". 속도 권한 요청·서비스 시작은 화면(HmtmApp)이 한다 */
    fun consent() {
        recordSettings.consented = true
        screen = Screen.Home
    }
    /** 결과 화면에서 뒤로 가면 갈 곳 (홈 또는 지난 분석) */
    private var resultFrom = Screen.Home

    val driving: Boolean get() = home.driving

    private var job: Job? = null

    init {
        viewModelScope.launch {
            while (isActive) {
                val marks = withContext(Dispatchers.IO) { Bookmarks.list(eventsDir) }
                home = HomeState(
                    recording = VehicleHub.isRunning,
                    bookmarks = marks,
                    driving = VehicleHub.latest.let { DrivingState.isDriving(it.speedKmh, it.gear) },
                )
                delay(1_000)
            }
        }
    }

    // ---------- 이동 ----------

    fun openImport() {
        if (driving) return
        screen = Screen.Import
    }

    fun goHome() {
        screen = Screen.Home
    }

    fun back() {
        screen = when (screen) {
            Screen.Import, Screen.History, Screen.Onboarding -> Screen.Home
            Screen.Result -> {
                if (resultFrom == Screen.History) refreshHistory()
                resultFrom
            }
            Screen.Questions -> {
                questionBack()
                return
            }
            Screen.Player -> {
                // 고르기 확인 단계면 영상으로 돌아감
                val p = player.pick
                if (p?.chosenMs != null) {
                    unchoosePick()
                    return
                }
                player = PlayerState()
                Screen.Result
            }
            Screen.Record -> Screen.Result
            Screen.Analyzing -> if (analyzing.error != null || analyzing.stopped != null) Screen.Import else Screen.Home
            Screen.Home -> Screen.Home
        }
    }

    // ---------- 영상 고르기 ----------

    fun onPicked(uri: Uri?) {
        if (uri == null) {
            import = import.copy(pickCancelled = import.video == null)
            return
        }
        val ctx = getApplication<Application>()
        // 결과 화면의 "영상 다시 보기"에서 다시 열 수 있게 읽기 권한을 남긴다 (USB를 빼면 못 엶)
        runCatching { ctx.contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION) }
        import = ImportState(inspecting = true)
        viewModelScope.launch {
            import = try {
                val v = videoSource.inspect(ctx, uri)
                val vehicle = withContext(Dispatchers.IO) {
                    v.startMs?.let { VehicleRecord.attach(loopDir, VehicleRecord.window(it, v.durationMs, v.startSource)) }
                }
                ImportState(video = v, vehicle = vehicle, syncHint = syncHint(v, vehicle))
            } catch (e: VideoReadException) {
                ImportState(error = e.message)
            }
        }
    }

    /** 서버의 시각 맞추기 등급 미리보기 (bb-flow-notes 4절: 파일 이름·메타데이터면 coarse, 수정 시각뿐이면 none) */
    private fun syncHint(v: PickedVideo, vehicle: VehicleAttachment?): SyncHint = when {
        vehicle == null && v.startMs != null -> SyncHint.NoRecord
        v.startSource == StartTime.FILENAME || v.startSource == StartTime.METADATA -> SyncHint.Coarse
        else -> SyncHint.None
    }

    // ---------- 업로드·분석 ----------

    fun startAnalysis() {
        val v = import.video ?: return
        if (driving || job?.isActive == true) return
        val vehicle = import.vehicle
        analyzing = AnalyzingState()
        result = null
        screen = Screen.Analyzing
        val ctx = getApplication<Application>()
        job = viewModelScope.launch {
            try {
                val created = api.create(
                    v, { videoSource.open(ctx, v.uri) }, vehicle?.toJson(BuildConfig.VERSION_NAME),
                    BuildConfig.BB_SCENARIO.ifBlank { null },
                ) { p -> analyzing = analyzing.copy(uploadProgress = p) }
                analyzing = analyzing.copy(step = 1, uploadProgress = 1f, caseId = created.id)
                analyzingVideo = v.uri to v.mimeType
                follow(created.id)
            } catch (e: ApiException) {
                analyzing = analyzing.copy(error = e.message, errorCode = e.code)
            } catch (e: VideoReadException) {
                analyzing = analyzing.copy(error = e.message, errorCode = "video_read")
            }
        }
    }

    /** 다시 시도: 사건을 이미 만들었으면 결과만 다시 기다리고, 아니면 처음부터 올린다 */
    fun retry() {
        val id = analyzing.caseId
        if (id == null || analyzing.stopped != null) {
            if (import.video != null) startAnalysis()
            return
        }
        analyzing = analyzing.copy(error = null, errorCode = null)
        job = viewModelScope.launch {
            try {
                follow(id)
            } catch (e: ApiException) {
                analyzing = analyzing.copy(error = e.message, errorCode = e.code)
            }
        }
    }

    /** 분석 중인 사건의 기기 원본 (content://, 결과 화면의 영상 다시 보기·사고 순간 고르기) */
    private var analyzingVideo: Pair<Uri, String>? = null

    private suspend fun follow(id: String) {
        val done = api.await(id, onUpdate = { c ->
            if (c.analyzing) analyzing = analyzing.copy(step = 1, analysisProgress = c.progress)
        })
        val v = analyzingVideo
        when {
            // 판정은 못 했지만 사고 순간을 고르면 다시 분석할 수 있으면(no_collision) 결과 화면에서 고르기를 안내
            done.status == BbCase.NO_COLLISION && done.review?.needed == true -> {
                analyzing = analyzing.copy(step = 4)
                showCase(done, v)
            }
            done.finished -> {
                // 맞추기·판정은 서버가 분석 직후 바로 끝낸다 (bb-flow-notes 6절). 단계 표시만 차례로 넘긴다
                analyzing = analyzing.copy(step = 2, analysisProgress = 100)
                delay(400)
                analyzing = analyzing.copy(step = 4)
                delay(300)
                showCase(done, v)
            }
            else -> analyzing = analyzing.copy(stopped = stopMessage(done), errorCode = done.analysis?.reason ?: done.status)
        }
    }

    /** 끝난 분석을 결과 화면으로. 기기 원본 주소를 사건마다 보관 (다시 보기·사고 순간 고르기) */
    private suspend fun showCase(done: BbCase, v: Pair<Uri, String>?) {
        result = done
        if (v != null) {
            resultVideo = v
            withContext(Dispatchers.IO) {
                cases.update(done.id) { it.copy(videoUri = v.first.toString(), mimeType = v.second) }
            }
        }
        if (!analyzing.picking) resultFrom = Screen.Home
        // 고른 순간으로도 판정하지 못했으면 결과 카드의 안내와 함께 짧게 알림
        val review = done.review
        val last = review?.lastPick
        if (analyzing.picking && review?.needed == true && last != null) {
            showToast(text(R.string.pick_last_failed, Format.seconds(last.t)))
        }
        // 분석 중에 홈으로 나갔어도 끝나면 결과를 보여 준다 (새 영상을 고르는 중이면 두고)
        if (screen == Screen.Analyzing || screen == Screen.Home) screen = Screen.Result
    }

    private fun stopMessage(c: BbCase): String = when {
        c.status == BbCase.FAILED -> text(R.string.analyze_failed)
        else -> c.analysis?.message ?: text(R.string.analyze_failed)
    }

    fun showResult() {
        if (result != null) screen = Screen.Result
    }

    // ---------- 지난 분석 (docs/app-ui.md 2.6) ----------

    fun openHistory() {
        screen = Screen.History
        refreshHistory()
    }

    private var historyJob: Job? = null

    /** 첫 쪽부터 다시 */
    fun refreshHistory() = loadHistory(reset = true)

    /** 다음 쪽 (마지막 항목의 created_at을 before로) */
    fun moreHistory() = loadHistory(reset = false)

    private fun loadHistory(reset: Boolean) {
        if (historyJob?.isActive == true) return
        val before = if (reset) null else history.items.lastOrNull()?.createdAt
        history = history.copy(loading = true, error = null)
        historyJob = viewModelScope.launch {
            try {
                val page = api.list(before = before)
                val items = if (reset) page else (history.items + page).distinctBy { it.id }
                history = history.copy(items = items, loading = false, more = page.size >= BbApi.PAGE)
            } catch (e: ApiException) {
                history = history.copy(loading = false, error = e.message)
            }
        }
    }

    /** 목록에서 사건 열기 → 결과 화면 */
    fun openCase(s: BbSummary) {
        if (history.opening != null) return
        when {
            s.analyzing -> {
                showToast(text(R.string.toast_still_analyzing))
                return
            }
            !s.openable -> {
                showToast(text(R.string.toast_not_judged) + (s.reason?.let { " ($it)" } ?: ""))
                return
            }
        }
        history = history.copy(opening = s.id)
        viewModelScope.launch {
            try {
                val c = api.get(s.id)
                val local = withContext(Dispatchers.IO) { cases.get(c.id) }
                result = c
                resultVideo = local?.videoUri?.let { Uri.parse(it) to (local?.mimeType ?: "video/*") }
                resultFrom = Screen.History
                history = history.copy(opening = null)
                screen = Screen.Result
            } catch (e: ApiException) {
                history = history.copy(opening = null)
                showToast(e.message)
            }
        }
    }

    // ---------- 기록 설정 (docs/app-ui.md 2.6 오른쪽) ----------

    /** 자동 기록: 끄면 수집 서비스를 멈추고 부팅 때도 시작하지 않음 (BootReceiver) */
    fun setAutoRecord(on: Boolean) {
        recordSettings.autoRecord = on
        settings = settings.copy(autoRecord = on)
        val ctx = getApplication<Application>()
        if (on) Collector.startIfAllowed(ctx) else Collector.stop(ctx)
    }

    fun askWipe() {
        settings = settings.copy(confirmWipe = true, wipeServer = false)
    }

    fun setWipeServer(on: Boolean) {
        settings = settings.copy(wipeServer = on)
    }

    fun cancelWipe() {
        if (!settings.wiping) settings = settings.copy(confirmWipe = false)
    }

    /**
     * 모든 기록 삭제: 수집 서비스를 멈추고 루프 기록·급제동 북마크를 지운 뒤 (자동 기록이 켜져 있으면) 다시 시작.
     * 고르면 서버의 내 사건도 DELETE /api/bb-cases 한 번으로 지운다.
     */
    fun confirmWipe() {
        if (settings.wiping) return
        val withServer = settings.wipeServer
        val ctx = getApplication<Application>()
        settings = settings.copy(wiping = true)
        viewModelScope.launch {
            var msg: String
            Collector.stop(ctx)
            // 서비스가 멈추고 마지막 쓰기(loop.close)가 끝날 때까지 잠깐 기다림
            var waited = 0
            while (VehicleHub.isRunning && waited < 3_000) {
                delay(100); waited += 100
            }
            delay(300)
            val n = withContext(Dispatchers.IO) { RecordPolicy.wipe(loopDir, eventsDir) }
            VehicleHub.buffer.clear()
            msg = text(R.string.toast_wiped, n)
            if (withServer) {
                msg = try {
                    val gone = deleteAllCases()
                    text(R.string.toast_wiped_server, msg, gone)
                } catch (e: ApiException) {
                    text(R.string.toast_wiped_server_failed, msg, e.message ?: "")
                }
            }
            if (recordSettings.autoRecord) Collector.startIfAllowed(ctx)
            home = home.copy(bookmarks = emptyList())
            settings = settings.copy(wiping = false, confirmWipe = false)
            showToast(msg)
        }
    }

    /** 서버의 내 블랙박스 사건 전부 삭제 (DELETE /api/bb-cases). 지운 수 */
    private suspend fun deleteAllCases(): Int {
        val n = api.deleteAll()
        withContext(Dispatchers.IO) { cases.clear() }
        history = history.copy(items = emptyList(), more = false)
        if (result != null && screen != Screen.Result) {
            result = null
            resultVideo = null
        }
        return n
    }

    // ---------- 영상 다시 보기 ----------

    var player by mutableStateOf(PlayerState())
        private set

    /** 결과 화면 "영상 다시 보기": 기기의 원본을 앱 안에서 재생. 읽을 수 없으면 "USB를 다시 연결해 주세요" */
    fun openPlayer() {
        val uri = resultVideo?.first
        player = PlayerState(uri, result?.collisionT, checking = uri != null, error = if (uri == null) text(R.string.player_no_local) else null)
        screen = Screen.Player
        if (uri != null) checkPlayable(uri)
    }

    // ---------- 사고 순간 고르기 (design-blackbox 3.2·3.6 PUT collision) ----------

    /**
     * 결과 화면 "사고 순간 고르기": 영상 다시 보기 화면을 고르기 모드로 연다.
     * 분석기 순간·첫 후보 3초 전부터 재생. 기기 원본을 열 수 없으면 "USB를 다시 연결해 주세요"
     */
    fun openPick() {
        val c = result ?: return
        val review = c.review ?: return
        if (!review.canPick) return
        val uri = resultVideo?.first
        val at = review.t ?: review.candidates.firstOrNull()?.t
        player = PlayerState(
            uri, at, checking = uri != null, error = if (uri == null) text(R.string.player_no_local) else null,
            pick = PickMode(c.id, review.candidates.map { it.t }),
        )
        screen = Screen.Player
        if (uri != null) checkPlayable(uri)
    }

    /** 고르기 화면 "이 순간으로 고르기": 그 시점 화면을 크게 보여 주는 확인 단계로 (아직 보내지 않음) */
    fun choosePick(ms: Int) {
        val p = player.pick ?: return
        val uri = player.uri ?: return
        if (driving) return
        player = player.copy(pick = p.copy(chosenMs = ms, resumeMs = ms, frame = null, frameLoading = true, error = null))
        val ctx = getApplication<Application>()
        viewModelScope.launch {
            val frame = withContext(Dispatchers.IO) { Frames.at(ctx, uri, ms) }
            val now = player.pick ?: return@launch
            if (now.chosenMs == ms) player = player.copy(pick = now.copy(frame = frame, frameLoading = false))
        }
    }

    /** 확인 단계 "다시 고르기" */
    fun unchoosePick() {
        val p = player.pick ?: return
        if (p.sending) return
        player = player.copy(pick = p.copy(chosenMs = null, frame = null, frameLoading = false, error = null))
    }

    /**
     * 확인 단계 "이 순간으로 분석": PUT collision → 202 → 분석 중 화면에서 폴링 (POST와 같음).
     * 409 이미 정해짐·410 기한 지남은 사건을 다시 불러 결과 화면으로 (카드가 그 상태를 보여 줌). 422·503 등은 이 화면에 안내
     */
    fun confirmPick() {
        val p = player.pick ?: return
        val ms = p.chosenMs ?: return
        if (driving || p.sending || job?.isActive == true) return
        player = player.copy(pick = p.copy(sending = true, error = null))
        val video = resultVideo
        job = viewModelScope.launch {
            var accepted = false
            try {
                api.putCollision(p.caseId, ms / 1000.0)
                accepted = true
                analyzing = AnalyzingState(step = 1, uploadProgress = 1f, caseId = p.caseId, picking = true)
                analyzingVideo = video
                player = PlayerState()
                screen = Screen.Analyzing
                follow(p.caseId)
            } catch (e: ApiException) {
                if (accepted) {
                    analyzing = analyzing.copy(error = e.message, errorCode = e.code)
                    return@launch
                }
                when (e.code) {
                    "collision_not_needed", "video_gone" -> {
                        showToast(if (e.code == "video_gone") e.message else text(R.string.pick_err_not_needed))
                        try {
                            result = api.get(p.caseId)
                        } catch (_: ApiException) {
                        }
                        player = PlayerState()
                        screen = Screen.Result
                    }
                    else -> player = player.copy(
                        pick = p.copy(
                            sending = false,
                            error = if (e.code == "analyzer_not_ready") text(R.string.pick_err_not_ready) else e.message,
                        ),
                    )
                }
            }
        }
    }

    fun retryPlayer() {
        val uri = player.uri ?: return
        player = player.copy(checking = true, error = null)
        checkPlayable(uri)
    }

    /** 재생 중 오류 (USB를 뺐을 때 등) */
    fun playerFailed() {
        player = player.copy(checking = false, error = Replay.MSG_UNAVAILABLE)
    }

    private fun checkPlayable(uri: Uri) {
        val ctx = getApplication<Application>()
        viewModelScope.launch {
            val ok = withContext(Dispatchers.IO) {
                try {
                    ctx.contentResolver.openFileDescriptor(uri, "r")?.use { true } ?: false
                } catch (e: Exception) {   // SecurityException(권한 끊김), FileNotFoundException(USB 뺌) 등
                    false
                }
            }
            player = player.copy(checking = false, error = if (ok) null else Replay.MSG_UNAVAILABLE)
        }
    }

    // ---------- 사건 삭제 ----------

    /** 삭제 확인 대화상자를 띄운 사건 (id, 사고 시각) */
    var deleting by mutableStateOf<Pair<String, Long?>?>(null)
        private set
    var deleteBusy by mutableStateOf(false)
        private set
    var deleteError by mutableStateOf<String?>(null)
        private set

    fun askDelete(id: String, accidentAt: Long?) {
        deleting = id to accidentAt
        deleteError = null
    }

    fun cancelDelete() {
        if (!deleteBusy) deleting = null
    }

    /** DELETE /api/bb-cases/{id} → 기기 보관도 지우고 목록·결과 화면에서 뺀다 */
    fun confirmDelete() {
        val id = deleting?.first ?: return
        if (deleteBusy) return
        deleteBusy = true
        viewModelScope.launch {
            try {
                api.delete(id)
                withContext(Dispatchers.IO) { cases.delete(id) }
                history = history.copy(items = history.items.filterNot { it.id == id })
                if (result?.id == id) {
                    result = null
                    resultVideo = null
                    if (screen == Screen.Result) {
                        screen = resultFrom
                        if (resultFrom == Screen.History) refreshHistory()
                    }
                }
                if (analyzing.caseId == id) analyzing = AnalyzingState()
                deleting = null
            } catch (e: ApiException) {
                deleteError = e.message
            } finally {
                deleteBusy = false
            }
        }
    }

    // ---------- 질문 (docs/app-ui.md 2.4) ----------

    /** 결과 화면 "질문 N개 답하기" */
    fun answerRemaining() {
        val c = result ?: return
        openQuestions(c, QuestionSession.remaining(c))
    }

    /** 결과 화면 "상대가 OO가 아니었나요?" */
    fun askOtherCls() {
        val c = result ?: return
        val session = QuestionSession.otherCls(c) ?: return
        // 상대 종류만 고치면 결과로 바로 (장이 바뀌면 질문이 통째로 바뀌어 결과에서 "질문 N개 답하기"로)
        openQuestions(c, session, followUps = false)
    }

    /** 결과 화면 "답변 고치기": 지금까지의 답을 채운 상태로 (답한 질문 정의는 서버 answered) */
    fun editAnswers() {
        val c = result ?: return
        openQuestions(c, QuestionSession.edit(c))
    }

    // ---------- 기록 보기 (docs/app-ui.md 2.7) ----------

    /** 결과 화면 "기록 보기": 충돌 전후 차량 기록 그래프 */
    fun openRecord() {
        if (result?.timeline != null) screen = Screen.Record
    }

    /** 고칠 답이 있는지 (답한 것이나 남은 질문) */
    fun canEdit(c: BbCase): Boolean = c.finished &&
        (c.userAnswers.isNotEmpty() || c.remaining.any { it.answerable } || c.optionalQuestions.isNotEmpty())

    private fun openQuestions(c: BbCase, session: QuestionSession, followUps: Boolean = true) {
        if (session.done) return
        questions = QuestionUi(session, pedestrian = pedestrian(c), followUps = followUps)
        screen = Screen.Questions
    }

    private fun pedestrian(c: BbCase) = (c.result?.chapter ?: c.otherCls?.chapter) == "car_pedestrian"

    /** 여러 개 고르기·묶음: 보기 켜고 끄기 */
    fun toggle(field: String, value: Any?) {
        if (driving) return
        val q = questions ?: return
        val s = q.session
        val next = when (val p = s.page) {
            is Page.Bundle -> s.toggleIn(p, field, value)
            else -> s.toggle(field, value)
        }
        questions = q.copy(session = next, error = null)
    }

    /** 묶음 "해당 없음" */
    fun bundleNone() {
        if (driving) return
        val q = questions ?: return
        val p = q.session.page as? Page.Bundle ?: return
        questions = q.copy(session = q.session.toggleBundleNone(p), error = null)
    }

    fun pick(value: Any?) {
        if (driving) return
        val q = questions ?: return
        questions = q.copy(session = q.session.pick(value), error = null)
    }

    /** "잘 모르겠어요"·"건너뛰기": 한 질문·묶음은 답을 보내지 않고, 여러 개 고르기는 [] (답 없음)로 다음 */
    fun dontKnow() {
        if (driving) return
        val q = questions ?: return
        advance(q.copy(session = q.session.skip()))
    }

    fun nextQuestion() {
        if (driving) return
        val q = questions ?: return
        if (!q.session.hasSelection) return
        advance(q)
    }

    private fun advance(q: QuestionUi) {
        val next = q.session.next()
        questions = q.copy(session = next, error = null)
        if (next.done) submitAnswers()
    }

    private fun questionBack() {
        val q = questions ?: return
        if (q.sending) return
        if (q.session.isFirst || q.session.done) {
            questions = null
            screen = Screen.Result
        } else {
            questions = q.copy(session = q.session.prev(), error = null)
        }
    }

    /** 다 답하면 PUT answers → 새 결과로 결과 화면. 409(분석 중)면 안내하고 잠시 뒤 다시 보냄 (BbApi.putAnswers) */
    fun submitAnswers() {
        val q = questions ?: return
        if (driving || q.sending) return
        questions = q.copy(sending = true, waiting = null, error = null)
        viewModelScope.launch {
            try {
                val updated = api.putAnswers(q.session.caseId, q.session.answers(), onBusy = {
                    questions = questions?.copy(waiting = text(R.string.question_waiting))
                })
                result = updated
                // 답 때문에 새로 생긴 질문(과속 → 제한속도를 지켰다면 등)은 결과로 가기 전에 이어서 묻는다
                val follow = if (q.followUps) QuestionSession.followUp(updated, q.asked) else null
                if (follow != null) {
                    questions = QuestionUi(follow, pedestrian = pedestrian(updated), asked = q.asked + follow.questions.map { it.field })
                } else {
                    questions = null
                    screen = Screen.Result
                }
            } catch (e: ApiException) {
                // 마지막 질문에 머물러 다시 보낼 수 있게 한다
                val back = if (q.session.done) q.session.prev() else q.session
                questions = questions?.copy(session = back, sending = false, waiting = null, error = e.message)
            }
        }
    }
}
