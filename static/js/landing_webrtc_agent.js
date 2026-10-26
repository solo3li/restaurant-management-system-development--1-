/**
 * Motaem Cloud Restaurant OS
 * LiveKit WebRTC Direct Voice Agent & In-Page Stepper Auth Engine
 */

(function () {
    'use strict';

    // State Variables
    let currentRoom = null;
    let localAudioTrack = null;
    let remoteAudioElement = null;
    let audioContext = null;
    let localAnalyser = null;
    let remoteAnalyser = null;
    let animFrameId = null;
    let callTimerInterval = null;
    let callDurationSeconds = 0;
    let maxDurationSeconds = 300;
    let isMuted = false;

    // Helper: Get CSRF Token
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    // Helper: Format Time (seconds -> MM:SS)
    function formatTime(secs) {
        const m = Math.floor(secs / 60);
        const s = secs % 60;
        return `${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
    }

    // Dynamic LiveKit Script Loader
    function ensureLiveKitLoaded() {
        return new Promise((resolve, reject) => {
            if (window.LivekitClient || window.livekit) {
                resolve(window.LivekitClient || window.livekit);
                return;
            }
            const script = document.createElement('script');
            script.src = '/static/js/vendor/livekit-client.umd.min.js';
            script.onload = () => {
                resolve(window.LivekitClient || window.livekit);
            };
            script.onerror = () => {
                // Fallback to CDN if local fails
                const cdnScript = document.createElement('script');
                cdnScript.src = 'https://cdn.jsdelivr.net/npm/livekit-client/dist/livekit-client.umd.min.js';
                cdnScript.onload = () => resolve(window.LivekitClient || window.livekit);
                cdnScript.onerror = () => reject(new Error('تعذر تحميل مكتبة LiveKit للاتصال الصوتي.'));
                document.head.appendChild(cdnScript);
            };
            document.head.appendChild(script);
        });
    }

    // ========================================================
    // MODAL VISIBILITY MANAGERS
    // ========================================================

    window.openDemoVoiceFlow = function () {
        const isAuth = document.body.dataset.userAuthenticated === 'true';
        if (isAuth) {
            openVoiceCallModal();
            startWebRTCCall();
        } else {
            openAuthStepperModal();
        }
    };

    window.openAuthStepperModal = function () {
        const modal = document.getElementById('webrtc-auth-modal');
        if (modal) {
            modal.classList.remove('hidden');
            document.body.classList.add('overflow-hidden');
            switchAuthTab('register');
            setStepperStep(1);
        }
    };

    window.closeAuthStepperModal = function () {
        const modal = document.getElementById('webrtc-auth-modal');
        if (modal) {
            modal.classList.add('hidden');
            document.body.classList.remove('overflow-hidden');
        }
    };

    window.openVoiceCallModal = function () {
        const modal = document.getElementById('webrtc-call-modal');
        if (modal) {
            modal.classList.remove('hidden');
            document.body.classList.add('overflow-hidden');
            // Reset to active call view
            document.getElementById('call-active-state')?.classList.remove('hidden');
            document.getElementById('call-summary-state')?.classList.add('hidden');
            document.getElementById('call-error-state')?.classList.add('hidden');
            updateCallStatus('جاري تهيئة الاتصال بالذكاء الاصطناعي...', 'connecting');
        }
    };

    window.closeVoiceCallModal = function () {
        const modal = document.getElementById('webrtc-call-modal');
        if (modal) {
            modal.classList.add('hidden');
            document.body.classList.remove('overflow-hidden');
        }
        if (currentRoom) {
            hangupCall();
        }
    };

    // ========================================================
    // STEPPER FORM LOGIC (REGISTER & LOGIN)
    // ========================================================

    window.switchAuthTab = function (tab) {
        const regTabBtn = document.getElementById('tab-btn-register');
        const loginTabBtn = document.getElementById('tab-btn-login');
        const regPanel = document.getElementById('panel-register-stepper');
        const loginPanel = document.getElementById('panel-login');
        const authError = document.getElementById('auth-modal-error');
        if (authError) authError.classList.add('hidden');

        if (tab === 'register') {
            regTabBtn?.classList.add('bg-white', 'text-violet-700', 'shadow-xs');
            regTabBtn?.classList.remove('text-slate-600');
            loginTabBtn?.classList.remove('bg-white', 'text-violet-700', 'shadow-xs');
            loginTabBtn?.classList.add('text-slate-600');
            regPanel?.classList.remove('hidden');
            loginPanel?.classList.add('hidden');
        } else {
            loginTabBtn?.classList.add('bg-white', 'text-violet-700', 'shadow-xs');
            loginTabBtn?.classList.remove('text-slate-600');
            regTabBtn?.classList.remove('bg-white', 'text-violet-700', 'shadow-xs');
            regTabBtn?.classList.add('text-slate-600');
            loginPanel?.classList.remove('hidden');
            regPanel?.classList.add('hidden');
        }
    };

    window.setStepperStep = function (stepNumber) {
        const step1 = document.getElementById('stepper-step-1');
        const step2 = document.getElementById('stepper-step-2');
        const badge1 = document.getElementById('stepper-badge-1');
        const badge2 = document.getElementById('stepper-badge-2');
        const authError = document.getElementById('auth-modal-error');
        if (authError) authError.classList.add('hidden');

        if (stepNumber === 1) {
            step1?.classList.remove('hidden');
            step2?.classList.add('hidden');
            badge1?.classList.add('bg-violet-600', 'text-white');
            badge1?.classList.remove('bg-slate-100', 'text-slate-500');
            badge2?.classList.remove('bg-violet-600', 'text-white');
            badge2?.classList.add('bg-slate-100', 'text-slate-500');
        } else {
            // Validate step 1 fields before proceeding
            const restName = document.getElementById('reg-restaurant-name')?.value.trim();
            if (!restName) {
                showAuthError('يرجى إدخال اسم المطعم للمتابعة.');
                return;
            }
            step1?.classList.add('hidden');
            step2?.classList.remove('hidden');
            badge2?.classList.add('bg-violet-600', 'text-white');
            badge2?.classList.remove('bg-slate-100', 'text-slate-500');
        }
    };

    function showAuthError(msg) {
        const el = document.getElementById('auth-modal-error');
        if (el) {
            el.textContent = msg;
            el.classList.remove('hidden');
        }
    }

    window.handleStepperRegisterSubmit = async function (e) {
        if (e) e.preventDefault();
        const authError = document.getElementById('auth-modal-error');
        if (authError) authError.classList.add('hidden');

        const restName = document.getElementById('reg-restaurant-name')?.value.trim();
        const cuisine = document.getElementById('reg-cuisine-type')?.value.trim() || 'شعبي وتراثي';
        const ownerName = document.getElementById('reg-owner-name')?.value.trim();
        const phone = document.getElementById('reg-phone')?.value.trim();
        const username = document.getElementById('reg-username')?.value.trim();
        const password = document.getElementById('reg-password')?.value.trim();

        if (!restName || !username || !password) {
            showAuthError('يرجى ملء جميع الحقول المطلوبة: اسم المطعم، اسم المستخدم، وكلمة المرور.');
            return;
        }

        if (password.length < 6) {
            showAuthError('كلمة المرور يجب أن لا تقل عن 6 أحرف أو أرقام.');
            return;
        }

        const submitBtn = document.getElementById('btn-register-submit');
        const origText = submitBtn ? submitBtn.innerHTML : '';
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = `
                <svg class="animate-spin w-4 h-4 text-white inline-block mr-2" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
                </svg>
                <span>جاري إنشاء مطعمك وبدء الجلسة...</span>
            `;
        }

        try {
            const formData = new FormData();
            formData.append('restaurant_name', restName);
            formData.append('cuisine_type', cuisine);
            formData.append('owner_name', ownerName || restName);
            formData.append('phone', phone);
            formData.append('username', username);
            formData.append('password', password);
            formData.append('plan_code', 'trial');

            const resp = await fetch('/register/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCookie('csrftoken'),
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/json'
                },
                body: formData
            });

            const data = await resp.json();
            if (resp.ok && data.status === 'success') {
                // Successfully authenticated
                document.body.dataset.userAuthenticated = 'true';
                document.body.dataset.restaurantName = data.tenant_name || restName;
                closeAuthStepperModal();
                openVoiceCallModal();
                startWebRTCCall();
            } else {
                showAuthError(data.message || 'حدث خطأ أثناء إنشاء الحساب. يرجى مراجعة البيانات.');
            }
        } catch (err) {
            showAuthError('تعذر الاتصال بالخادم. يرجى المحاولة مرة أخرى.');
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = origText;
            }
        }
    };

    window.handleModalLoginSubmit = async function (e) {
        if (e) e.preventDefault();
        const authError = document.getElementById('auth-modal-error');
        if (authError) authError.classList.add('hidden');

        const username = document.getElementById('login-modal-username')?.value.trim();
        const password = document.getElementById('login-modal-password')?.value.trim();

        if (!username || !password) {
            showAuthError('يرجى إدخال اسم المستخدم وكلمة المرور.');
            return;
        }

        const submitBtn = document.getElementById('btn-login-submit');
        const origText = submitBtn ? submitBtn.innerHTML : '';
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = `
                <svg class="animate-spin w-4 h-4 text-white inline-block mr-2" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
                </svg>
                <span>جاري تسجيل الدخول...</span>
            `;
        }

        try {
            const formData = new FormData();
            formData.append('username', username);
            formData.append('password', password);

            const resp = await fetch('/login/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCookie('csrftoken'),
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/json'
                },
                body: formData
            });

            const data = await resp.json();
            if (resp.ok && data.status === 'success') {
                document.body.dataset.userAuthenticated = 'true';
                if (data.restaurant_name) {
                    document.body.dataset.restaurantName = data.restaurant_name;
                }
                closeAuthStepperModal();
                openVoiceCallModal();
                startWebRTCCall();
            } else {
                showAuthError(data.message || 'اسم المستخدم أو كلمة المرور غير صحيحة.');
            }
        } catch (err) {
            showAuthError('تعذر التحقق من الحساب، يرجى المحاولة لاحقاً.');
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = origText;
            }
        }
    };

    // ========================================================
    // WEBRTC LIVEKIT VOICE CALL ENGINE
    // ========================================================

    async function startWebRTCCall() {
        updateCallStatus('جاري طلب إذن الميكروفون...', 'connecting');
        const restNameEl = document.getElementById('call-restaurant-name');
        if (restNameEl && document.body.dataset.restaurantName) {
            restNameEl.textContent = document.body.dataset.restaurantName;
        }

        try {
            // 1. Request Browser Mic
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            
            updateCallStatus('جاري الاتصال بالسيرفر والذكاء الاصطناعي...', 'connecting');

            // 2. Fetch LiveKit Credentials from Backend Proxy
            const sessionResp = await fetch('/api/webrtc/session/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCookie('csrftoken'),
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/json',
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({})
            });

            if (!sessionResp.ok) {
                const errData = await sessionResp.json().catch(() => ({}));
                throw new Error(errData.message || 'تعذر بدء جلسة المكالمة الذكية من الخادم.');
            }

            const sessionData = await sessionResp.json();
            if (sessionData.status !== 'success' || !sessionData.livekit_url || !sessionData.livekit_token) {
                throw new Error(sessionData.message || 'بيانات اتصال السنترال غير مكتملة.');
            }

            if (sessionData.restaurant_name && restNameEl) {
                restNameEl.textContent = sessionData.restaurant_name;
            }
            if (sessionData.agent_profile && sessionData.agent_profile.name) {
                const agentEl = document.getElementById('call-agent-name');
                if (agentEl) agentEl.textContent = sessionData.agent_profile.name;
            }

            maxDurationSeconds = sessionData.max_duration_seconds || 300;

            // 3. Load LiveKit SDK
            const LK = await ensureLiveKitLoaded();
            const { Room, RoomEvent, createLocalAudioTrack } = LK;

            // 4. Create Room
            currentRoom = new Room({
                adaptiveStream: true,
                dynacast: true,
                audioCaptureDefaults: {
                    autoGainControl: true,
                    echoCancellation: true,
                    noiseSuppression: true,
                }
            });

            // 5. Setup Room Events
            currentRoom.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
                if (track.kind === 'audio') {
                    // Attach AI audio element
                    if (!remoteAudioElement) {
                        remoteAudioElement = document.createElement('audio');
                        remoteAudioElement.autoplay = true;
                        document.body.appendChild(remoteAudioElement);
                    }
                    track.attach(remoteAudioElement);

                    // Hook AI Audio Analyser
                    setupRemoteAudioAnalyser(remoteAudioElement);
                    updateCallStatus('المساعد الصوتي متصل — تحدث الآن', 'connected');
                }
            });

            currentRoom.on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
                const isAgentSpeaking = speakers.some(s => !s.isLocal);
                const isUserSpeaking = speakers.some(s => s.isLocal);
                const pulseRing = document.getElementById('agent-visual-pulse');
                
                if (isAgentSpeaking) {
                    updateCallStatus('المساعد الذكي يجيبك الآن...', 'agent_speaking');
                    pulseRing?.classList.add('scale-110', 'ring-emerald-400/80');
                    pulseRing?.classList.remove('ring-violet-500/50');
                } else if (isUserSpeaking) {
                    updateCallStatus('أنت تتحدث الآن — المساعد يستمع...', 'user_speaking');
                    pulseRing?.classList.remove('scale-110', 'ring-emerald-400/80');
                    pulseRing?.classList.add('ring-violet-500/50');
                } else {
                    updateCallStatus('المساعد جاهز ويستمع إليك... تحدث بحرية', 'connected');
                    pulseRing?.classList.remove('scale-110', 'ring-emerald-400/80');
                }
            });

            currentRoom.on(RoomEvent.Disconnected, () => {
                handleCallTermination('تم قطع الاتصال بالمكالمة.');
            });

            // 6. Connect to LiveKit Server
            await currentRoom.connect(sessionData.livekit_url, sessionData.livekit_token);

            // 7. Publish Local Mic
            localAudioTrack = await createLocalAudioTrack({
                echoCancellation: true,
                noiseSuppression: true,
            });
            await currentRoom.localParticipant.publishTrack(localAudioTrack);

            // 8. Setup Local Mic Analyser for Visualizer
            setupLocalAudioAnalyser(stream);

            // 9. Start Call Timer & Visualizer Loop
            startCallTimer();
            startVisualizerLoop();
            updateCallStatus('متصل بنجاح — تفضل بالتحدث مع المساعد', 'connected');

        } catch (err) {
            console.error('WebRTC Call Error:', err);
            showCallError(err.message || 'حدث خطأ أثناء بدء المكالمة الصوتية. يرجى التأكد من صلاحية الميكروفون.');
        }
    }

    // Audio Visualizer Analysers Setup
    function setupLocalAudioAnalyser(stream) {
        try {
            if (!audioContext) {
                audioContext = new (window.AudioContext || window.webkitAudioContext)();
            }
            if (audioContext.state === 'suspended') {
                audioContext.resume();
            }
            localAnalyser = audioContext.createAnalyser();
            localAnalyser.fftSize = 64;
            const source = audioContext.createMediaStreamSource(stream);
            source.connect(localAnalyser);
        } catch (e) {
            console.warn('Local Analyser setup skipped:', e);
        }
    }

    function setupRemoteAudioAnalyser(audioEl) {
        try {
            if (!audioContext) {
                audioContext = new (window.AudioContext || window.webkitAudioContext)();
            }
            // Optional: capture remote audio if CORS allows, otherwise fallback to local pulse
        } catch (e) {
            console.warn('Remote Analyser setup skipped:', e);
        }
    }

    // Visualizer Canvas / Bar Animation
    function startVisualizerLoop() {
        const bars = document.querySelectorAll('.sound-bar');
        if (!bars || bars.length === 0) return;

        const dataArray = new Uint8Array(32);

        function render() {
            if (localAnalyser) {
                localAnalyser.getByteFrequencyData(dataArray);
                let avg = 0;
                for (let i = 0; i < 16; i++) {
                    avg += dataArray[i];
                }
                avg = avg / 16;

                bars.forEach((bar, idx) => {
                    const val = dataArray[idx % 16] || 10;
                    const h = Math.max(8, Math.min(64, (val / 255) * 60 + 6));
                    bar.style.height = `${h}px`;
                    if (avg > 25) {
                        bar.classList.add('bg-violet-400');
                        bar.classList.remove('bg-slate-500');
                    } else {
                        bar.classList.remove('bg-violet-400');
                        bar.classList.add('bg-slate-500');
                    }
                });
            }
            animFrameId = requestAnimationFrame(render);
        }
        render();
    }

    function stopVisualizerLoop() {
        if (animFrameId) {
            cancelAnimationFrame(animFrameId);
            animFrameId = null;
        }
    }

    // Call Timer
    function startCallTimer() {
        callDurationSeconds = 0;
        const timerEl = document.getElementById('call-timer-display');
        const remainingEl = document.getElementById('call-countdown-display');

        if (callTimerInterval) clearInterval(callTimerInterval);

        callTimerInterval = setInterval(() => {
            callDurationSeconds++;
            const remaining = Math.max(0, maxDurationSeconds - callDurationSeconds);

            if (timerEl) timerEl.textContent = formatTime(callDurationSeconds);
            if (remainingEl) remainingEl.textContent = formatTime(remaining);

            if (remaining <= 0) {
                hangupCall();
            }
        }, 1000);
    }

    function stopCallTimer() {
        if (callTimerInterval) {
            clearInterval(callTimerInterval);
            callTimerInterval = null;
        }
    }

    // Mute / Unmute
    window.toggleMuteMic = function () {
        if (!localAudioTrack) return;
        isMuted = !isMuted;
        if (isMuted) {
            localAudioTrack.mute();
            document.getElementById('icon-mic-unmuted')?.classList.add('hidden');
            document.getElementById('icon-mic-muted')?.classList.remove('hidden');
            document.getElementById('btn-mute-toggle')?.classList.add('bg-amber-600', 'text-white');
            document.getElementById('btn-mute-toggle')?.classList.remove('bg-slate-800', 'text-slate-300');
            updateCallStatus('تم كتم الميكروفون', 'muted');
        } else {
            localAudioTrack.unmute();
            document.getElementById('icon-mic-muted')?.classList.add('hidden');
            document.getElementById('icon-mic-unmuted')?.classList.remove('hidden');
            document.getElementById('btn-mute-toggle')?.classList.remove('bg-amber-600', 'text-white');
            document.getElementById('btn-mute-toggle')?.classList.add('bg-slate-800', 'text-slate-300');
            updateCallStatus('الميكروفون مفعّل — تحدث الآن', 'connected');
        }
    };

    // Hangup
    window.hangupCall = function () {
        if (currentRoom) {
            try {
                currentRoom.disconnect();
            } catch (e) {
                console.warn('Disconnect error:', e);
            }
            currentRoom = null;
        }
        handleCallTermination('انتهت المكالمة بنجاح.');
    };

    function handleCallTermination(reason) {
        stopCallTimer();
        stopVisualizerLoop();

        if (localAudioTrack) {
            try {
                localAudioTrack.stop();
            } catch (e) {}
            localAudioTrack = null;
        }

        if (remoteAudioElement) {
            try {
                remoteAudioElement.pause();
                remoteAudioElement.srcObject = null;
            } catch (e) {}
        }

        // Switch to Summary View
        document.getElementById('call-active-state')?.classList.add('hidden');
        document.getElementById('call-error-state')?.classList.add('hidden');
        const summaryState = document.getElementById('call-summary-state');
        if (summaryState) {
            summaryState.classList.remove('hidden');
            const durEl = document.getElementById('summary-duration-display');
            if (durEl) durEl.textContent = formatTime(callDurationSeconds);
        }
    }

    function updateCallStatus(text, stateClass) {
        const statusEl = document.getElementById('call-status-badge');
        const statusText = document.getElementById('call-status-text');
        if (statusText) statusText.textContent = text;

        if (statusEl) {
            statusEl.className = 'inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold backdrop-blur-md transition-all ';
            if (stateClass === 'connecting') {
                statusEl.classList.add('bg-amber-500/20', 'text-amber-300', 'border', 'border-amber-500/30');
            } else if (stateClass === 'connected') {
                statusEl.classList.add('bg-emerald-500/20', 'text-emerald-300', 'border', 'border-emerald-500/30');
            } else if (stateClass === 'agent_speaking') {
                statusEl.classList.add('bg-violet-500/20', 'text-violet-300', 'border', 'border-violet-500/30', 'animate-pulse');
            } else if (stateClass === 'user_speaking') {
                statusEl.classList.add('bg-sky-500/20', 'text-sky-300', 'border', 'border-sky-500/30');
            } else {
                statusEl.classList.add('bg-slate-700/50', 'text-slate-300', 'border', 'border-slate-600/50');
            }
        }
    }

    function showCallError(msg) {
        stopCallTimer();
        stopVisualizerLoop();
        document.getElementById('call-active-state')?.classList.add('hidden');
        document.getElementById('call-summary-state')?.classList.add('hidden');
        const errorState = document.getElementById('call-error-state');
        if (errorState) {
            errorState.classList.remove('hidden');
            const errText = document.getElementById('call-error-text');
            if (errText) errText.textContent = msg;
        }
    }

    // Restart Call from Summary or Error
    window.restartDemoCall = function () {
        document.getElementById('call-summary-state')?.classList.add('hidden');
        document.getElementById('call-error-state')?.classList.add('hidden');
        document.getElementById('call-active-state')?.classList.remove('hidden');
        startWebRTCCall();
    };

})();
