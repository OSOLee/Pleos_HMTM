package com.example.hmtm.ui.theme

import androidx.compose.ui.text.font.FontFamily
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** 글자 크기는 docs/pleos-design-rules.md 3절 표의 Pleos 스타일(Connect-S)만 쓴다 */
class TypeScaleTest {

    @Test
    fun stylesUseGuideSizes() {
        val t = HmtmType.of(FontFamily.Default)
        val sizes = listOf(t.headline, t.title, t.cardTitle, t.bodyStrong, t.body, t.bodyBold, t.label, t.labelSmall)
            .map { it.fontSize.value.toInt() to it.lineHeight.value.toInt() }
        assertEquals(
            listOf(60 to 80, 32 to 40, 30 to 38, 28 to 36, 26 to 34, 26 to 34, 24 to 28, 20 to 24),
            sizes,
        )
        // 과실비율 숫자는 Headline/Large/Extra_Strong (ExtraBold), 나머지 Strong은 Bold
        assertEquals(androidx.compose.ui.text.font.FontWeight.ExtraBold, t.headline.fontWeight)
        assertTrue(listOf(t.headline, t.title, t.cardTitle, t.bodyStrong, t.body, t.bodyBold, t.label, t.labelSmall)
            .all { it.fontSize in HmtmType.SIZES })
    }

    /** 화면 코드에서 글자 크기를 따로 만들지 않는다 (테마 파일 밖에 "숫자.sp" 없음) */
    @Test
    fun noAdHocFontSizes() {
        val root = File("src/main/java")
        assertTrue("소스 폴더를 찾지 못함: ${root.absolutePath}", root.isDirectory)
        val re = Regex("""\b\d+(\.\d+)?\.sp\b""")
        val bad = root.walkTopDown()
            .filter { it.isFile && it.extension == "kt" && it.name != "Theme.kt" }
            .flatMap { f -> f.readLines().mapIndexedNotNull { i, line -> if (re.containsMatchIn(line)) "${f.name}:${i + 1}" else null } }
            .toList()
        assertTrue("테마 밖 글자 크기: $bad", bad.isEmpty())
    }
}
