package com.example.hmtm.data.bb

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class CaseStoreTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun keepsVideoAndReadsOldFiles() {
        val dir = tmp.newFolder("cases")
        val store = CaseStore(dir)
        store.update("a1") { it.copy(videoUri = "content://x/1", mimeType = "video/mp4") }
        assertEquals(CaseLocal("content://x/1", "video/mp4"), store.get("a1"))
        // 전에 쓴 파일(차량 기록 여부·질문·선택 질문 보관 칸)도 읽음 (그 칸은 무시)
        dir.resolve("old.json").writeText(
            """{"video_uri":"content://x/2","mime_type":null,"vehicle_record":true,"questions":[],""" +
                """"optional_questions":[{"field":"parties.ego.driver_factors"}]}""",
        )
        assertEquals(CaseLocal("content://x/2", null), store.get("old"))
    }

    @Test fun deleteAndClear() {
        val dir = tmp.newFolder("cases")
        val store = CaseStore(dir)
        store.update("a1") { it.copy(videoUri = "a") }
        store.update("b2") { it.copy(videoUri = "b") }
        store.delete("a1")
        assertNull(store.get("a1"))
        assertEquals("b", store.get("b2")!!.videoUri)
        store.clear()
        assertNull(store.get("b2"))
        // 이상한 id는 파일로 쓰지 않음
        store.update("../x") { it.copy(videoUri = "x") }
        assertNull(store.get("../x"))
        assertFalse(tmp.root.resolve("x.json").exists())
    }
}
