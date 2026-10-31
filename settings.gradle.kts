pluginManagement {
    repositories {
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        maven { url = uri("https://jitpack.io") }
        gradlePluginPortal()
        mavenLocal()
    }
}
plugins {
    id("org.gradle.toolchains.foojay-resolver-convention") version "1.0.0"
    // Chaquopy：在 Android 上运行一条龙的 Python 内核。
    // 17.0.0 changelog 明确支持 AGP 9.0-9.4（本项目 AGP 9.4.1 在范围内）。
    id("com.chaquo.python") version "17.2.0" apply false
}

includeBuild("build-logic")

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        maven { url = uri("https://jitpack.io") }
        mavenCentral()
    }
}

rootProject.name = "MaaMeow"
include(":app")
include(":hidden-api")
include(":annotation-api")
include(":ksp-processor")
 
