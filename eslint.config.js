export default [
    {
        files: ["sentinel/static/script-*.js", "sentinel/static/i18n.js"],
        languageOptions: {
            ecmaVersion: 2022,
            globals: {
                window: "readonly", document: "readonly", console: "readonly",
                fetch: "readonly", navigator: "readonly", localStorage: "readonly",
                sessionStorage: "readonly", setTimeout: "readonly", setInterval: "readonly",
                clearInterval: "readonly", clearTimeout: "readonly",
                alert: "readonly", confirm: "readonly", prompt: "readonly",
                URL: "readonly", URLSearchParams: "readonly", Blob: "readonly",
                FormData: "readonly", FileReader: "readonly", performance: "readonly",
                MutationObserver: "readonly", ResizeObserver: "readonly",
                EventSource: "readonly", BroadcastChannel: "readonly",
                Notification: "readonly", Worker: "readonly",
                // Sentinel globals — definovány v jiných souborech nebo inline
                io: "readonly", Chart: "readonly", Sortable: "readonly",
                QRCode: "readonly", hljs: "readonly",
                t: "readonly", currentLang: "readonly", toggleLang: "readonly",
                socket: "readonly",
            },
        },
        rules: {
            "no-undef": "warn",
            "no-unused-vars": ["warn", { "varsIgnorePattern": "^_", "argsIgnorePattern": "^_" }],
            "no-redeclare": "error",          // zachytí _DASH_WIDGETS duplicity
            "no-duplicate-case": "error",
            "no-unreachable": "warn",
            "eqeqeq": ["warn", "smart"],
            "no-eval": "warn",         // eval je záměrný pro dynamic script injection z SSR HTML
            "no-implied-eval": "error",
            "no-new-func": "error",
        },
    },
];
