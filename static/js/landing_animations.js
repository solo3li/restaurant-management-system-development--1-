/**
 * Motaem Cloud Restaurant OS - Interactive Landing Page Animations Engine
 * Integrates Typed.js (Dynamic Headline Typewriter) + GSAP & ScrollTrigger (Counters & Motion)
 */

(function () {
    'use strict';

    // Respect reduced motion preference
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        return;
    }

    function initTypewriter() {
        const typewriterEl = document.getElementById('hero-typewriter');
        if (!typewriterEl || typeof window.Typed === 'undefined') {
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

        new window.Typed('#hero-typewriter', {
            strings: typedStrings,
            typeSpeed: 55,
            backSpeed: 30,
            backDelay: 2200,
            startDelay: 400,
            loop: true,
            showCursor: true,
            cursorChar: '|',
            autoInsertCss: false
        });
    }

    function initGsapAnimations() {
        if (typeof window.gsap === 'undefined') {
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

        // 2. Hero Action Row & Badges Staggered Entrance
        const heroStaggerItems = document.querySelectorAll('.hero-anim-item');
        if (heroStaggerItems.length > 0) {
            window.gsap.from(heroStaggerItems, {
                opacity: 0,
                y: 20,
                duration: 0.75,
                stagger: 0.1,
                ease: 'power2.out',
                delay: 0.1
            });
        }

        // 3. Hero Metrics Strip (0ms, 24/7, 99.9%)
        const metricsStrip = document.querySelector('.hero-metrics-strip');
        if (metricsStrip) {
            const counterState = { latency: 120, hrs: 0, pct: 0 };
            const elLatency = document.getElementById('metric-latency');
            const elHrs = document.getElementById('metric-uptime-hrs');
            const elPct = document.getElementById('metric-uptime-pct');

            const triggerConfig = window.ScrollTrigger ? {
                scrollTrigger: {
                    trigger: metricsStrip,
                    start: 'top 95%',
                    once: true
                }
            } : {};

            window.gsap.to(counterState, {
                ...triggerConfig,
                latency: 0,
                hrs: 24,
                pct: 99.9,
                duration: 1.5,
                ease: 'power2.out',
                onUpdate: function () {
                    if (elLatency) elLatency.textContent = Math.round(counterState.latency);
                    if (elHrs) elHrs.textContent = Math.round(counterState.hrs);
                    if (elPct) elPct.textContent = counterState.pct.toFixed(1);
                }
            });
        }

        // 4. Live Stats Counter Strip (Dark Section)
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

        // 6. SaaS Pricing Cards Scroll Reveal
        const pricingCards = document.querySelectorAll('.pricing-card');
        if (pricingCards.length > 0 && window.ScrollTrigger) {
            window.gsap.from(pricingCards, {
                scrollTrigger: {
                    trigger: '#pricing',
                    start: 'top 85%',
                    once: true
                },
                opacity: 0,
                y: 30,
                duration: 0.6,
                stagger: 0.12,
                ease: 'power2.out'
            });
        }

        // 7. FAQ Items Scroll Reveal
        const faqItems = document.querySelectorAll('.faq-item');
        if (faqItems.length > 0 && window.ScrollTrigger) {
            window.gsap.from(faqItems, {
                scrollTrigger: {
                    trigger: '#faq',
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

        // 8. Final Conversion Banner
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
