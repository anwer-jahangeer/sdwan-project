// Top-level build file. Plugin versions are declared here (with `apply false`)
// and actually applied in app/build.gradle.kts.
//
// NOTE ON VERSIONS: this project was authored in an environment with no Java,
// Gradle, or Android SDK installed, so these versions could not be resolved
// or built here. They are a "sensible stable" combination for compileSdk 36
// (Android 16) as of the time this project was authored. When you open the
// project in a current Android Studio, accept any "Upgrade Assistant" /
// AGP-upgrade prompt it offers rather than fighting it - Studio knows the
// exact latest compatible versions for the SDK/Gradle it ships with.
plugins {
    id("com.android.application") version "8.10.1" apply false
    id("org.jetbrains.kotlin.android") version "2.1.0" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.1.0" apply false
}
