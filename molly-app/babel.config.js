module.exports = function (api) {
  api.cache(true);
  return {
    // babel-preset-expo (SDK 54) adds the react-native-worklets plugin itself,
    // so Reanimated 4 needs no plugin entry here.
    presets: ['babel-preset-expo'],
    plugins: [
      [
        'module-resolver',
        {
          root: ['./'],
          alias: { '@': './src' },
        },
      ],
    ],
  };
};
