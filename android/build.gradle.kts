// The Android client. One module, no runtime dependencies: everything it uses
// is in the Android framework, so the APK carries only this code and what R8
// keeps of the Kotlin standard library. See README.md for the design.
plugins {
    id("com.android.application") version "9.4.1"
}

// CI passes both (desktop-release.yml). The version code has to rise with every
// published build, or Android refuses the update as a downgrade; CI derives it
// from the build time, so there is no number for anyone to remember to bump.
// A local build is 1, which any CI build replaces.
val smylteVersionCode = providers.gradleProperty("smylteVersionCode").orNull?.toInt() ?: 1
val smylteVersionName = providers.gradleProperty("smylteVersionName").orNull ?: "dev"

android {
    namespace = "com.nicholaskmitchell.smylte"
    compileSdk = 36

    defaultConfig {
        // Permanent. Android treats a different id as a different app, so
        // changing it would strand every installed copy on its last update.
        applicationId = "com.nicholaskmitchell.smylte"
        minSdk = 30
        targetSdk = 36
        versionCode = smylteVersionCode
        versionName = smylteVersionName
    }

    buildTypes {
        release {
            // Unsigned here on purpose. The signing key is applied by a later
            // CI job that runs no Gradle and no dependency code at all, so the
            // key is never on a machine running third-party build plugins.
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    lint {
        // Errors fail the build; warnings are reported but do not.
        abortOnError = true
        checkReleaseBuilds = true
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}
