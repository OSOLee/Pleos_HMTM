package com.example.hmtm.data.net

import okhttp3.MediaType
import okhttp3.RequestBody
import okio.BufferedSink
import java.io.InputStream

/**
 * 큰 영상을 메모리에 올리지 않고 스트림으로 보내며 진행률을 알리는 본문.
 * 재시도(401 재발급 뒤)하면 OkHttp가 writeTo를 다시 부르므로 그때마다 스트림을 새로 연다.
 */
class ProgressRequestBody(
    private val type: MediaType?,
    private val length: Long,
    private val open: () -> InputStream,
    private val onProgress: (sent: Long, total: Long) -> Unit,
) : RequestBody() {
    override fun contentType() = type
    override fun contentLength() = length

    override fun writeTo(sink: BufferedSink) {
        open().use { input ->
            val buf = ByteArray(CHUNK)
            var sent = 0L
            var lastReport = -1L
            while (true) {
                val n = input.read(buf)
                if (n < 0) break
                sink.write(buf, 0, n)
                sent += n
                // 너무 자주 알리지 않게 1% 또는 끝에서만
                val step = if (length > 0) sent * 100 / length else sent / CHUNK
                if (step != lastReport) {
                    lastReport = step
                    onProgress(sent, length)
                }
            }
        }
    }

    companion object {
        private const val CHUNK = 64 * 1024
    }
}
