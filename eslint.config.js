import js from "@eslint/js";
import globals from "globals";

export default [
	js.configs.recommended,
	{
		files: ["static/js/**/*.js"],
		languageOptions: {
			ecmaVersion: 2022,
			sourceType: "module",
			globals: {
				...globals.browser,
				...globals.es2021,
				marked: "readonly",
				hljs: "readonly",
				mermaid: "readonly",
				katex: "readonly",
				renderMathInElement: "readonly"
			}
		},
		rules: {
			"no-unused-vars": ["warn", { 
				"argsIgnorePattern": "^_",
				"varsIgnorePattern": "^_",
				"destructuredArrayIgnorePattern": "^_",
				"caughtErrorsIgnorePattern": "^_"
			}],
			"no-console": ["warn", { "allow": ["warn", "error", "log"] }],
			"eqeqeq": "error",
			"no-var": "error",
			"prefer-const": "warn",
			"no-use-before-define": ["error", { "functions": false, "classes": false, "variables": false }]
		}
	}
];