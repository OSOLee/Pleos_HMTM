plugins {
    id("com.android.application") version "8.13.2" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
    // Kotlin 2.0부터 Compose 컴파일러는 Kotlin 플러그인과 같은 판으로 맞춘다
    id("org.jetbrains.kotlin.plugin.compose") version "2.0.21" apply false
}
