# MultiLink Manager (Android) - stock, non-root feasibility MVP

[![Android CI](https://github.com/anwer-jahangeer/sdwan-project/actions/workflows/android-ci.yml/badge.svg)](https://github.com/anwer-jahangeer/sdwan-project/actions/workflows/android-ci.yml)

> **Read this first.** This app can only choose which network **its own**
> HTTP(S) requests use. It **cannot** steer traffic for other apps, and it
> **cannot** steer traffic for devices connected to this phone's Wi-Fi
> hotspot. If you came here hoping to "bond" Wi-Fi + cellular bandwidth for
> your whole phone or for your hotspot clients, that is **not** what this
> build does, and - without root and a privileged/system app slot - it is
> not something any normal Android app can do. See
> [What this app cannot do (and why)](#what-this-app-cannot-do-and-why)
> below before you rely on it for anything.

This is a small Kotlin + Jetpack Compose Android app that:

- discovers every Wi-Fi and cellular network with internet capability that
  this app is allowed to see, using `ConnectivityManager.NetworkCallback`;
- independently health-probes each one over HTTPS, bound to that specific
  `android.net.Network`, measuring HTTP-layer latency/jitter/loss (not
  ICMP);
- scores each link with a documented, pure-Kotlin formula;
- lets *this app's own* future connections prefer the healthier link, with
  hysteresis/hold-down so the choice doesn't flap; and
- reports, honestly, what is and is not possible on a stock, non-rooted
  Android 16 phone like the Realme GT 7 Pro - including that hotspot-client
  steering and true multi-link bandwidth bonding are **out of scope for a
  non-root app** and would need fundamentally different architectures (see
  [Future architectures](#future-architectures-out-of-scope-for-this-mvp)).

It is a companion, Android-side counterpart to the Windows desktop
`multilink_manager` project at the repository root - see that project's
own README for the Windows side. **This Android project is fully
independent**: it shares no code, build system, or process with the
Windows app, and building/running one has no effect on the other.

---

## Table of contents

1. [Supported vs. unsupported matrix](#supported-vs-unsupported-matrix)
2. [Architecture](#architecture)
3. [Data sources, accuracy, and honesty rules](#data-sources-accuracy-and-honesty-rules)
4. [Scoring formula](#scoring-formula)
5. [Installing Android Studio and building this project](#installing-android-studio-and-building-this-project)
6. [Manual test plan for the Realme GT 7 Pro (Android 16)](#manual-test-plan-for-the-realme-gt-7-pro-android-16)
7. [Checking whether your device is rooted (without rooting it)](#checking-whether-your-device-is-rooted-without-rooting-it)
8. [Security warning about rooting](#security-warning-about-rooting)
9. [What this app cannot do (and why)](#what-this-app-cannot-do-and-why)
10. [Future architectures (out of scope for this MVP)](#future-architectures-out-of-scope-for-this-mvp)
11. [Build/test status of this repository snapshot](#buildtest-status-of-this-repository-snapshot)

---

## Supported vs. unsupported matrix

| Capability | Status | Why |
|---|---|---|
| Discover and request Wi-Fi + cellular networks for app-owned flows | **Supported** | `ConnectivityManager.requestNetwork` + `NetworkRequest` for `TRANSPORT_WIFI` / `TRANSPORT_CELLULAR` with `NET_CAPABILITY_INTERNET`. `CHANGE_NETWORK_STATE` is a normal install-time permission. Requesting both helps keep cellular available while Wi-Fi is the system default, subject to OEM and data-policy restrictions. |
| Read validated/metered/roaming/bandwidth-estimate/interface/IP/DNS/route info per link | **Supported** | `NetworkCapabilities` + `LinkProperties`, both public APIs. Bandwidth is a driver estimate, not measured throughput - see below. |
| Read Wi-Fi SSID/BSSID or precise signal strength | **Not implemented (by design)** | Requires location permission on modern Android. This app deliberately does not request `ACCESS_FINE_LOCATION`, so these fields report Unknown. |
| Read cellular subscription/carrier details | **Not implemented (by design)** | Would require `READ_PHONE_STATE`. Not requested; out of scope for this MVP. |
| Independently probe each link's HTTP health (latency/jitter/loss) | **Supported** | Each probe opens an `HttpURLConnection` via `Network.openConnection(url)`, bound to that one network. |
| ICMP ping-based latency | **Not used, anywhere** | Many carriers/captive portals deprioritize or block ICMP; all "latency" here is HTTP connect/response timing, clearly labeled as such. |
| Score/rank links, app-owned per-flow selection with hysteresis | **Supported** | Pure Kotlin scoring + a hold-down/hysteresis selection policy (see below). Affects only sockets this app opens. |
| Make **other apps** use a specific link (phone-wide steering) | **Not supported by this app** | Requires a local `VpnService` acting as a userspace packet forwarder - a fundamentally different, far more invasive app design. Not built here. See [Future architectures](#future-architectures-out-of-scope-for-this-mvp). |
| Steer traffic for devices tethered to this phone's hotspot | **Not supported, non-root** | Tethering/NAT/routing for hotspot clients is handled by the kernel and privileged system services, invisible to a normal app's socket or VPN APIs. Requires `TETHER_PRIVILEGED`/system signing or root. This app never requests or fakes that permission. |
| Enable/disable the Wi-Fi hotspot | **Not supported, by design** | No public API for a normal app to toggle SoftAP. This app only opens Android's own tethering settings screen; you enable it yourself. |
| Read current hotspot on/off state | **Unknown, always** | No public, non-privileged API exists to read this reliably as of Android 16. Reported honestly as "Unknown" rather than guessed via reflection/hidden APIs (which this app never uses). |
| Attribute traffic bytes to Wi-Fi vs. cellular specifically | **Not supported by any public API** | `TrafficStats` gives this app's own UID totals, and device-wide *mobile* totals and *overall* totals - there is no public "Wi-Fi-only" counter, so this app never invents one. |
| True bandwidth bonding (combine Wi-Fi + cellular throughput for one flow) | **Not supported on-device alone** | Requires a remote aggregation server the device connects to over every link simultaneously (e.g. MPTCP-capable endpoint, or a custom bonding tunnel). See [Future architectures](#future-architectures-out-of-scope-for-this-mvp). |
| Root / privileged / hidden-API tricks of any kind | **Never used** | No reflection, no `iptables`, no hidden `WifiManager`/`ConnectivityManager` APIs, no `TETHER_PRIVILEGED`, no VPN blackhole tricks. |

---

## Architecture

```
app/src/main/java/com/windowssdwan/multilink/
├── model/        Pure Kotlin data classes - NO Android imports. Every
│                 nullable field means "unknown", never a fabricated
│                 default. Safe to unit test on the plain JVM.
│                 (TransportKind, LinkId, NetworkLinkSnapshot, ProbeSample,
│                 LinkHealth, LinkScore, TrafficSnapshot, HotspotState,
│                 CapabilityVerdict, SelectionState, ProbeConfig)
│
├── networking/   Android-facing layer: ConnectivityManager callbacks,
│                 NetworkCapabilities/LinkProperties -> model translation,
│                 the pure NetworkLinkReducer (Available/Lost -> map),
│                 BoundConnectionFactory (bind a connection to one
│                 Network), the app-owned NetworkSelector, and the
│                 PackageManager-based CapabilityInspector.
│
├── monitoring/   HealthProbe (per-network HTTPS probe loop),
│                 TrafficStatsReader (public TrafficStats wrapper), and
│                 MonitoringCoordinator, which owns starting/stopping one
│                 probe coroutine per live link and assembles health/score/
│                 traffic/capability state for the ViewModel.
│
├── scoring/      Pure Kotlin: JitterLossAggregator (rolling-window probe
│                 aggregation) and LinkScorer (the documented 0-100
│                 formula). No Android dependency.
│
├── policy/       Pure Kotlin: SelectionPolicy (hold-down/hysteresis
│                 app-owned link selection) and CapabilityVerdictPolicy
│                 (builds the human-readable capability verdict). No
│                 Android dependency.
│
├── ui/           Compose screen, ViewModel (StateFlow-based), and
│                 ui/theme (Material 3 theme) + ui/components (LinkCard,
│                 TrafficCard, CapabilityCard, SelectionCard,
│                 ControlsCard, LimitationsSection, HistorySparkline).
│
└── util/         Logger (state-change/failure logging only), DisplayFormat
                  (null-safe "Unknown" formatting), SettingsIntents (open
                  tethering settings), StreamUtil (minSdk-26-safe stream
                  read helper).
```

The `model`, `scoring`, and `policy` packages, plus
`networking/NetworkLinkReducer`, have zero Android dependencies and are
covered by local JVM unit tests under `app/src/test/...` - no
device/emulator needed for them. Everything that must talk to real
`android.net.*`/`android.util.Log` APIs lives in `networking/`,
`monitoring/`, and `ui/`.

---

## Data sources, accuracy, and honesty rules

This app follows one rule everywhere: **if a value cannot be obtained
without doing something out of scope, it says "Unknown" instead of
guessing.** Concretely:

- **Bandwidth ("Downstream/Upstream (estimate)")** comes from
  `NetworkCapabilities.getLinkDownstreamBandwidthKbps()` /
  `getLinkUpstreamBandwidthKbps()`. These are the platform/driver's
  *negotiated or estimated link capability* (e.g. a PHY speed class), **not
  measured throughput** of any traffic this app has sent. Labeled
  "(estimate)" everywhere it's shown.
- **Latency/jitter/loss** come only from this app's own HTTPS probe
  requests, bound to one specific link via `Network.openConnection(url)`.
  They are HTTP-layer connect/response timings, explicitly **not** ICMP
  round-trip time - this app never assumes ICMP is available, since many
  carriers/captive portals block or deprioritize it.
- **Signal strength** uses `NetworkCapabilities.getSignalStrength()`
  (API 29+). This reliably returns a value only when the request included
  `NET_CAPABILITY_SIGNAL_STRENGTH` *and* the caller holds location
  permission. This app does not request location permission, so this
  field will typically show "Unknown" - that is expected, not a bug.
- **Traffic totals** use `android.net.TrafficStats`: this app's own UID
  RX/TX, the device-wide *mobile* RX/TX totals, and the device-wide *all
  networks* RX/TX totals. There is no public API to get a "Wi-Fi-only"
  total, so this app never fabricates one. Any counter the device/kernel
  reports as `TrafficStats.UNSUPPORTED` is shown as "Unsupported" - never
  as zero bytes.
- **Hotspot/SoftAP state** has no public, non-privileged read API as of
  Android 16, so it is always reported as "Unknown" here. This app never
  uses reflection or hidden `WifiManager` APIs to work around that.
- **Privileged tethering permission** is checked read-only via
  `PackageManager.checkPermission(TETHER_PRIVILEGED, ...)` and is expected
  to always be `false` for this app - it is never declared or requested.

---

## Scoring formula

Implemented in `scoring/LinkScorer.kt`. Four independently-computable
components sum to at most 100 points:

| Component | Max points | Based on |
|---|---:|---|
| Connectivity | 40 | 40 if platform-validated; 15 if it only declares internet capability without validation yet; 0 otherwise. Always computable. |
| Reliability | 30 | `30 * (1 - lossFraction)` from the rolling probe window. Unknown until the first probe sample completes. |
| Latency | 20 | Linear ramp: `<= 80 ms` average successful request time = 20 points, `>= 1500 ms` = 0 points. Unknown until the first *successful* sample. |
| Jitter | 10 | Linear ramp: `0 ms` mean-abs-difference between consecutive successful timings = 10 points, `>= 400 ms` = 0 points. Unknown until 2 successful samples. |

**Unknown handling:** any component that cannot yet be computed is
excluded from *both* the numerator and denominator when combining into the
final 0-100 total - it is never treated as 0 (bad) or 100 (good). A
brand-new, validated Wi-Fi link with no probe samples yet therefore scores
100 based purely on what is known (connectivity), not a misleadingly low
number. The UI/tests can check `knownComponentCount` (0-4) to see how much
of a score is actually backed by data.

Selection hysteresis (`policy/SelectionPolicy.kt`): once a link is
selected for this app's own traffic, a challenger must (a) wait out a
hold-down window (default 15s) since the last switch, and (b) then beat
the current selection's score by a minimum margin (default 8 points)
before this app switches to it. This prevents rapid flapping between two
similarly-scoring links.

---

## Installing Android Studio and building this project

This project was authored in an environment with **no Java, Gradle, adb,
`ANDROID_HOME`, or `ANDROID_SDK_ROOT` installed**, so none of the steps
below were run here. The project is a standard Gradle-Kotlin-DSL Android
project and should import cleanly, but you must build/run it yourself:

1. Install **Android Studio** (a current stable channel release; it
   bundles a compatible JDK and can install the Android SDK for you on
   first run).
2. Open Android Studio -> **Open** -> select this folder
   (`android_multilink_manager`, the one containing `settings.gradle.kts`).
3. On first sync, Android Studio will likely offer to:
   - generate the missing Gradle wrapper jar/scripts (see
     `gradle/wrapper/WRAPPER_NOTE.md` - this project intentionally ships
     without a fabricated `gradle-wrapper.jar`), and
   - install `compileSdk`/`targetSdk` 36 (Android 16) SDK platform +
     build-tools, and a JDK 17, if not already present.
   Accept these prompts.
4. If Studio's "Upgrade Assistant" suggests a newer Android Gradle Plugin/
   Kotlin version than the ones pinned in `build.gradle.kts`/
   `app/build.gradle.kts`, it is generally safe to accept - Studio knows
   the best-matching versions for the SDK/Gradle it ships with; the
   versions pinned here were a sensible-stable combination at authoring
   time, not a hard requirement.
5. **Build** -> Make Project (or `./gradlew assembleDebug` once the
   wrapper is generated, from a terminal with a JDK on `PATH`).
6. **Run** -> select your device (a Realme GT 7 Pro over USB with USB
   debugging enabled, or any API 26+ device/emulator) -> Run 'app'.
7. To run the local unit tests: right-click
   `app/src/test/java/.../scoring` (or any test package) -> **Run Tests**,
   or `./gradlew testDebugUnitTest` from a terminal. These require no
   device/emulator.
8. To run the one instrumented test
   (`app/src/androidTest/.../DashboardScreenSmokeTest.kt`): connect a
   device/emulator and use **Run** -> select the androidTest configuration,
   or `./gradlew connectedDebugAndroidTest`.

No credentials, API keys, or external services are required to build,
run, or test this app.

---

## Manual test plan for the Realme GT 7 Pro (Android 16)

Run these after installing a debug build. For each scenario, start
monitoring and observe the dashboard for at least the configured probe
interval (default 5s) x a few rounds before judging results.

1. **Wi-Fi only.** Connect to Wi-Fi, disable mobile data (or ensure no SIM
   is active). Expect: one Wi-Fi card, validated, with a score rising to
   ~100 as probes succeed; no cellular card (or a cellular card with
   `hasInternetCapability = false` if a SIM is present but data is off).
2. **Cellular only.** Disable/forget Wi-Fi, enable mobile data. Expect:
   one cellular card, validated, scoring similarly; no Wi-Fi card.
3. **Both simultaneously.** Enable Wi-Fi (connected) and mobile data.
   Expect: both cards present and validated at the same time, the
   Capability card reporting "Both Wi-Fi + cellular validated right now:
   Yes", and the Selection card showing this app's own chosen path with a
   reason string.
4. **Hotspot manually enabled (from Settings, not this app).** With
   cellular data on, open Android's own hotspot settings (this app's
   "Open hotspot / tethering settings" button can take you there) and
   enable the hotspot. Expect: the phone's own Wi-Fi/cellular cards behave
   as in scenario 3 (the hotspot itself does not appear as a "link" this
   app tracks, since this app only tracks networks *it* can use, not
   networks it is serving to others). Confirm the Capability card still
   correctly states hotspot-client steering is unsupported.
5. **Disconnect Wi-Fi while both are up.** Expect: the Wi-Fi card
   disappears within a few seconds (`onLost`), its probe loop stops
   (check logcat for "Stopping monitoring" / "Stopping probe loop" tags
   under `MultiLinkManager:*`), and the Selection card (if it had chosen
   Wi-Fi) re-selects cellular immediately, since the previously-selected
   link is no longer eligible.
6. **Disconnect cellular (airplane-mode the data, keep Wi-Fi) while both
   are up.** Symmetric to scenario 5.
7. **Endpoint failure.** In the Controls card, set the probe URL(s) to an
   address that will fail (e.g. an unreachable host or a domain that
   returns a non-2xx/206 status). Expect: the link's card shows increasing
   loss / "Unknown" latency once no samples ever succeed, its reliability
   component drops while latency/jitter stay Unknown (not zero), and its
   score falls accordingly - but the app keeps running (never crashes on
   probe failure).

Across all scenarios, watch logcat filtered to `MultiLinkManager:*` -
state-change/failure logs (link appeared/disappeared, selection changed,
probe start/stop) should appear; there should be no per-sample or
per-packet log spam.

---

## Checking whether your device is rooted (without rooting it)

This app itself never requires root and never attempts to detect root via
invasive means. If you simply want to confirm your **stock** Realme GT 7
Pro is not rooted (the normal, out-of-the-box state for a retail device),
you can check safely without installing or running any rooting tool:

- **Settings check:** Settings -> About phone -> look for any mention of
  "unlocked bootloader" or custom recovery; stock/unmodified retail
  devices do not show this.
- **adb check (read-only, no changes):** with USB debugging enabled and
  `adb` available on your PC, run `adb shell su -c id` - on a non-rooted
  stock device this fails ("su: not found" or "permission denied"),
  because there is no `su` binary. Do **not** interpret a failure as
  something to "fix" - it's the expected, safe state.
- **Third-party root-checker apps** (e.g. from a trusted app store) can
  confirm this without your involvement; these merely check for the
  presence of `su`/Magisk/known root markers and do not modify anything.
- A stock Realme GT 7 Pro, as sold, is normally **not** rooted, and
  Realme's own warranty/security model assumes it stays that way. This
  app's entire design (see the matrix above) assumes and requires no root.

## Security warning about rooting

**This project does not root your device, and does not want you to.**
Rooting (unlocking the bootloader, flashing Magisk/su, etc.) permanently
weakens your device's security model: it can disable Google
SafetyNet/Play Integrity (breaking banking/payment/DRM apps), void your
manufacturer warranty, expose you to malware that can gain full
device/data access if any app you install requests root, make future OTA
updates unreliable or impossible without a full reflash, and in the worst
case can hard-brick the device (Realme, like most OEMs, does not
guarantee unbrick support after an unlocked/rooted attempt goes wrong).
If you choose to explore the rooted/privileged architecture described
below on a device you own, do so on a device you can afford to lose data
on or replace, understand your own OEM's specific unlock process and
warranty terms first, and never on your daily-driver phone or SIM.

---

## What this app cannot do (and why)

Restated plainly, since this is the most important thing to get right:

- **It cannot make other apps use a specific network.** Android has no
  public API for a normal app to redirect another app's sockets. The only
  way to intercept/redirect other apps' traffic is a local `VpnService`,
  which turns this app into a userspace packet forwarder for the *whole
  device* - a fundamentally different, more invasive design with its own
  performance and trust trade-offs, and it is *still* not visible to
  traffic from hotspot clients (see below). Not built in this MVP.
- **It cannot steer, inspect, or influence traffic from devices tethered
  to this phone's hotspot.** Once you enable the hotspot (which you must
  do yourself, via Settings), tethered clients' packets are handled by the
  kernel's own NAT/tethering stack before any app - VPN or otherwise - on
  the phone ever sees them. Controlling that requires
  `TETHER_PRIVILEGED`/system signing, or root with iptables/nftables
  access. This app never requests or emulates that permission and never
  will in this design.
- **It cannot combine (bond) Wi-Fi + cellular bandwidth into one faster
  connection.** A single TCP/TLS connection can only ride one network
  interface at a time. True bandwidth bonding needs either kernel-level
  MPTCP support with a cooperating remote MPTCP endpoint, or a custom
  tunnel client/server pair that splits one logical stream across both
  links and reassembles it remotely. Neither exists on-device alone.

## Future architectures (out of scope for this MVP)

Two follow-on projects would be needed to go further than this MVP - both
are deliberately **not** implemented here:

1. **Privileged/rooted phone-wide router.** A `VpnService`-based
   forwarder (no root required for *phone-wide, this-device* app
   steering) could redirect all of this phone's own app traffic through a
   chosen underlying network, by having the VPN interface's tunnel reads/
   writes go through a userspace proxy bound to the selected
   `android.net.Network`. Going further, to also cover **hotspot-client**
   traffic, would additionally require either: a rooted device with
   direct `iptables`/`nftables` control over the tethering NAT table, or a
   privileged/system-signed build with `TETHER_PRIVILEGED` and the
   `TetheringManager` APIs (available to OEM/carrier-signed or
   device-owner-provisioned apps, not to a normal sideloaded/Play app).
   This is real, deliberate scope creep beyond "safe non-root MVP" and
   should be a clearly separate, clearly-labeled project if ever pursued.
2. **True bandwidth-bonding remote aggregation server.** To actually
   combine Wi-Fi + cellular throughput for one logical stream, the device
   needs a remote server it can reach over *both* links simultaneously,
   which either speaks MPTCP (Linux kernel MPTCP support, with the app
   using a raw multipath-capable socket) or runs a custom bonding
   protocol: the client splits/sequences outgoing packets across both
   links, the server reassembles and forwards to the real destination,
   and reverse traffic is split back across both links to the client. This
   requires infrastructure this project intentionally does not include
   (no server component, no credentials, nothing installed here) and is a
   materially larger undertaking (protocol design, loss/reordering
   recovery, server hosting/ops) than this feasibility MVP.

---

## Build/test status of this repository snapshot

**Not built or tested in this environment.** The environment this project
was authored in has no Java, Gradle, adb, `ANDROID_HOME`, or
`ANDROID_SDK_ROOT` installed, and no internet-connected Android toolchain
was installed to produce this project (per the constraints of that task).
Every source file was written and cross-checked by careful manual
inspection (package/import consistency, Android API level availability
for `minSdk 26`, Gradle/AGP/Kotlin/Compose version compatibility for
`compileSdk 36`), but this is **not a substitute for actually compiling
it**. The first thing to do after cloning this into a machine with Android
Studio is a full Gradle sync and build, and running the unit test suite
under `app/src/test`, before trusting any further changes.
