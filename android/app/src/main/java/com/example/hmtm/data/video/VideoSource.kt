package com.example.hmtm.data.video

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.provider.DocumentsContract
import android.provider.OpenableColumns
import androidx.activity.result.contract.ActivityResultContract
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.InputStream

/** 고른 영상. 업로드·차량 기록 첨부에 필요한 것 전부 */
data class PickedVideo(
    val uri: Uri,
    val name: String,
    val sizeBytes: Long,
    val durationMs: Long?,
    val mimeType: String,
    val candidates: List<StartCandidate>,
    val mtimeMs: Long?,
    val tzOffsetMin: Int,
) {
    /** 차량 기록을 자를 때 쓰는 촬영 시작 시각 (가장 믿을 만한 후보) */
    val startMs: Long? get() = candidates.firstOrNull()?.startMs
    val startSource: String? get() = candidates.firstOrNull()?.source
}

class VideoReadException(message: String) : Exception(message)

/**
 * 영상 가져오기 (docs/design-blackbox.md 7절 "VideoSource").
 * 고르기 → content:// 주소·파일 이름·크기·길이·촬영 시각 후보. 실차 확인 뒤 방식이 바뀌면(빌트인 캠 등) 이것만 바꾼다.
 */
interface VideoSource {
    /** 파일 선택 화면 (registerForActivityResult / rememberLauncherForActivityResult에 넘김) */
    val contract: ActivityResultContract<Unit, Uri?>

    /** 받은 주소를 실제로 읽어 보고 정보를 모음. 못 읽으면 VideoReadException */
    suspend fun inspect(context: Context, uri: Uri): PickedVideo

    /** 업로드할 때 여는 스트림 (재시도하면 다시 연다) */
    fun open(context: Context, uri: Uri): InputStream
}

/**
 * USB·SD 카드 영상을 DocumentsUI로 고른다 (설계 7.1).
 * 차량용 빌드는 그냥 부른 ACTION_OPEN_DOCUMENT를 빈 화면(Stubs)이 가로채므로 패키지를 com.android.documentsui로 정한다.
 * DocumentsUI가 없는 기기에서만 패키지 없이 부른다.
 */
class DocumentsUiVideoSource : VideoSource {

    override val contract = object : ActivityResultContract<Unit, Uri?>() {
        override fun createIntent(context: Context, input: Unit): Intent {
            val intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
                .addCategory(Intent.CATEGORY_OPENABLE)
                .setType("video/*")
                .setPackage(DOCUMENTS_UI)
            val ok = context.packageManager.queryIntentActivities(intent, 0).isNotEmpty()
            return if (ok) intent else intent.setPackage(null)
        }

        override fun parseResult(resultCode: Int, intent: Intent?): Uri? =
            if (resultCode == Activity.RESULT_OK) intent?.data else null
    }

    override suspend fun inspect(context: Context, uri: Uri): PickedVideo = withContext(Dispatchers.IO) {
        val cr = context.contentResolver
        var name: String? = null
        var size: Long? = null
        var mtime: Long? = null
        cr.query(uri, null, null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                c.getColumnIndex(OpenableColumns.DISPLAY_NAME).takeIf { it >= 0 && !c.isNull(it) }
                    ?.let { name = c.getString(it) }
                c.getColumnIndex(OpenableColumns.SIZE).takeIf { it >= 0 && !c.isNull(it) }
                    ?.let { size = c.getLong(it) }
                c.getColumnIndex(DocumentsContract.Document.COLUMN_LAST_MODIFIED).takeIf { it >= 0 && !c.isNull(it) }
                    ?.let { mtime = c.getLong(it) }
            }
        }
        // 읽을 수 있는지: 처음 몇 바이트를 실제로 읽어 본다 (권한·연결이 끊긴 USB 확인)
        try {
            cr.openInputStream(uri)?.use { if (it.read(ByteArray(16)) <= 0) throw VideoReadException("영상 파일이 비어 있어요") }
                ?: throw VideoReadException("영상을 열지 못했어요")
        } catch (e: VideoReadException) {
            throw e
        } catch (e: Exception) {
            throw VideoReadException("영상을 읽지 못했어요. USB가 연결됐는지 확인해 주세요")
        }
        if (size == null || size!! <= 0) {
            size = cr.openAssetFileDescriptor(uri, "r")?.use { it.length.takeIf { n -> n > 0 } }
        }

        var duration: Long? = null
        var metaDate: String? = null
        val mmr = MediaMetadataRetriever()
        try {
            mmr.setDataSource(context, uri)
            duration = mmr.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull()
            metaDate = mmr.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DATE)
        } catch (e: Exception) {
            // 길이를 못 읽어도 업로드는 할 수 있다 (서버가 다시 읽음)
        } finally {
            runCatching { mmr.release() }
        }

        val fileName = name ?: uri.lastPathSegment?.substringAfterLast('/') ?: "video.mp4"
        val candidates = StartTime.candidates(fileName, metaDate, mtime, duration)
        PickedVideo(
            uri = uri,
            name = fileName,
            sizeBytes = size ?: -1L,
            durationMs = duration,
            mimeType = cr.getType(uri) ?: "video/mp4",
            candidates = candidates,
            mtimeMs = mtime,
            tzOffsetMin = StartTime.tzOffsetMin(candidates.firstOrNull()?.startMs ?: System.currentTimeMillis()),
        )
    }

    override fun open(context: Context, uri: Uri): InputStream =
        context.contentResolver.openInputStream(uri) ?: throw VideoReadException("영상을 열지 못했어요")

    companion object {
        const val DOCUMENTS_UI = "com.android.documentsui"
    }
}
