import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
export default tseslint.config({ignores:['dist','node_modules','docs','playwright-report','test-results']},js.configs.recommended,...tseslint.configs.recommended,{files:['src/**/*.{ts,tsx}'],languageOptions:{globals:globals.browser},plugins:{'react-hooks':reactHooks,'react-refresh':reactRefresh},rules:{'react-hooks/rules-of-hooks':'error','react-hooks/exhaustive-deps':'warn','react-refresh/only-export-components':['warn',{allowConstantExport:true}]}},{files:['*.{js,ts}','e2e/**/*.ts'],languageOptions:{globals:globals.node}});
