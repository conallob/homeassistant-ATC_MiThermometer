import js from "@eslint/js";
import globals from "globals";

export default [
  js.configs.recommended,
  {
    files: ["custom_components/atc_mithermometer/www/**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: {
        ...globals.browser,
      },
    },
  },
  {
    files: ["tests/js/**/*.mjs"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: {
        ...globals.node,
        // These tests assign browser globals (window/document/etc.) onto
        // the Node global object so the card can be imported as-is.
        ...globals.browser,
      },
    },
  },
];
