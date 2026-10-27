/**
 * Motaem Cloud Restaurant OS - Pure Native Landing Page Animations Engine
 * 100% Vanilla JS & CSS — Zero external libraries, Zero CDNs.
 * Built for maximum speed, zero network latency, and silky-smooth 60fps animations.
 */

(function () {
    'use strict';

    // Check reduced motion preference
    const prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // Detect language (Arabic / English / French / Turkish / German)
    function detectLanguage() {
        const docLang = (document.documentElement.lang || '').toLowerCase().substring(0, 2);
        if (['en', 'fr', 'tr', 'de', 'ar'].includes(docLang)) return docLang;

        try {
            const params = new URLSearchParams(window.location.search);
            const qLang = (params.get('lang') || '').toLowerCase().substring(0, 2);
            if (['en', 'fr', 'tr', 'de', 'ar'].includes(qLang)) return qLang;

            const landingEl = document.getElementById('landing-page');
            if (landingEl) {
                const elLang = (landingEl.getAttribute('lang') || '').toLowerCase().substring(0, 2);
                if (['en', 'fr', 'tr', 'de', 'ar'].includes(elLang)) return elLang;
                if (landingEl.getAttribute('dir') === 'ltr') return 'en';
            }
        } catch (e) {}

        const docDir = (document.documentElement.dir || '').toLowerCase();
        if (docDir === 'ltr') return 'en';

        return 'ar';
    }

    // Safety fallback helper to ensure text & numbers are never blank or zero
    function ensureFallbackValues() {
        const typewriterEl = document.getElementById('hero-typewriter');
        if (typewriterEl && (!typewriterEl.textContent.trim() || typewriterEl.textContent === '\u200B')) {
            const lang = detectLanguage();
            if (lang === 'fr') {
                typewriterEl.textContent = 'Chaînes de restaurants modernes';
            } else if (lang === 'tr') {
                typewriterEl.textContent = 'Modern Restoran Zincirleri';
            } else if (lang === 'de') {
                typewriterEl.textContent = 'Moderne Restaurantketten';
            } else if (lang === 'en') {
                typewriterEl.textContent = 'Modern Restaurant Chains';
            } else {
                typewriterEl.textContent = 'سلاسل المطاعم الحديثة';
            }
        }

        const elLatency = document.getElementById('metric-latency');
        if (elLatency) elLatency.textContent = '0';
        const elHrs = document.getElementById('metric-uptime-hrs');
        if (elHrs) elHrs.textContent = '24';
        const elPct = document.getElementById('metric-uptime-pct');
        if (elPct) elPct.textContent = '99.9';

        document.querySelectorAll('[data-counter-target]').forEach((el) => {
            const targetVal = parseFloat(el.getAttribute('data-counter-target')) || 0;
            const isFloat = el.getAttribute('data-counter-float') === 'true';
            const hasComma = el.getAttribute('data-counter-comma') === 'true';
            if (isFloat) el.textContent = targetVal.toFixed(1);
            else if (hasComma) el.textContent = Math.round(targetVal).toLocaleString('en-US');
            else el.textContent = Math.round(targetVal);
        });
    }

    // Handle reduced motion preference early and cleanly
    if (prefersReducedMotion) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', ensureFallbackValues);
        } else {
            ensureFallbackValues();
        }
        return;
    }

    // Self-healing fallback styles injection if CSS not yet present
    function injectStylesIfNeeded() {
        if (document.getElementById('motaem-anim-styles')) return;
        const style = document.createElement('style');
        style.id = 'motaem-anim-styles';
        style.textContent = `
            @keyframes heroReveal {
                0% { opacity: 0; transform: translateY(24px); }
                100% { opacity: 1; transform: translateY(0); }
            }
            .native-typewriter-cursor, .typed-cursor {
                display: inline-block;
                color: #7C3AED;
                font-weight: 300;
                margin-inline-start: 2px;
                animation: nativeCursorBlink 0.8s infinite;
                vertical-align: baseline;
            }
            @keyframes nativeCursorBlink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
            @keyframes heroAmbientGlowPulse {
                0%, 100% { transform: translate(-50%, -50%) scale(1); opacity: 0.12; }
                50% { transform: translate(-50%, -50%) scale(1.18); opacity: 0.24; }
            }
            #hero-ambient-glow { animation: heroAmbientGlowPulse 4.5s ease-in-out infinite; }
            .motaem-anim-active .hero-anim-item {
                opacity: 0;
                transform: translateY(24px);
                animation: heroReveal 0.65s cubic-bezier(0.16, 1, 0.3, 1) both;
            }
            .motaem-anim-active .section-header-reveal .reveal-item,
            .motaem-anim-active .bento-card,
            .motaem-anim-active .stat-card,
            .motaem-anim-active .pricing-card,
            .motaem-anim-active .faq-item,
            .motaem-anim-active .conversion-banner,
            .motaem-anim-active .banner-item,
            .motaem-anim-active .footer-reveal {
                opacity: 0;
                transform: translateY(24px);
                transition: opacity 0.65s cubic-bezier(0.16, 1, 0.3, 1), transform 0.65s cubic-bezier(0.16, 1, 0.3, 1);
                will-change: opacity, transform;
            }
            .motaem-anim-active .hero-anim-item.is-revealed,
            .motaem-anim-active .section-header-reveal .reveal-item.is-revealed,
            .motaem-anim-active .bento-card.is-revealed,
            .motaem-anim-active .stat-card.is-revealed,
            .motaem-anim-active .pricing-card.is-revealed,
            .motaem-anim-active .faq-item.is-revealed,
            .motaem-anim-active .conversion-banner.is-revealed,
            .motaem-anim-active .banner-item.is-revealed,
            .motaem-anim-active .footer-reveal.is-revealed {
                opacity: 1;
                transform: translateY(0);
            }
            @media (prefers-reduced-motion: reduce) {
                .motaem-anim-active .hero-anim-item,
                .motaem-anim-active .section-header-reveal .reveal-item,
                .motaem-anim-active .bento-card,
                .motaem-anim-active .stat-card,
                .motaem-anim-active .pricing-card,
                .motaem-anim-active .faq-item,
                .motaem-anim-active .conversion-banner,
                .motaem-anim-active .banner-item,
                .motaem-anim-active .footer-reveal {
                    opacity: 1 !important;
                    transform: none !important;
                    transition: none !important;
                    animation: none !important;
                }
                #hero-ambient-glow { animation: none !important; }
            }
        `;
        document.head.appendChild(style);
    }

    // =========================================================================
    // 1. NATIVE TYPEWRITER ENGINE
    // =========================================================================
    function initNativeTypewriter() {
        const typewriterEl = document.getElementById('hero-typewriter');
        if (!typewriterEl) return;

        const lang = detectLanguage();
        let words = [
            'سلاسل المطاعم الحديثة',
            'المطابخ السحابية',
            'الكافيهات والمقاهي العصرية',
            'أسطول التوصيل وخدمات الضيافة'
        ];

        if (lang === 'en') {
            words = [
                'Modern Restaurant Chains',
                'Cloud & Ghost Kitchens',
                'Fast Casuals & Cafes',
                'Hospitality & Delivery Fleets'
            ];
        } else if (lang === 'fr') {
            words = [
                'Chaînes de restaurants modernes',
                'Cuisines fantômes & cloud',
                'Cafés & restauration rapide',
                'Flottes de livraison & hospitalité'
            ];
        } else if (lang === 'tr') {
            words = [
                'Modern Restoran Zincirleri',
                'Bulut ve Hayalet Mutfaklar',
                'Hızlı Servis ve Kafeler',
                'Teslimat Filosu ve Ağırlama'
            ];
        } else if (lang === 'de') {
            words = [
                'Moderne Restaurantketten',
                'Cloud- & Ghost-Kitchens',
                'Fast-Casual & Cafés',
                'Lieferflotten & Gastronomie'
            ];
        }

        // Find or create pulsing purple cursor element
        let cursorEl = typewriterEl.parentNode.querySelector('.native-typewriter-cursor');
        if (!cursorEl) {
            cursorEl = document.createElement('span');
            cursorEl.className = 'native-typewriter-cursor';
            cursorEl.setAttribute('aria-hidden', 'true');
            cursorEl.textContent = '|';
            typewriterEl.parentNode.insertBefore(cursorEl, typewriterEl.nextSibling);
        }

        let wordIdx = 0;
        let charIdx = 0;
        let isDeleting = false;

        const TYPE_SPEED = 65;      // Smooth natural typing speed
        const DELETE_SPEED = 32;    // Snappy backspacing speed
        const PAUSE_END = 2200;     // Pause at complete word
        const PAUSE_START = 350;    // Pause before typing next word
        const INITIAL_DELAY = 150;  // Initial start delay

        function tick() {
            const currentWord = words[wordIdx];
            const chars = Array.from(currentWord);

            if (isDeleting) {
                charIdx--;
                // Zero-width space preserves line box height when text is fully backspaced
                typewriterEl.textContent = chars.slice(0, charIdx).join('') || '\u200B';

                if (charIdx === 0) {
                    isDeleting = false;
                    wordIdx = (wordIdx + 1) % words.length;
                    setTimeout(tick, PAUSE_START);
                    return;
                }
                setTimeout(tick, DELETE_SPEED);
            } else {
                charIdx++;
                typewriterEl.textContent = chars.slice(0, charIdx).join('');

                if (charIdx === chars.length) {
                    isDeleting = true;
                    setTimeout(tick, PAUSE_END);
                    return;
                }
                setTimeout(tick, TYPE_SPEED);
            }
        }

        // Start with zero-width space to keep line height stable
        typewriterEl.textContent = '\u200B';
        setTimeout(tick, INITIAL_DELAY);
    }

    // =========================================================================
    // 2. NATIVE COUNTERS ENGINE (requestAnimationFrame + Easing)
    // =========================================================================
    function animateCounter(element, startVal, endVal, duration, options = {}) {
        if (!element) return;
        const isFloat = options.isFloat || false;
        const hasComma = options.hasComma || false;

        // Set initial formatted value immediately to eliminate any frame-1 jump/flicker
        if (isFloat) element.textContent = startVal.toFixed(1);
        else if (hasComma) element.textContent = Math.round(startVal).toLocaleString('en-US');
        else element.textContent = Math.round(startVal);

        if (startVal === endVal) return;

        const startTime = performance.now();

        function update(currentTime) {
            const elapsed = currentTime - startTime;
            const progress = Math.min(elapsed / duration, 1);
            // Cubic Ease Out: 1 - (1 - t)^3 for smooth 60fps deceleration
            const ease = 1 - Math.pow(1 - progress, 3);
            const currentVal = startVal + (endVal - startVal) * ease;

            if (isFloat) {
                element.textContent = currentVal.toFixed(1);
            } else if (hasComma) {
                element.textContent = Math.round(currentVal).toLocaleString('en-US');
            } else {
                element.textContent = Math.round(currentVal);
            }

            if (progress < 1) {
                requestAnimationFrame(update);
            } else {
                if (isFloat) element.textContent = endVal.toFixed(1);
                else if (hasComma) element.textContent = Math.round(endVal).toLocaleString('en-US');
                else element.textContent = Math.round(endVal);
            }
        }

        requestAnimationFrame(update);
    }

    function initHeroCounters() {
        const elLatency = document.getElementById('metric-latency');
        const elHrs = document.getElementById('metric-uptime-hrs');
        const elPct = document.getElementById('metric-uptime-pct');

        // Hero counters start immediately from zero on page open without waiting for scroll
        if (elHrs) animateCounter(elHrs, 0, 24, 1600);
        if (elPct) animateCounter(elPct, 0, 99.9, 1600, { isFloat: true });
        if (elLatency) animateCounter(elLatency, 0, 0, 1400);
    }

    function triggerCounterForElement(el) {
        if (!el || el.dataset.counterStarted === 'true') return;
        el.dataset.counterStarted = 'true';
        const targetVal = parseFloat(el.getAttribute('data-counter-target')) || 0;
        const isFloat = el.getAttribute('data-counter-float') === 'true';
        const hasComma = el.getAttribute('data-counter-comma') === 'true';
        animateCounter(el, 0, targetVal, 1800, { isFloat, hasComma });
    }

    function initStatsSectionCounters() {
        const statCounters = document.querySelectorAll('[data-counter-target]');
        if (statCounters.length === 0) return;

        if ('IntersectionObserver' in window) {
            const observer = new IntersectionObserver((entries, obs) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) {
                        triggerCounterForElement(entry.target);
                        obs.unobserve(entry.target);
                    }
                });
            }, {
                threshold: 0.08,
                rootMargin: '0px 0px -20px 0px'
            });

            statCounters.forEach((el) => observer.observe(el));
        } else {
            statCounters.forEach((el) => triggerCounterForElement(el));
        }
    }

    // =========================================================================
    // 3. NATIVE SCROLL REVEAL ENGINE (IntersectionObserver + CSS Transitions)
    // =========================================================================
    function revealElement(el, delay = 0) {
        if (!el || el.classList.contains('is-revealed')) return;
        el.style.transitionDelay = `${delay}ms`;
        el.classList.add('is-revealed');
        setTimeout(() => {
            el.style.transitionDelay = '';
        }, delay + 700);
    }

    function initScrollReveal() {
        injectStylesIfNeeded();
        document.documentElement.classList.add('motaem-anim-active');

        // 1. Hero elements: stagger waterfall immediately on load via keyframe delays
        const heroItems = document.querySelectorAll('.hero-anim-item');
        heroItems.forEach((item, idx) => {
            const delay = 50 + idx * 75;
            item.style.animationDelay = `${delay}ms`;
            item.classList.add('is-revealed');
        });

        if (!('IntersectionObserver' in window)) {
            document.querySelectorAll(
                '.section-header-reveal .reveal-item, .bento-card, .stat-card, .pricing-card, .faq-item, .conversion-banner, .banner-item, .footer-reveal'
            ).forEach((el) => {
                el.classList.add('is-revealed');
                const counter = el.querySelector('[data-counter-target]');
                if (counter) triggerCounterForElement(counter);
            });
            return;
        }

        const observerOptions = {
            threshold: 0.08,
            rootMargin: '0px 0px -20px 0px'
        };

        const revealObserver = new IntersectionObserver((entries, obs) => {
            const intersecting = entries.filter((e) => e.isIntersecting);
            intersecting.forEach((entry, idx) => {
                const target = entry.target;

                if (target.classList.contains('section-header-reveal')) {
                    const items = target.querySelectorAll('.reveal-item');
                    if (items.length > 0) {
                        items.forEach((item, itemIdx) => revealElement(item, itemIdx * 85));
                    } else {
                        revealElement(target, 0);
                    }
                } else if (target.classList.contains('conversion-banner')) {
                    revealElement(target, 0);
                    const items = target.querySelectorAll('.banner-item');
                    items.forEach((item, itemIdx) => revealElement(item, 70 + itemIdx * 75));
                } else {
                    // Stagger cards / items in the same viewport batch
                    revealElement(target, idx * 80);

                    // If stat card, coordinate counter roll synchronously
                    if (target.classList.contains('stat-card')) {
                        const counter = target.querySelector('[data-counter-target]');
                        if (counter) triggerCounterForElement(counter);
                    }
                }

                obs.unobserve(target);
            });
        }, observerOptions);

        // Observe section headers
        document.querySelectorAll('.section-header-reveal').forEach((el) => revealObserver.observe(el));

        // Observe Bento Grid cards
        document.querySelectorAll('.bento-card').forEach((el) => revealObserver.observe(el));

        // Observe Stat cards
        document.querySelectorAll('.stat-card').forEach((el) => revealObserver.observe(el));

        // Observe Pricing cards
        document.querySelectorAll('.pricing-card').forEach((el) => revealObserver.observe(el));

        // Observe FAQ items
        document.querySelectorAll('.faq-item').forEach((el) => revealObserver.observe(el));

        // Observe Conversion Banner
        const conversionBanner = document.querySelector('.conversion-banner');
        if (conversionBanner) revealObserver.observe(conversionBanner);

        // Observe Footer
        const footerEl = document.querySelector('.footer-reveal');
        if (footerEl) revealObserver.observe(footerEl);

        // Safety fallback: reveal any remaining items if scrolled near bottom
        window.addEventListener('scroll', function onScrollCheck() {
            if ((window.innerHeight + window.scrollY) >= (document.documentElement.scrollHeight - 80)) {
                document.querySelectorAll(
                    '.section-header-reveal .reveal-item, .bento-card, .stat-card, .pricing-card, .faq-item, .conversion-banner, .banner-item, .footer-reveal'
                ).forEach((el) => {
                    if (!el.classList.contains('is-revealed')) {
                        revealElement(el, 0);
                        const counter = el.querySelector('[data-counter-target]');
                        if (counter) triggerCounterForElement(counter);
                    }
                });
            }
        }, { passive: true });
    }

    // =========================================================================
    // INITIALIZATION LIFECYCLE
    // =========================================================================
    function startEngine() {
        initScrollReveal();
        initNativeTypewriter();
        initHeroCounters();
        initStatsSectionCounters();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', startEngine);
    } else {
        startEngine();
    }
})();
