# Gradle wrapper: what's here and what's missing

This directory intentionally contains only `gradle-wrapper.properties`
(a plain-text file that pins the Gradle version, `8.13`).

It does **not** contain:

- `gradle-wrapper.jar` (a binary bootstrap jar), or
- `gradlew` / `gradlew.bat` (the wrapper launcher scripts, at the project
  root) — see note below.

## Why they were not created

This project was authored in an environment with no internet-connected
Java/Gradle/Android toolchain available to legitimately generate or
verify a working `gradle-wrapper.jar`. Hand-typing a binary jar, or a
launcher script that must byte-for-byte match a specific Gradle
distribution's bootstrap protocol, from memory would risk producing a
file that looks plausible but silently fails or (worse) behaves in an
unreviewable way. Rather than fabricate either, this project ships
without them and documents the one-time fix below.

## How to fix this (either option works)

**Option A — Android Studio (recommended, no CLI needed).**
Open this project's root folder (`android_multilink_manager`) in a
current Android Studio ("Open" → select this folder). Studio detects the
missing wrapper jar/scripts on sync and offers to regenerate them
automatically from the `distributionUrl` above. Accept the prompt.

**Option B — Command line, if you have any Gradle install available.**
From this project's root folder, run:

```
gradle wrapper --gradle-version 8.13
```

This downloads Gradle 8.13's real, verified wrapper jar and writes
`gradle/wrapper/gradle-wrapper.jar`, `gradlew`, and `gradlew.bat` next to
this file / at the project root, matching the version already pinned in
`gradle-wrapper.properties`.

Either way, nothing else in the project needs to change afterward.
