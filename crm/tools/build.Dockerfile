# Build environment for Daybook CRM (Rust + Dioxus 0.7).
# One image builds every target from Linux:
#   web (WASM, also the iPhone home-screen app), Windows (cross, x86_64-pc-windows-gnu + NSIS installer)
#   and Android (APK, stage "android").
# iOS needs a Mac with Xcode: `dx bundle --platform ios --release` there.
#
#   docker build -f crm/tools/build.Dockerfile --target base    -t daybook-crm-build   crm/tools
#   docker build -f crm/tools/build.Dockerfile --target android -t daybook-crm-android crm/tools

FROM rust:1-bookworm AS base
# Laptop-friendly: half the threads, so overnight builds don't run the CPU at its limit.
ENV CARGO_BUILD_JOBS=6
RUN apt-get update && apt-get install -y --no-install-recommends \
      mingw-w64 nsis clang lld cmake pkg-config unzip zip ca-certificates curl wget \
      python3 libssl-dev imagemagick \
    && rm -rf /var/lib/apt/lists/*
RUN rustup target add wasm32-unknown-unknown x86_64-pc-windows-gnu \
 && rustup component add rustfmt clippy
RUN cargo install dioxus-cli --version 0.7.10 --locked \
 && rm -rf /usr/local/cargo/registry /usr/local/cargo/git
ENV CARGO_TARGET_DIR=/target
WORKDIR /src/crm

FROM base AS android
RUN apt-get update && apt-get install -y --no-install-recommends openjdk-17-jdk-headless \
    && rm -rf /var/lib/apt/lists/*
ENV ANDROID_HOME=/opt/android-sdk \
    ANDROID_SDK_ROOT=/opt/android-sdk \
    JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
RUN mkdir -p /opt/android-sdk/cmdline-tools && cd /tmp \
 && curl -fsSLo clt.zip https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip \
 && unzip -q clt.zip && mv cmdline-tools /opt/android-sdk/cmdline-tools/latest && rm clt.zip
ENV PATH=/opt/android-sdk/cmdline-tools/latest/bin:/opt/android-sdk/platform-tools:$PATH
RUN yes | sdkmanager --licenses > /dev/null \
 && sdkmanager "platform-tools" "platforms;android-35" "build-tools;35.0.0" "ndk;27.2.12479018" > /dev/null
ENV ANDROID_NDK_HOME=/opt/android-sdk/ndk/27.2.12479018 \
    NDK_HOME=/opt/android-sdk/ndk/27.2.12479018
RUN rustup target add aarch64-linux-android armv7-linux-androideabi x86_64-linux-android i686-linux-android
