package com.example.hmtm.data.record

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.io.File
import java.nio.file.Files

class BookmarksTest {
    private fun event(trigger: Long, speeds: List<Pair<Long, Double?>>) = buildString {
        append("{\"reason\":\"hard_brake\",\"triggerAt\":$trigger,\"samples\":[")
        append(speeds.joinToString(",") { (t, v) -> "{\"t\":$t,\"speedKmh\":${v ?: "null"}}" })
        append("]}")
    }

    @Test fun speedBeforeAndAfter() {
        val b = Bookmarks.parse(event(10_000, listOf(
            7_000L to 70.0, 8_600L to 62.0, 9_500L to 50.0, 10_000L to 40.0, 12_000L to 8.0, 16_000L to 0.0,
        )))!!
        assertEquals(62f, b.speedBefore!!, 0.01f)   // 7초는 1.5초 밖
        assertEquals(8f, b.speedAfter!!, 0.01f)      // 16초는 5초 밖
    }

    @Test fun missingSpeed() {
        val b = Bookmarks.parse(event(10_000, listOf(9_500L to null)))!!
        assertNull(b.speedBefore)
        assertNull(Bookmarks.parse("{\"triggerAt\":null,\"samples\":[]}"))
    }

    @Test fun listNewestFirst() {
        val dir = Files.createTempDirectory("ev").toFile()
        File(dir, "event_100.json").writeText(event(100, emptyList()))
        File(dir, "event_300.json").writeText(event(300, emptyList()))
        File(dir, "event_200.json").writeText("깨진 파일")
        File(dir, "other.json").writeText(event(400, emptyList()))
        assertEquals(listOf(300L, 100L), Bookmarks.list(dir).map { it.triggerAt })
        dir.deleteRecursively()
    }
}
