/**
 * Motaem Jazzmin Custom JS
 * Enforces unified dark slate theme across all Django Admin pages
 */
(function () {
    // Force dark mode attribute on root document
    document.documentElement.setAttribute('data-bs-theme', 'dark');
    try {
        localStorage.setItem('jazzmin-theme-mode', 'dark');
    } catch (e) {}

    // Ensure on DOMContentLoaded in case any Jazzmin script switches it back
    document.addEventListener('DOMContentLoaded', function () {
        document.documentElement.setAttribute('data-bs-theme', 'dark');
        if (document.body) {
            document.body.classList.remove('bg-body-tertiary');
        }
    });
})();
