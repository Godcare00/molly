# Vendored React Native ports (Libraries.dev)

These are the official React Native ports from https://github.com/Jakubantalik/Libraries.dev
(`packages/*/ports/react-native/*-native/src`), MIT licensed. They aren't published to npm yet, so
their sources live here and are imported as `@/vendor/<name>`. They need Skia >= 2, Reanimated >= 4
and react-native-worklets >= 0.7 (Expo SDK 54). When they land on npm, replace each folder with the
package and delete it from here.

`metal-fx-native` derives from Paper Shaders' liquidMetal (Apache-2.0) — see its NOTICE.
