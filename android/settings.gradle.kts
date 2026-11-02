// Two repositories and no plugin portal: the Android Gradle Plugin comes from
// Google's, everything it needs from there or Maven Central. Every artifact
// resolved from either is checked against gradle/verification-metadata.xml.
pluginManagement {
    repositories {
        google()
        mavenCentral()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "smylte-android"
