package com.example.hmtm.data.record

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class RecordPolicyTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun wipeLoopAndEvents() {
        val loop = tmp.newFolder("loop")
        val events = tmp.newFolder("events")
        val keep = tmp.newFolder("cases")
        File(loop, "seg_1.csv").writeText("t\n")
        File(loop, "seg_2.csv").writeText("t\n")
        File(events, "event_3.json").writeText("{}")
        File(keep, "abc.json").writeText("{}")
        assertEquals(3, RecordPolicy.wipe(loop, events, File(tmp.root, "missing")))
        assertTrue(loop.listFiles()!!.isEmpty())
        assertTrue(events.listFiles()!!.isEmpty())
        assertEquals(1, keep.listFiles()!!.size)        // 다른 폴더는 그대로
        assertTrue(Bookmarks.list(events).isEmpty())
    }

    @Test fun recordOnlyAfterConsent() {
        assertEquals(false, RecordPolicy.shouldRecord(consented = false, autoRecord = true))
        assertEquals(false, RecordPolicy.shouldRecord(consented = true, autoRecord = false))
        assertEquals(true, RecordPolicy.shouldRecord(consented = true, autoRecord = true))
    }
}
