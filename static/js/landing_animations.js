/**
 * Motaem Cloud Restaurant OS - Interactive Landing Page Animations Engine
 * Integrates Typed.js (Dynamic Headline Typewriter) + GSAP & ScrollTrigger (Counters & Motion)
 */

(function () {
    'use strict';

    // Safety fallback helper to ensure text & numbers are never blank or zero
    function ensureFallbackValues() {
        const typewriterEl = document.getElementById('hero-typewriter');
        if (typewriterEl && !typewriterEl.textContent.trim()) {
            const isEnglish = (document.documentElement.lang === 'en' || document.documentElement.dir === 'ltr');
            typewriterEl.textContent = isEnglish ? 'Modern Restaurant Chains' : 'سلاسل المطاعم الحديثة';
        }

        const elLatency = document.getElementById('metric-latency');
        if (elLatency && (!elLatency.textContent.trim() || elLatency.textContent === '0')) {
            elLatency.textContent = '0';
        }
        const elHrs = document.getElementById('metric-uptime-hrs');
        if (elHrs && (!elHrs.textContent.trim() || elHrs.textContent === '0')) {
            elHrs.textContent = '24';
        }
        const elPct = document.getElementById('metric-uptime-pct');
        if (elPct && (!elPct.textContent.trim() || elPct.textContent === '0')) {
            elPct.textContent = '99.9';
        }

        document.querySelectorAll('[data-counter-target]').forEach((el) => {
            if (!el.textContent.trim() || el.textContent === '0') {
                const targetVal = parseFloat(el.getAttribute('data-counter-target')) || 0;
                const isFloat = el.getAttribute('data-counter-float') === 'true';
                const hasComma = el.getAttribute('data-counter-comma') === 'true';
                if (isFloat) el.textContent = targetVal.toFixed(1);
                else if (hasComma) el.textContent = Math.round(targetVal).toLocaleString('en-US');
                else el.textContent = Math.round(targetVal);
            }
        });
    }

    // Respect reduced motion preference
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        ensureFallbackValues();
        return;
    }

    function initTypewriter() {
        const typewriterEl = document.getElementById('hero-typewriter');
        if (!typewriterEl) {
            return;
        }

        if (typeof window.Typed === 'undefined') {
            ensureFallbackValues();
            return;
        }

        const isEnglish = (document.documentElement.lang === 'en' || document.documentElement.dir === 'ltr');
        const typedStrings = isEnglish
            ? [
                'Modern Restaurant Chains',
                'Cloud & Ghost Kitchens',
                'Fast Casuals & Cafes',
                'Hospitality & Delivery Fleets'
              ]
            : [
                'سلاسل المطاعم الحديثة',
                'المطابخ السحابية',
                'الكافيهات والمقاهي العصرية',
                'أسطول التوصيل وخدمات الضيافة'
              ];

        try {
            new window.Typed('#hero-typewriter', {
                strings: typedStrings,
                typeSpeed: 55,
                backSpeed: 30,
                backDelay: 2200,
                startDelay: 100,
                loop: true,
                showCursor: true,
                cursorChar: '|',
                autoInsertCss: false
            });
        } catch (err) {
            console.warn('Typed.js initialization failed:', err);
            ensureFallbackValues();
        }
    }

    function initGsapAnimations() {
        if (typeof window.gsap === 'undefined') {
            ensureFallbackValues();
            return;
        }

        if (typeof window.ScrollTrigger !== 'undefined') {
            window.gsap.registerPlugin(window.ScrollTrigger);
        }

        // 1. Ambient Hero Mesh Glow subtle breathing animation
        const ambientGlow = document.getElementById('hero-ambient-glow');
        if (ambientGlow) {
            window.gsap.to(ambientGlow, {
                scale: 1.15,
                opacity: 0.22,
                duration: 4,
                repeat: -1,
                yoyo: true,
                ease: 'sine.inOut'
            });
        }

        // 2. Hero Elements (H1 headline, subheadline, CTAs, badges, metrics strip, voice demo teaser)
        const heroStaggerItems = document.querySelectorAll('.hero-anim-item');
        if (heroStaggerItems.length > 0) {
            window.gsap.from(heroStaggerItems, {
                opacity: 0,
                y: 22,
                duration: 0.75,
                stagger: 0.09,
                ease: 'power2.out',
                delay: 0.05
            });
        }

        // 3. Hero Metrics Strip (0ms, 24/7, 99.9%) - Smooth immediate rollup without ScrollTrigger
        const elLatency = document.getElementById('metric-latency');
        const elHrs = document.getElementById('metric-uptime-hrs');
        const elPct = document.getElementById('metric-uptime-pct');

        if (elLatency || elHrs || elPct) {
            const counterState = { latency: 60, hrs: 0, pct: 0 };
            if (elLatency) elLatency.textContent = Math.round(counterState.latency);
            if (elHrs) elHrs.textContent = Math.round(counterState.hrs);
            if (elPct) elPct.textContent = counterState.pct.toFixed(1);

            window.gsap.to(counterState, {
                latency: 0,
                hrs: 24,
                pct: 99.9,
                duration: 1.6,
                ease: 'power2.out',
                onUpdate: function () {
                    if (elLatency) elLatency.textContent = Math.round(counterState.latency);
                    if (elHrs) elHrs.textContent = Math.round(counterState.hrs);
                    if (elPct) elPct.textContent = counterState.pct.toFixed(1);
                }
            });
        }

        // 4. Section Headers Text Reveals (Badges, Titles & Subtitles)
        const sectionHeaders = document.querySelectorAll('.section-header-reveal');
        sectionHeaders.forEach((header) => {
            const items = header.querySelectorAll('.reveal-item');
            const targets = items.length > 0 ? items : header;
            if (window.ScrollTrigger) {
                window.gsap.from(targets, {
                    scrollTrigger: {
                        trigger: header,
                        start: 'top 85%',
                        once: true
                    },
                    opacity: 0,
                    y: 24,
                    duration: 0.7,
                    stagger: 0.1,
                    ease: 'power2.out'
                });
            }
        });

        // 5. Bento Grid Cards Staggered Scroll Reveal
        const bentoGrid = document.querySelector('#features .grid');
        const bentoCards = document.querySelectorAll('.bento-card');
        if (bentoCards.length > 0 && window.ScrollTrigger) {
            window.gsap.from(bentoCards, {
                scrollTrigger: {
                    trigger: bentoGrid || '#features',
                    start: 'top 85%',
                    once: true
                },
                opacity: 0,
                y: 35,
                duration: 0.65,
                stagger: 0.1,
                ease: 'power2.out'
            });
        }

        // 6. Live Stats Counter Strip & Numbers (Dark Section) - Triggers on scroll
        const statsSection = document.querySelector('.stats-section');
        if (statsSection && window.ScrollTrigger) {
            const statCards = statsSection.querySelectorAll('.stat-card');
            if (statCards.length > 0) {
                window.gsap.from(statCards, {
                    scrollTrigger: {
                        trigger: statsSection,
                        start: 'top 90%',
                        once: true
                    },
                    opacity: 0,
                    y: 20,
                    duration: 0.65,
                    stagger: 0.1,
                    ease: 'power2.out'
                });
            }
        }

        const statCounters = document.querySelectorAll('[data-counter-target]');
        if (statCounters.length > 0) {
            statCounters.forEach((el) => {
                const targetVal = parseFloat(el.getAttribute('data-counter-target')) || 0;
                const isFloat = el.getAttribute('data-counter-float') === 'true';
                const hasComma = el.getAttribute('data-counter-comma') === 'true';
                const animObj = { val: 0 };

                const counterTrigger = window.ScrollTrigger ? {
                    scrollTrigger: {
                        trigger: el,
                        start: 'top 90%',
                        once: true
                    }
                } : {};

                window.gsap.to(animObj, {
                    ...counterTrigger,
                    val: targetVal,
                    duration: 1.8,
                    ease: 'power2.out',
                    onUpdate: function () {
                        if (isFloat) {
                            el.textContent = animObj.val.toFixed(1);
                        } else if (hasComma) {
                            el.textContent = Math.round(animObj.val).toLocaleString('en-US');
                        } else {
                            el.textContent = Math.round(animObj.val);
                        }
                    }
                });
            });
        }

        // 7. SaaS Pricing Cards Scroll Reveal
        const pricingGrid = document.querySelector('#pricing .grid');
        const pricingCards = document.querySelectorAll('.pricing-card');
        if (pricingCards.length > 0 && window.ScrollTrigger) {
            window.gsap.from(pricingCards, {
                scrollTrigger: {
                    trigger: pricingGrid || '#pricing',
                    start: 'top 85%',
                    once: true
                },
                opacity: 0,
                y: 30,
                duration: 0.65,
                stagger: 0.12,
                ease: 'power2.out'
            });
        }

        // 8. FAQ Items Scroll Reveal
        const faqContainer = document.querySelector('#faq .space-y-3');
        const faqItems = document.querySelectorAll('.faq-item');
        if (faqItems.length > 0 && window.ScrollTrigger) {
            window.gsap.from(faqItems, {
                scrollTrigger: {
                    trigger: faqContainer || '#faq',
                    start: 'top 85%',
                    once: true
                },
                opacity: 0,
                y: 20,
                duration: 0.5,
                stagger: 0.08,
                ease: 'power2.out'
            });
        }

        // 9. Final Conversion Banner & Inner Texts Scroll Reveal
        const conversionBanner = document.querySelector('.conversion-banner');
        if (conversionBanner && window.ScrollTrigger) {
            window.gsap.from(conversionBanner, {
                scrollTrigger: {
                    trigger: conversionBanner,
                    start: 'top 85%',
                    once: true
                },
                opacity: 0,
                scale: 0.96,
                y: 25,
                duration: 0.7,
                ease: 'power2.out'
            });

            const bannerItems = conversionBanner.querySelectorAll('.banner-item');
            if (bannerItems.length > 0) {
                window.gsap.from(bannerItems, {
                    scrollTrigger: {
                        trigger: conversionBanner,
                        start: 'top 85%',
                        once: true
                    },
                    opacity: 0,
                    y: 18,
                    duration: 0.6,
                    stagger: 0.1,
                    delay: 0.1,
                    ease: 'power2.out'
                });
            }
        }

        // 10. Minimalist Footer Scroll Reveal
        const footerEl = document.querySelector('.footer-reveal');
        if (footerEl && window.ScrollTrigger) {
            window.gsap.from(footerEl, {
                scrollTrigger: {
                    trigger: footerEl,
                    start: 'top 95%',
                    once: true
                },
                opacity: 0,
                y: 20,
                duration: 0.6,
                ease: 'power2.out'
            });
        }
    }

    // Initialize after DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            initTypewriter();
            initGsapAnimations();
        });
    } else {
        initTypewriter();
        initGsapAnimations();
    }
})();
