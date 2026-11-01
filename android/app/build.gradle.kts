plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.example.stellariteminer"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.example.stellariteminer"
        minSdk = 26
        targetSdk = 35
        versionCode = 120100
        versionName = "12.1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            // Signed with the debug key so CI produces an installable APK.
            // Replace with your own keystore before sharing builds widely.
            signingConfig = signingConfigs.getByName("debug")
        }
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
    implementation(project(":core"))   // consensus, physics, mining engine and wallet code
}
