// Stellarite core: everything both coins need that isn't UI. The consensus rules (solo
// chains, useful-work scoring, scouts), the physics (VSOP87A, Lambert, escapes, star routes),
// the mining engine and node/pool clients, and key/signing code compatible with wallet.py.
// Used by the Stellarite Miner app and, as a synced copy, by the Stellura wallet.
plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.stellarite.core"
    compileSdk = 35

    defaultConfig {
        minSdk = 26
        consumerProguardFiles("consumer-rules.pro")
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}
