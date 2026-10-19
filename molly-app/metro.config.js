const { getDefaultConfig } = require('expo/metro-config');

// SDK 54's Metro resolves package.json `exports` natively, so
// `thinking-orbs/engine` and friends need no custom resolver.
module.exports = getDefaultConfig(__dirname);
