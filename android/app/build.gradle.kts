import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// 서버 주소: android/local.properties의 backend.url (git에 안 올라감). 없으면 에뮬레이터에서 본 내 PC
val localProps = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}
val backendUrl = (localProps.getProperty("backend.url") ?: "http://10.0.2.2:8000").trimEnd('/')
// 개발용: 가짜 분석기 시나리오를 고정 (backend/src/blackbox/scenarios). 비우면 서버가 파일 이름·기본값으로 고름
val bbScenario = localProps.getProperty("bb.scenario") ?: ""

// release 서명: 저장소 밖 값만 읽는다 (사용자 ~/.gradle/gradle.properties 또는 환경변수).
// HMTM_RELEASE_STORE_FILE, HMTM_RELEASE_STORE_PASSWORD, HMTM_RELEASE_KEY_ALIAS, HMTM_RELEASE_KEY_PASSWORD
// 하나라도 없으면 서명 없이 빌드한다 (app-release-unsigned.apk). 키 파일·비밀번호는 저장소에 넣지 않는다.
fun releaseValue(name: String): String? =
    (findProperty(name) as String?)?.takeIf { it.isNotBlank() } ?: System.getenv(name)?.takeIf { it.isNotBlank() }
val releaseStoreFile = releaseValue("HMTM_RELEASE_STORE_FILE")?.let { file(it) }?.takeIf { it.exists() }
val releaseStorePassword = releaseValue("HMTM_RELEASE_STORE_PASSWORD")
val releaseKeyAlias = releaseValue("HMTM_RELEASE_KEY_ALIAS")
val releaseKeyPassword = releaseValue("HMTM_RELEASE_KEY_PASSWORD")
val hasReleaseSigning = releaseStoreFile != null && releaseStorePassword != null &&
    releaseKeyAlias != null && releaseKeyPassword != null

android {
    namespace = "com.example.hmtm"
    compileSdk = 34

    // 속도·기어 조회용 Android Automotive 라이브러리 (CarPropertyManager)
    useLibrary("android.car")

    defaultConfig {
        applicationId = "com.example.hmtm"
        minSdk = 28
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"
        buildConfigField("String", "BACKEND_URL", "\"$backendUrl\"")
        buildConfigField("String", "BB_SCENARIO", "\"$bbScenario\"")
    }

    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                storeFile = releaseStoreFile
                storePassword = releaseStorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            isShrinkResources = false
            // 심사용 시연: android/tools/sd.ps1 -RecordsOnly가 adb run-as로 차량 기록을 앱 폴더에 넣으려면 debuggable이어야 한다
            isDebuggable = true
            if (hasReleaseSigning) signingConfig = signingConfigs.getByName("release")
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }

}

dependencies {
    // Pleos Vehicle SDK (방향지시등, 브레이크 등)
    implementation("ai.pleos.playground:Vehicle:2.3.2")

    // Compose. BOM 2024.09.03 = Compose 1.7 (compileSdk 34에 맞는 마지막 줄)
    val composeBom = platform("androidx.compose:compose-bom:2024.09.03")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    // 아이콘: Material Symbols와 같은 모양(Outlined 기본, 켜짐·선택만 Filled)의 Material Icons (docs/app-ui.md 1절 아이콘 표)
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui-tooling-preview")
    debugImplementation("androidx.compose.ui:ui-tooling")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    // 네트워크
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    // JVM 단위 시험 (org.json은 안드로이드 것이 시험에서 빈 껍데기라 진짜 구현을 넣음)
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
}
