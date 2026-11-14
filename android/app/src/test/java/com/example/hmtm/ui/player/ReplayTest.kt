package com.example.hmtm.ui.player

import org.junit.Assert.assertEquals
import org.junit.Test

class ReplayTest {
    @Test fun startsThreeSecondsBeforeCollision() {
        assertEquals(3_067, Replay.startMs(6.067))
        assertEquals(0, Replay.startMs(1.5))
        assertEquals(0, Replay.startMs(null))
        assertEquals(0, Replay.startMs(Double.NaN))
    }

    @Test fun clock() {
        assertEquals("0:18", Replay.clock(18_400))
        assertEquals("1:05", Replay.clock(65_000))
    }
}
