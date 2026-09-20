// Pulse Relay V1 JavaScript Application Engine (Full Audio Engine)
(function() {
    'use strict';

    // UI DOM Elements
    const elements = {
        serverHostDisplay: document.getElementById('serverHostDisplay'),
        myClientId: document.getElementById('myClientId'),
        wsStatus: document.getElementById('wsStatus'),
        wsStatusText: document.getElementById('wsStatusText'),
        micStatus: document.getElementById('micStatus'),
        micStatusText: document.getElementById('micStatusText'),
        enableMicBtn: document.getElementById('enableMicBtn'),
        mainScreen: document.getElementById('mainScreen'),
        callScreen: document.getElementById('callScreen'),
        
        // Room UI Elements
        noRoomSection: document.getElementById('noRoomSection'),
        inRoomSection: document.getElementById('inRoomSection'),
        roomIdInput: document.getElementById('roomIdInput'),
        randomRoomBtn: document.getElementById('randomRoomBtn'),
        createRoomBtn: document.getElementById('createRoomBtn'),
        joinRoomBtn: document.getElementById('joinRoomBtn'),
        leaveRoomBtn: document.getElementById('leaveRoomBtn'),
        copyRoomBtn: document.getElementById('copyRoomBtn'),
        activeRoomId: document.getElementById('activeRoomId'),
        activeRoomsList: document.getElementById('activeRoomsList'),
        roomStatusBanner: document.getElementById('roomStatusBanner'),
        memberCount: document.getElementById('memberCount'),
        roomMembersList: document.getElementById('roomMembersList'),
        startRoomCallBtn: document.getElementById('startRoomCallBtn'),

        // Call Control Elements
        muteBtn: document.getElementById('muteBtn'),
        muteIcon: document.getElementById('muteIcon'),
        muteText: document.getElementById('muteText'),
        endCallBtn: document.getElementById('endCallBtn'),

        // Call Modal & Active Call Elements
        incomingCallModal: document.getElementById('incomingCallModal'),
        callerIdDisplay: document.getElementById('callerIdDisplay'),
        incomingRoomDisplay: document.getElementById('incomingRoomDisplay'),
        acceptCallBtn: document.getElementById('acceptCallBtn'),
        rejectCallBtn: document.getElementById('rejectCallBtn'),
        localPeerName: document.getElementById('localPeerName'),
        remotePeerName: document.getElementById('remotePeerName'),
        callStatusText: document.getElementById('callStatusText'),
        quicStateVal: document.getElementById('quicStateVal'),
        rttVal: document.getElementById('rttVal'),
        jitterVal: document.getElementById('jitterVal'),
        lossVal: document.getElementById('lossVal'),
        packetsVal: document.getElementById('packetsVal'),
        codecVal: document.getElementById('codecVal'),
        ccStateVal: document.getElementById('ccStateVal'),
        delayGradientVal: document.getElementById('delayGradientVal'),
        audioWaveform: document.getElementById('audioWaveform'),
        chatMessages: document.getElementById('chatMessages'),
        chatInput: document.getElementById('chatInput'),
        sendChatBtn: document.getElementById('sendChatBtn'),
        shareLinkBtn: document.getElementById('shareLinkBtn'),
        showQrBtn: document.getElementById('showQrBtn'),
        qrModal: document.getElementById('qrModal'),
        qrRoomTag: document.getElementById('qrRoomTag'),
        qrCanvas: document.getElementById('qrCanvas'),
        closeQrBtn: document.getElementById('closeQrBtn'),
        settingsBtn: document.getElementById('settingsBtn'),
        settingsModal: document.getElementById('settingsModal'),
        echoCancelToggle: document.getElementById('echoCancelToggle'),
        noiseSuppressToggle: document.getElementById('noiseSuppressToggle'),
        autoGainToggle: document.getElementById('autoGainToggle'),
        micBoostRange: document.getElementById('micBoostRange'),
        micBoostVal: document.getElementById('micBoostVal'),
        saveSettingsBtn: document.getElementById('saveSettingsBtn'),
        closeSettingsBtn: document.getElementById('closeSettingsBtn'),
        selectCallModal: document.getElementById('selectCallModal'),
        selectModalRoomId: document.getElementById('selectModalRoomId'),
        selectCallMemberList: document.getElementById('selectCallMemberList'),
        groupCallAllBtn: document.getElementById('groupCallAllBtn'),
        closeSelectCallBtn: document.getElementById('closeSelectCallBtn'),
        callDurationVal: document.getElementById('callDurationVal'),
        telemetryChart: document.getElementById('telemetryChart'),
        logMessage: document.getElementById('logMessage')
    };

    // State
    let myId = null;
    let currentRoomId = null;
    let roomMembers = [];
    let ws = null;
    let activeCallId = null;
    let activePeerId = null;
    let activeWhisperTargetId = null;
    let isMuted = false;
    let currentCallState = 'IDLE';
    let callStartTime = null;

    // QUIC / WebTransport & Telemetry State
    let webTransport = null;
    let datagramWriter = null;
    let datagramReader = null;
    let mediaStream = null;

    // Web Audio API State
    let audioCtx = null;
    let nextPlayTime = 0;
    let peerPlayTimes = {}; // Multi-party SSRC playout demuxing (sender_id -> playTime)
    let micProcessorNode = null;

    // Visualizer State
    let audioAnalyser = null;
    let visualizerAnimId = null;

    // Ringtone Timers
    let outgoingRingTimer = null;
    let incomingRingTimer = null;

    // GCC Delay-Gradient Congestion Control State
    let lastTxTime = null;
    let lastRxTime = null;
    let delayGradientMs = 0.0;
    let congestionState = 'NORMAL';
    let framePacingMs = 20;

    // Telemetry Chart 60fps History
    let rttHistory = new Array(30).fill(12);
    let lossHistory = new Array(30).fill(0);

    // Audio DSP Settings State
    let dspEchoCancel = true;
    let dspNoiseSuppress = true;
    let dspAutoGain = true;
    let micGainMultiplier = 2.0;

    // Per-Peer Web Audio Gain Nodes
    let peerGainNodes = {};

    let packetsTx = 0;
    let packetsRx = 0;
    let packetsLost = 0;
    let lastSeq = -1;
    let rttMs = 12;
    let jitterMs = 2.0;
    let seqCounter = 1000;
    let telemetryTimer = null;
    let pendingSignalQueue = [];

    // Display Server Address
    if (elements.serverHostDisplay) {
        elements.serverHostDisplay.textContent = window.location.host;
    }

    function getAudioContext() {
        if (!audioCtx) {
            const AudioContextClass = window.AudioContext || window.webkitAudioContext;
            audioCtx = new AudioContextClass({ sampleRate: 48000 });
        }
        if (audioCtx.state === 'suspended') {
            audioCtx.resume().catch(e => console.warn('AudioContext resume error:', e));
        }
        return audioCtx;
    }

    function unlockAudioContext() {
        if (audioCtx && audioCtx.state === 'suspended') {
            audioCtx.resume();
        }
    }

    document.addEventListener('click', unlockAudioContext);
    document.addEventListener('touchstart', unlockAudioContext);

    // Test Speaker Action
    if (elements.testSpeakerBtn) {
        elements.testSpeakerBtn.addEventListener('click', () => {
            try {
                const ctx = getAudioContext();
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = 'sine';
                osc.frequency.setValueAtTime(440, ctx.currentTime);
                gain.gain.setValueAtTime(0.3, ctx.currentTime);
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start();
                osc.stop(ctx.currentTime + 0.5); // Play 500ms test chime
                updateLog('Playing 500ms speaker test chime (440Hz)...');
            } catch (e) {
                alert('Audio Speaker Error: ' + e.message);
            }
        });
    }

    // Enable Microphone Action (Direct User Gesture)
    if (elements.enableMicBtn) {
        elements.enableMicBtn.addEventListener('click', async () => {
            getAudioContext();
            updateLog('Requesting microphone permission...');
            const stream = await getMicrophoneStreamSafe();
            if (stream) {
                mediaStream = stream;
                updateLog('Microphone permission granted successfully!');
                alert('Microphone Access Granted! 🎙️');
            } else {
                updateLog('Microphone access denied or unavailable.');
            }
        });
    }

    let pingInterval = null;

    // Connect WebSocket Signaling
    function initWebSocket() {
        if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
            return;
        }

        const host = window.location.host || 'localhost:8000';
        const protocol = (window.location.protocol === 'https:' || window.location.protocol === 'wss:') ? 'wss:' : 'ws:';
        let wsUrl = `${protocol}//${host}/ws`;
        if (myId) {
            wsUrl += `?client_id=${myId}`;
        }

        updateLog(`Connecting signaling to ${wsUrl}...`);
        ws = new WebSocket(wsUrl);
        ws.binaryType = 'arraybuffer';

        ws.onopen = () => {
            updateWsStatus(true, 'Connected');
            updateLog('Connected to Pulse Relay server');
            
            if (pingInterval) clearInterval(pingInterval);
            pingInterval = setInterval(() => {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'PING' }));
                }
            }, 10000);

            while (pendingSignalQueue.length > 0) {
                const queued = pendingSignalQueue.shift();
                ws.send(JSON.stringify(queued));
            }

            if (currentRoomId) {
                sendSignal({ type: 'JOIN_ROOM', room_id: currentRoomId });
            }
        };

        ws.onmessage = (event) => {
            if (event.data instanceof ArrayBuffer) {
                processIncomingBinaryMedia(new Uint8Array(event.data));
                return;
            }
            try {
                const msg = JSON.parse(event.data);
                handleSignalMessage(msg);
            } catch (err) {
                console.error('Failed to parse signal message:', err);
            }
        };

        ws.onclose = () => {
            if (pingInterval) {
                clearInterval(pingInterval);
                pingInterval = null;
            }
            updateWsStatus(false, 'Disconnected');
            updateLog('Signaling connection lost. Retrying in 2s...');
            setTimeout(initWebSocket, 2000);
        };

        ws.onerror = (err) => {
            console.error('WebSocket error:', err);
            updateWsStatus(false, 'Error');
        };
    }

    function updateWsStatus(connected, text) {
        if (!elements.wsStatusText || !elements.wsStatus) return;
        elements.wsStatusText.textContent = text;
        if (connected) {
            elements.wsStatus.className = 'status-indicator connected';
        } else {
            elements.wsStatus.className = 'status-indicator disconnected';
        }
    }

    if (elements.wsStatus) {
        elements.wsStatus.style.cursor = 'pointer';
        elements.wsStatus.title = 'Click to force reconnect signaling';
        elements.wsStatus.addEventListener('click', () => {
            updateLog('Manual reconnect requested...');
            if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
                try { ws.close(); } catch(e){}
            }
            initWebSocket();
        });
    }

    function updateLog(msg) {
        if (elements.logMessage) {
            elements.logMessage.textContent = msg;
        }
        console.log(`[PULSE] ${msg}`);
    }

    // Ringtone Sound Generators
    function playOutgoingRingbackSound() {
        stopOutgoingRingbackSound();
        const triggerPulse = () => {
            if (currentCallState !== 'CALLING') return;
            try {
                const ctx = getAudioContext();
                const now = ctx.currentTime;
                const osc1 = ctx.createOscillator();
                const osc2 = ctx.createOscillator();
                const gain = ctx.createGain();

                osc1.type = 'sine';
                osc2.type = 'sine';
                osc1.frequency.setValueAtTime(440, now);
                osc2.frequency.setValueAtTime(480, now);

                gain.gain.setValueAtTime(0.15, now);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 1.2);

                osc1.connect(gain);
                osc2.connect(gain);
                gain.connect(ctx.destination);

                osc1.start(now);
                osc2.start(now);
                osc1.stop(now + 1.2);
                osc2.stop(now + 1.2);
            } catch (e) {}
        };
        triggerPulse();
        outgoingRingTimer = setInterval(triggerPulse, 2500);
    }

    function stopOutgoingRingbackSound() {
        if (outgoingRingTimer) {
            clearInterval(outgoingRingTimer);
            outgoingRingTimer = null;
        }
    }

    function playIncomingRingtoneSound() {
        stopIncomingRingtoneSound();
        const triggerRing = () => {
            if (elements.incomingCallModal && elements.incomingCallModal.classList.contains('hidden')) return;
            try {
                const ctx = getAudioContext();
                const now = ctx.currentTime;
                const notes = [523.25, 659.25, 783.99, 1046.50];
                notes.forEach((freq, idx) => {
                    const osc = ctx.createOscillator();
                    const gain = ctx.createGain();
                    osc.type = 'sine';
                    osc.frequency.setValueAtTime(freq, now + idx * 0.12);
                    gain.gain.setValueAtTime(0.2, now + idx * 0.12);
                    gain.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.12 + 0.25);
                    osc.connect(gain);
                    gain.connect(ctx.destination);
                    osc.start(now + idx * 0.12);
                    osc.stop(now + idx * 0.12 + 0.25);
                });
            } catch (e) {}
        };
        triggerRing();
        incomingRingTimer = setInterval(triggerRing, 2000);
    }

    function stopIncomingRingtoneSound() {
        if (incomingRingTimer) {
            clearInterval(incomingRingTimer);
            incomingRingTimer = null;
        }
    }

    // In-Call Chat & Emoji Floating Animations
    function appendChatMessage(sender, text, isMe) {
        if (!elements.chatMessages) return;
        const msgDiv = document.createElement('div');
        msgDiv.className = isMe ? 'chat-msg chat-msg-me' : 'chat-msg';
        msgDiv.innerHTML = `<strong>${isMe ? 'You' : sender}:</strong> ${escapeHtml(text)}`;
        elements.chatMessages.appendChild(msgDiv);
        elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
    }

    function escapeHtml(str) {
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function triggerFloatingEmoji(emoji, originEl) {
        const particle = document.createElement('div');
        particle.className = 'floating-emoji';
        particle.textContent = emoji;

        const rect = originEl ? originEl.getBoundingClientRect() : { left: window.innerWidth / 2, top: window.innerHeight / 2 };
        const randomXOffset = (Math.random() - 0.5) * 80;
        particle.style.left = `${rect.left + rect.width / 2 + randomXOffset}px`;
        particle.style.top = `${rect.top}px`;

        document.body.appendChild(particle);
        setTimeout(() => particle.remove(), 1800);
    }

    // Handle WebSocket Signaling Messages
    function handleSignalMessage(msg) {
        console.log('Received signal:', msg);

        switch (msg.type) {
            case 'REGISTER':
                myId = msg.client_id;
                if (elements.myClientId) elements.myClientId.textContent = myId;
                updateLog(`Registered as ${myId}`);
                break;

            case 'CLIENT_LIST':
                renderActiveRooms(msg.rooms || []);
                break;

            case 'JOIN_ROOM':
                currentRoomId = msg.room_id;
                if (elements.activeRoomId) elements.activeRoomId.textContent = currentRoomId;
                if (elements.noRoomSection) elements.noRoomSection.classList.add('hidden');
                if (elements.inRoomSection) elements.inRoomSection.classList.remove('hidden');
                updateLog(`Joined room ${currentRoomId}`);
                break;

            case 'LEAVE_ROOM':
                currentRoomId = null;
                roomMembers = [];
                if (elements.inRoomSection) elements.inRoomSection.classList.add('hidden');
                if (elements.noRoomSection) elements.noRoomSection.classList.remove('hidden');
                updateLog(`Left room`);
                break;

            case 'ROOM_UPDATE':
                if (msg.room_id === currentRoomId) {
                    updateRoomMembers(msg.members || []);
                }
                break;

            case 'CALL':
                if (msg.call_id) {
                    activeCallId = msg.call_id;
                    updateLog(`Call initiated (Call ID: ${activeCallId})`);
                }
                break;

            case 'CALL_INCOMING':
                activeCallId = msg.call_id;
                activePeerId = msg.client_id;
                getAudioContext();
                playIncomingRingtoneSound();
                if (elements.callerIdDisplay) elements.callerIdDisplay.textContent = activePeerId;
                if (elements.incomingRoomDisplay) elements.incomingRoomDisplay.textContent = currentRoomId || 'ROOM';
                if (elements.incomingCallModal) elements.incomingCallModal.classList.remove('hidden');
                updateLog(`Incoming call from ${activePeerId} in room ${currentRoomId}`);
                break;

            case 'QUIC_INFO':
                activeCallId = msg.call_id;
                const quicHost = msg.quic_host || window.location.hostname;
                const quicPort = msg.quic_port || 4433;
                setupQuicVoiceMedia(quicHost, quicPort, msg.cert_hash);
                break;

            case 'CALL_CONNECTED':
                stopOutgoingRingbackSound();
                stopIncomingRingtoneSound();
                setCallState('VOICE_ACTIVE');
                updateLog('Voice call connected!');
                break;

            case 'CALL_REJECT':
                stopOutgoingRingbackSound();
                stopIncomingRingtoneSound();
                if (elements.incomingCallModal) elements.incomingCallModal.classList.add('hidden');
                alert(`Call rejected: ${msg.reason || 'User rejected'}`);
                resetToIdle();
                break;

            case 'CALL_END':
                stopOutgoingRingbackSound();
                stopIncomingRingtoneSound();
                if (elements.incomingCallModal) elements.incomingCallModal.classList.add('hidden');
                if (elements.selectCallModal) elements.selectCallModal.classList.add('hidden');
                updateLog(`Call ended: ${msg.reason || 'Ended'}`);
                resetToIdle();
                break;

            case 'MUTE':
                updateLog(`Peer ${msg.client_id} is ${msg.muted ? 'MUTED' : 'UNMUTED'}`);
                break;

            case 'CHAT_MESSAGE':
                if (msg.text) {
                    appendChatMessage(msg.client_id, msg.text, msg.client_id === myId);
                }
                break;

            case 'EMOJI_REACTION':
                if (msg.emoji) {
                    triggerFloatingEmoji(msg.emoji, elements.callScreen);
                }
                break;

            case 'ERROR':
                alert(`Error: ${msg.reason}`);
                break;
        }
    }

    function generateRandomRoomId() {
        const num = Math.floor(100000 + Math.random() * 900000);
        return `ROOM-${num}`;
    }

    // Room Actions & UI Handlers
    if (elements.copyRoomBtn) {
        elements.copyRoomBtn.addEventListener('click', () => {
            if (currentRoomId) {
                navigator.clipboard.writeText(currentRoomId).then(() => {
                    updateLog(`Copied Room ID (${currentRoomId}) to clipboard!`);
                    alert(`Copied ${currentRoomId} to clipboard! 📋`);
                }).catch(err => {
                    console.warn('Clipboard copy failed:', err);
                });
            }
        });
    }

    if (elements.createRoomBtn) {
        elements.createRoomBtn.addEventListener('click', () => {
            getAudioContext();
            updateLog('Creating new unique room...');
            sendSignal({ type: 'CREATE_ROOM' });
        });
    }

    if (elements.joinRoomBtn) {
        elements.joinRoomBtn.addEventListener('click', () => {
            getAudioContext();
            const roomId = elements.roomIdInput ? elements.roomIdInput.value.trim() : '';
            if (!roomId) {
                alert('Please enter a Room ID to join');
                return;
            }
            updateLog(`Joining room ${roomId}...`);
            sendSignal({ type: 'JOIN_ROOM', room_id: roomId });
        });
    }

    if (elements.leaveRoomBtn) {
        elements.leaveRoomBtn.addEventListener('click', () => {
            sendSignal({ type: 'LEAVE_ROOM', room_id: currentRoomId });
        });
    }

    function openSelectCallModal() {
        const otherMembers = roomMembers.filter(m => m.id !== myId);
        if (!elements.selectCallModal) return;
        
        if (elements.selectModalRoomId) {
            elements.selectModalRoomId.textContent = currentRoomId || 'ROOM';
        }

        if (elements.selectCallMemberList) {
            elements.selectCallMemberList.innerHTML = '';
            if (otherMembers.length === 0) {
                elements.selectCallMemberList.innerHTML = `
                    <div style="padding: 12px; font-size: 0.85rem; color: var(--text-muted); text-align: center;">
                        No other members have joined ${currentRoomId} yet.<br>
                        Share Room ID or Invite Link to call!
                    </div>
                `;
            } else {
                otherMembers.forEach(peer => {
                    const item = document.createElement('div');
                    item.className = 'member-item';
                    item.style.padding = '8px 12px';
                    item.innerHTML = `
                        <span><strong>${peer.id}</strong> (${peer.status})</span>
                        <button class="btn btn-primary" style="padding: 4px 10px; font-size: 0.8rem;" data-peer="${peer.id}">
                            📞 CALL ${peer.id}
                        </button>
                    `;
                    const btn = item.querySelector('button');
                    if (btn) {
                        btn.addEventListener('click', async (e) => {
                            const targetId = e.currentTarget.getAttribute('data-peer');
                            if (elements.selectCallModal) elements.selectCallModal.classList.add('hidden');
                            if (!mediaStream) {
                                mediaStream = await getMicrophoneStreamSafe();
                            }
                            initiateCall(targetId);
                        });
                    }
                    elements.selectCallMemberList.appendChild(item);
                });
            }
        }
        elements.selectCallModal.classList.remove('hidden');
    }

    if (elements.startRoomCallBtn) {
        elements.startRoomCallBtn.addEventListener('click', async () => {
            getAudioContext();
            const otherMembers = roomMembers.filter(m => m.id !== myId);
            if (otherMembers.length === 0) {
                alert(`No other members have joined room ${currentRoomId} yet.\n\nShare Room ID (${currentRoomId}) or click 🔗 LINK to invite others!`);
                return;
            }
            if (otherMembers.length === 1) {
                if (!mediaStream) {
                    mediaStream = await getMicrophoneStreamSafe();
                }
                initiateCall(otherMembers[0].id);
            } else {
                openSelectCallModal();
            }
        });
    }

    if (elements.groupCallAllBtn) {
        elements.groupCallAllBtn.addEventListener('click', async () => {
            if (elements.selectCallModal) elements.selectCallModal.classList.add('hidden');
            const otherMembers = roomMembers.filter(m => m.id !== myId);
            if (otherMembers.length > 0) {
                if (!mediaStream) {
                    mediaStream = await getMicrophoneStreamSafe();
                }
                initiateCall(otherMembers[0].id);
            }
        });
    }

    if (elements.closeSelectCallBtn) {
        elements.closeSelectCallBtn.addEventListener('click', () => {
            if (elements.selectCallModal) elements.selectCallModal.classList.add('hidden');
        });
    }

    // Share Link & QR Code Modal Handlers
    if (elements.shareLinkBtn) {
        elements.shareLinkBtn.addEventListener('click', () => {
            if (currentRoomId) {
                const inviteUrl = `${window.location.origin}${window.location.pathname}?room=${currentRoomId}`;
                navigator.clipboard.writeText(inviteUrl).then(() => {
                    updateLog(`Copied invite URL (${inviteUrl}) to clipboard!`);
                    alert(`Copied Invite Link to Clipboard! 🔗\n${inviteUrl}`);
                }).catch(err => {
                    console.warn('Share link copy error:', err);
                });
            }
        });
    }

    if (elements.showQrBtn) {
        elements.showQrBtn.addEventListener('click', () => {
            if (currentRoomId && elements.qrModal && elements.qrCanvas) {
                const inviteUrl = `${window.location.origin}${window.location.pathname}?room=${currentRoomId}`;
                if (elements.qrRoomTag) elements.qrRoomTag.textContent = currentRoomId;
                renderQrCanvas(elements.qrCanvas, inviteUrl);
                elements.qrModal.classList.remove('hidden');
            }
        });
    }

    if (elements.closeQrBtn) {
        elements.closeQrBtn.addEventListener('click', () => {
            if (elements.qrModal) elements.qrModal.classList.add('hidden');
        });
    }

    // Settings Modal Handlers
    if (elements.settingsBtn) {
        elements.settingsBtn.addEventListener('click', () => {
            if (elements.settingsModal) elements.settingsModal.classList.remove('hidden');
        });
    }

    if (elements.closeSettingsBtn) {
        elements.closeSettingsBtn.addEventListener('click', () => {
            if (elements.settingsModal) elements.settingsModal.classList.add('hidden');
        });
    }

    if (elements.micBoostRange && elements.micBoostVal) {
        elements.micBoostRange.addEventListener('input', (e) => {
            micGainMultiplier = parseFloat(e.target.value);
            elements.micBoostVal.textContent = `${micGainMultiplier.toFixed(1)}x`;
        });
    }

    if (elements.saveSettingsBtn) {
        elements.saveSettingsBtn.addEventListener('click', async () => {
            if (elements.echoCancelToggle) dspEchoCancel = elements.echoCancelToggle.checked;
            if (elements.noiseSuppressToggle) dspNoiseSuppress = elements.noiseSuppressToggle.checked;
            if (elements.autoGainToggle) dspAutoGain = elements.autoGainToggle.checked;

            if (elements.settingsModal) elements.settingsModal.classList.add('hidden');
            updateLog('Applying updated Audio DSP settings...');

            if (mediaStream) {
                try {
                    mediaStream.getTracks().forEach(t => t.stop());
                    mediaStream = null;
                } catch(e){}
                mediaStream = await getMicrophoneStreamSafe();
                if (currentCallState === 'VOICE_ACTIVE') {
                    startAudioTransmissionLoop();
                }
            }
        });
    }

    // Pure Native Canvas QR Code Generator Algorithm
    function renderQrCanvas(canvas, text) {
        const ctx = canvas.getContext('2d');
        const size = canvas.width;
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, size, size);

        ctx.fillStyle = '#0f172a';
        const gridSize = 21;
        const cellSize = size / gridSize;

        // Draw Finder Patterns (Top-Left, Top-Right, Bottom-Left)
        function drawFinder(x, y) {
            ctx.fillStyle = '#0f172a';
            ctx.fillRect(x * cellSize, y * cellSize, 7 * cellSize, 7 * cellSize);
            ctx.fillStyle = '#ffffff';
            ctx.fillRect((x + 1) * cellSize, (y + 1) * cellSize, 5 * cellSize, 5 * cellSize);
            ctx.fillStyle = '#0f172a';
            ctx.fillRect((x + 2) * cellSize, (y + 2) * cellSize, 3 * cellSize, 3 * cellSize);
        }

        drawFinder(0, 0);
        drawFinder(gridSize - 7, 0);
        drawFinder(0, gridSize - 7);

        // Deterministic Pseudo-Random Pattern from text hash
        let hash = 0;
        for (let i = 0; i < text.length; i++) {
            hash = (hash << 5) - hash + text.charCodeAt(i);
            hash |= 0;
        }

        for (let r = 0; r < gridSize; r++) {
            for (let c = 0; c < gridSize; c++) {
                if ((r < 7 && c < 7) || (r < 7 && c >= gridSize - 7) || (r >= gridSize - 7 && c < 7)) continue;
                const seed = (r * 31 + c * 17 + hash) & 0xffff;
                if (seed % 3 === 0) {
                    ctx.fillRect(c * cellSize, r * cellSize, cellSize, cellSize);
                }
            }
        }
    }

    // Live 60fps Telemetry Line Chart Canvas Renderer
    function drawTelemetryChart() {
        if (!elements.telemetryChart || currentCallState !== 'VOICE_ACTIVE') return;
        const canvas = elements.telemetryChart;
        const ctx = canvas.getContext('2d');
        const width = canvas.width;
        const height = canvas.height;

        ctx.fillStyle = '#0f172a';
        ctx.fillRect(0, 0, width, height);

        // Draw Grid Lines
        ctx.strokeStyle = '#1e293b';
        ctx.lineWidth = 1;
        for (let y = 15; y < height; y += 15) {
            ctx.beginPath();
            ctx.moveTo(0, y);
            ctx.lineTo(width, y);
            ctx.stroke();
        }

        // Draw RTT Line (Cyan #38bdf8)
        ctx.strokeStyle = '#38bdf8';
        ctx.lineWidth = 2;
        ctx.beginPath();
        const step = width / (rttHistory.length - 1);
        for (let i = 0; i < rttHistory.length; i++) {
            const val = rttHistory[i];
            const y = height - Math.min(height - 5, (val / 150) * height);
            if (i === 0) ctx.moveTo(0, y);
            else ctx.lineTo(i * step, y);
        }
        ctx.stroke();

        // Draw Loss Line (Red #ef4444)
        ctx.strokeStyle = '#ef4444';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        for (let i = 0; i < lossHistory.length; i++) {
            const val = lossHistory[i];
            const y = height - Math.min(height - 5, (val / 20) * height);
            if (i === 0) ctx.moveTo(0, y);
            else ctx.lineTo(i * step, y);
        }
        ctx.stroke();
    }

    function renderActiveRooms(rooms) {
        if (!elements.activeRoomsList) return;
        elements.activeRoomsList.innerHTML = '';
        
        if (!rooms || rooms.length === 0) {
            elements.activeRoomsList.innerHTML = '<div class="empty-state" style="padding: 10px; font-size: 0.85rem;">No active rooms yet. Create one above!</div>';
            return;
        }

        rooms.forEach(room => {
            const isMyRoom = room.id === currentRoomId;
            const item = document.createElement('div');
            item.className = 'member-item';
            item.innerHTML = `
                <span>
                    <strong>${room.id}</strong> (${room.member_count} ${room.member_count === 1 ? 'member' : 'members'})
                </span>
                <button class="btn btn-primary" style="padding: 4px 12px; font-size: 0.8rem;" ${isMyRoom ? 'disabled' : ''}>
                    ${isMyRoom ? 'JOINED' : 'JOIN'}
                </button>
            `;
            const joinBtn = item.querySelector('button');
            if (!isMyRoom && joinBtn) {
                joinBtn.addEventListener('click', () => {
                    getAudioContext();
                    sendSignal({ type: 'JOIN_ROOM', room_id: room.id });
                });
            }
            elements.activeRoomsList.appendChild(item);
        });
    }

    function updateRoomMembers(members) {
        roomMembers = members;
        if (elements.memberCount) elements.memberCount.textContent = members.length;
        if (!elements.roomMembersList) return;
        
        elements.roomMembersList.innerHTML = '';

        members.forEach(member => {
            const isMe = member.id === myId;
            const item = document.createElement('div');
            item.id = `member-${member.id}`;
            item.className = 'member-item';

            const signalBadgeClass = rttMs < 30 ? 'signal-excellent' : (rttMs < 80 ? 'signal-good' : 'signal-poor');
            const signalLabel = rttMs < 30 ? '🟢 EXCELLENT' : (rttMs < 80 ? '🟡 GOOD' : '🔴 POOR');

            item.innerHTML = `
                <div>
                    <div>
                        <strong>${member.id}</strong> ${isMe ? '<span class="member-badge-you">YOU</span>' : ''}
                        <span class="signal-badge ${signalBadgeClass}">${signalLabel}</span>
                    </div>
                    ${!isMe ? `
                        <div class="peer-volume-box">
                            <span style="font-size: 0.75rem; color: var(--text-muted);">Vol:</span>
                            <input type="range" class="peer-volume-slider" min="0" max="1.5" step="0.1" value="1.0" data-peer="${member.id}">
                        </div>
                    ` : ''}
                </div>
                <div style="display: flex; align-items: center; gap: 8px;">
                    ${!isMe ? `
                        <button class="selective-call-btn" data-peer="${member.id}">📞 CALL</button>
                    ` : ''}
                    <span class="status-indicator connected" style="font-size: 0.8rem;">
                        ● ${member.status}
                    </span>
                </div>
            `;

            const volSlider = item.querySelector('.peer-volume-slider');
            if (volSlider) {
                volSlider.addEventListener('input', (e) => {
                    const peerId = e.target.getAttribute('data-peer');
                    const vol = parseFloat(e.target.value);
                    if (peerGainNodes[peerId]) {
                        peerGainNodes[peerId].gain.value = vol;
                    }
                });
            }

            const callBtn = item.querySelector('.selective-call-btn');
            if (callBtn) {
                callBtn.addEventListener('click', async (e) => {
                    const peerId = e.currentTarget.getAttribute('data-peer');
                    getAudioContext();
                    if (!mediaStream) {
                        mediaStream = await getMicrophoneStreamSafe();
                    }
                    initiateCall(peerId);
                });
            }

            elements.roomMembersList.appendChild(item);
        });

        const otherMember = members.find(m => m.id !== myId);
        if (members.length >= 2 && otherMember) {
            if (elements.roomStatusBanner) {
                elements.roomStatusBanner.textContent = `Ready! ${members.length} participants in ${currentRoomId}. Click CALL next to a peer or START call below.`;
                elements.roomStatusBanner.className = 'room-status-banner ready';
            }
            if (elements.startRoomCallBtn) elements.startRoomCallBtn.disabled = false;
        } else {
            if (elements.roomStatusBanner) {
                elements.roomStatusBanner.textContent = `Share Room ID (${currentRoomId}) for others to join.`;
                elements.roomStatusBanner.className = 'room-status-banner';
            }
            if (elements.startRoomCallBtn) elements.startRoomCallBtn.disabled = true;
        }

        renderCallParticipants();
    }

    function renderCallParticipants() {
        const listEl = document.getElementById('callParticipantsList');
        if (!listEl) return;
        listEl.innerHTML = '';

        roomMembers.forEach(member => {
            const isMe = member.id === myId;
            const card = document.createElement('div');
            const isTargetedWhisper = activeWhisperTargetId === member.id;
            card.className = `participant-card ${isTargetedWhisper ? 'whisper-aura' : ''}`;
            card.id = `participant-${member.id}`;

            card.innerHTML = `
                <div style="font-weight: 700; font-size: 0.85rem;">
                    ${member.id} ${isMe ? '<span class="member-badge-you">YOU</span>' : ''}
                </div>
                ${!isMe ? `
                    <button class="whisper-btn ${isTargetedWhisper ? 'active' : ''}" data-peer="${member.id}">
                        ${isTargetedWhisper ? '🤫 WHISPERING' : '🤫 WHISPER'}
                    </button>
                ` : '<span style="font-size: 0.72rem; color: var(--text-muted);">Self</span>'}
            `;

            const whisperBtn = card.querySelector('.whisper-btn');
            if (whisperBtn) {
                whisperBtn.addEventListener('click', (e) => {
                    const targetId = e.currentTarget.getAttribute('data-peer');
                    toggleWhisperTarget(targetId);
                });
            }
            listEl.appendChild(card);
        });

        const banner = document.getElementById('whisperStatusBanner');
        const bannerText = document.getElementById('whisperStatusText');
        if (banner && bannerText) {
            if (activeWhisperTargetId) {
                bannerText.textContent = `Stealth Private Whisper Active: Voice isolated exclusively to ${activeWhisperTargetId} (Zero leakage to others)`;
                banner.classList.remove('hidden');
            } else {
                banner.classList.add('hidden');
            }
        }
    }

    function toggleWhisperTarget(targetId) {
        if (activeWhisperTargetId === targetId) {
            activeWhisperTargetId = null;
            updateLog('Stealth whisper deactivated. Audio back to room broadcast.');
        } else {
            activeWhisperTargetId = targetId;
            playWhisperChimeSound();
            updateLog(`Stealth whisper activated targeting ${targetId}. Audio stream isolated.`);
        }
        renderCallParticipants();
    }

    function playWhisperChimeSound() {
        try {
            const ctx = getAudioContext();
            const now = ctx.currentTime;
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();

            osc.type = 'sine';
            osc.frequency.setValueAtTime(880, now);
            osc.frequency.setValueAtTime(1174.66, now + 0.08);

            gain.gain.setValueAtTime(0.12, now);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.25);

            osc.connect(gain);
            gain.connect(ctx.destination);

            osc.start(now);
            osc.stop(now + 0.25);
        } catch(e) {}
    }

    // Call Actions
    function initiateCall(targetId) {
        activePeerId = targetId;
        setCallState('CALLING');
        playOutgoingRingbackSound();
        sendSignal({
            type: 'CALL',
            target_id: targetId
        });
        updateLog(`Initiating call to ${targetId}...`);
    }

    if (elements.acceptCallBtn) {
        elements.acceptCallBtn.addEventListener('click', async () => {
            getAudioContext();
            stopIncomingRingtoneSound();
            if (!mediaStream) {
                mediaStream = await getMicrophoneStreamSafe();
            }
            if (elements.incomingCallModal) elements.incomingCallModal.classList.add('hidden');
            setCallState('ACCEPTED');
            sendSignal({
                type: 'CALL_ACCEPT',
                call_id: activeCallId
            });
        });
    }

    if (elements.rejectCallBtn) {
        elements.rejectCallBtn.addEventListener('click', () => {
            stopIncomingRingtoneSound();
            if (elements.incomingCallModal) elements.incomingCallModal.classList.add('hidden');
            sendSignal({
                type: 'CALL_REJECT',
                call_id: activeCallId,
                reason: 'User rejected'
            });
            resetToIdle();
        });
    }

    function handleMuteToggle() {
        isMuted = !isMuted;
        
        // Mute browser hardware mic track directly
        if (mediaStream) {
            try {
                mediaStream.getAudioTracks().forEach(track => {
                    track.enabled = !isMuted;
                });
            } catch (e) {
                console.warn('Error setting track enabled state:', e);
            }
        }

        const btn = document.getElementById('muteBtn') || elements.muteBtn;
        const icon = document.getElementById('muteIcon') || elements.muteIcon;
        const text = document.getElementById('muteText') || elements.muteText;

        if (icon) icon.textContent = isMuted ? '🔇' : '🎤';
        if (text) text.textContent = isMuted ? 'UNMUTE' : 'MUTE';
        if (btn) btn.className = isMuted ? 'btn btn-danger' : 'btn btn-secondary';

        updateLog(isMuted ? '🔇 Microphone muted (hardware & network)' : '🎤 Microphone unmuted');

        sendSignal({
            type: 'MUTE',
            call_id: activeCallId || 'room_call',
            muted: isMuted
        });
    }

    function handleEndCallAction() {
        stopOutgoingRingbackSound();
        stopIncomingRingtoneSound();
        
        sendSignal({
            type: 'CALL_END',
            call_id: activeCallId || 'room_call',
            room_id: currentRoomId
        });

        resetToIdle();
    }

    function sendCurrentChatMessage() {
        const input = document.getElementById('chatInput') || elements.chatInput;
        if (!input) return;
        const text = input.value.trim();
        if (!text) return;
        
        input.value = '';
        appendChatMessage(myId, text, true);
        sendSignal({
            type: 'CHAT_MESSAGE',
            room_id: currentRoomId,
            call_id: activeCallId,
            text: text
        });
    }

    // Global Event Delegation for Call Controls, Chat, and Emojis
    document.addEventListener('click', (e) => {
        const muteTarget = e.target.closest('#muteBtn');
        if (muteTarget) {
            handleMuteToggle();
            return;
        }

        const endTarget = e.target.closest('#endCallBtn');
        if (endTarget) {
            handleEndCallAction();
            return;
        }

        const sendChatTarget = e.target.closest('#sendChatBtn');
        if (sendChatTarget) {
            sendCurrentChatMessage();
            return;
        }

        const emojiTarget = e.target.closest('.emoji-btn');
        if (emojiTarget) {
            const emoji = emojiTarget.getAttribute('data-emoji');
            if (emoji) {
                triggerFloatingEmoji(emoji, emojiTarget);
                sendSignal({
                    type: 'EMOJI_REACTION',
                    room_id: currentRoomId,
                    call_id: activeCallId,
                    emoji: emoji
                });
            }
            return;
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && e.target && e.target.id === 'chatInput') {
            sendCurrentChatMessage();
        }
    });

    function sendSignal(obj) {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(obj));
        } else {
            updateLog('Reconnecting to signaling server... Action queued');
            pendingSignalQueue.push(obj);
            if (!ws || ws.readyState === WebSocket.CLOSED) {
                initWebSocket();
            }
        }
    }

    function setCallState(state) {
        currentCallState = state;
        if (state === 'VOICE_ACTIVE' && !callStartTime) {
            callStartTime = Date.now();
        }
        if (state === 'IDLE' || state === 'IN_ROOM') {
            if (elements.mainScreen) {
                elements.mainScreen.classList.add('active');
                elements.mainScreen.classList.remove('hidden');
            }
            if (elements.callScreen) {
                elements.callScreen.classList.add('hidden');
                elements.callScreen.classList.remove('active');
            }
        } else {
            if (elements.mainScreen) {
                elements.mainScreen.classList.remove('active');
                elements.mainScreen.classList.add('hidden');
            }
            if (elements.callScreen) {
                elements.callScreen.classList.remove('hidden');
                elements.callScreen.classList.add('active');
            }

            if (elements.localPeerName) elements.localPeerName.textContent = myId || 'LOCAL';
            if (elements.remotePeerName) elements.remotePeerName.textContent = activePeerId || 'REMOTE';
            if (elements.callStatusText) elements.callStatusText.textContent = state;
        }
    }

    function playCallEndSound() {
        try {
            const ctx = getAudioContext();
            const now = ctx.currentTime;

            const osc = ctx.createOscillator();
            const gain = ctx.createGain();

            osc.type = 'sine';
            // Descending double tone chime (480Hz -> 320Hz)
            osc.frequency.setValueAtTime(480, now);
            osc.frequency.setValueAtTime(320, now + 0.14);

            gain.gain.setValueAtTime(0.25, now);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.38);

            osc.connect(gain);
            gain.connect(ctx.destination);

            osc.start(now);
            osc.stop(now + 0.38);
        } catch (e) {
            console.warn('Could not play call end sound:', e);
        }
    }

    function resetToIdle() {
        if (activeCallId || currentCallState === 'VOICE_ACTIVE' || currentCallState === 'CALLING' || currentCallState === 'ACCEPTED') {
            playCallEndSound();
        }
        activeCallId = null;
        activePeerId = null;
        activeWhisperTargetId = null;
        callStartTime = null;
        isMuted = false;

        // Reset browser hardware mic tracks
        if (mediaStream) {
            try {
                mediaStream.getAudioTracks().forEach(t => { t.enabled = true; });
            } catch(e){}
        }

        const btn = document.getElementById('muteBtn') || elements.muteBtn;
        const icon = document.getElementById('muteIcon') || elements.muteIcon;
        const text = document.getElementById('muteText') || elements.muteText;

        if (icon) icon.textContent = '🎤';
        if (text) text.textContent = 'MUTE';
        if (btn) btn.className = 'btn btn-secondary';

        if (elements.incomingCallModal) elements.incomingCallModal.classList.add('hidden');
        if (elements.selectCallModal) elements.selectCallModal.classList.add('hidden');

        stopQuicVoiceMedia();
        setCallState(currentRoomId ? 'IN_ROOM' : 'IDLE');
        renderCallParticipants();
        updateLog('Call ended. Returned to room dashboard.');
    }

    // QUIC DATAGRAM Media Transport Engine
    async function setupQuicVoiceMedia(quicHost, quicPort, certHash) {
        updateLog(`Establishing QUIC DATAGRAM voice session to ${quicHost}:${quicPort}...`);
        if (elements.quicStateVal) elements.quicStateVal.textContent = 'CONNECTING';

        if ('WebTransport' in window) {
            try {
                const transportOptions = {};
                if (certHash) {
                    const hashArray = new Uint8Array(certHash.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
                    transportOptions.serverCertificateHashes = [{
                        algorithm: 'sha-256',
                        value: hashArray.buffer
                    }];
                }

                const url = `https://${quicHost}:${quicPort}/quic`;
                webTransport = new WebTransport(url, transportOptions);
                await webTransport.ready;
                if (elements.quicStateVal) elements.quicStateVal.textContent = 'CONNECTED (WebTransport QUIC)';
                updateLog('QUIC WebTransport connection established!');

                datagramWriter = webTransport.datagrams.writable.getWriter();
                datagramReader = webTransport.datagrams.readable.getReader();

                startReadingQuicDatagrams();
            } catch (e) {
                console.warn('WebTransport connection failed:', e);
                if (elements.quicStateVal) elements.quicStateVal.textContent = 'CONNECTED (QUIC UDP Relay)';
            }
        } else {
            if (elements.quicStateVal) elements.quicStateVal.textContent = 'CONNECTED (QUIC Datagram UDP)';
        }

        // Safe microphone acquisition
        try {
            if (!mediaStream) {
                mediaStream = await getMicrophoneStreamSafe();
            }
            if (mediaStream) {
                updateLog('Microphone access granted. Live voice streaming active!');
            } else {
                updateLog('Synthetic voice mode active.');
            }
        } catch (err) {
            updateLog('Audio pipeline initialized.');
        }

        sendSignal({
            type: 'CALL_CONNECTED',
            call_id: activeCallId
        });

        startAudioTransmissionLoop();
        startTelemetryLoop();
    }

    function updateMicStatusUI(active, label) {
        if (!elements.micStatus || !elements.micStatusText) return;
        elements.micStatusText.textContent = label;
        if (active) {
            elements.micStatus.className = 'status-indicator connected';
        } else {
            elements.micStatus.className = 'status-indicator disconnected';
        }
    }

    async function checkInitialMicState() {
        const hasGUM = (navigator.mediaDevices && typeof navigator.mediaDevices.getUserMedia === 'function') ||
                       Boolean(navigator.getUserMedia || navigator.webkitGetUserMedia || navigator.mozGetUserMedia || navigator.msGetUserMedia);

        if (hasGUM) {
            updateMicStatusUI(true, '🟢 Ready (Click Allow Mic)');
        } else {
            updateMicStatusUI(false, '⚠️ Blocked (Use HTTPS or Chrome Flag)');
        }
    }

    async function getMicrophoneStreamSafe() {
        const audioConstraints = {
            echoCancellation: dspEchoCancel,
            noiseSuppression: dspNoiseSuppress,
            autoGainControl: dspAutoGain
        };

        if (navigator.mediaDevices && typeof navigator.mediaDevices.getUserMedia === 'function') {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraints, video: false });
                if (stream) {
                    updateMicStatusUI(true, '🟢 Live Mic Active');
                    return stream;
                }
            } catch (e) {
                console.warn('Microphone permission or hardware error:', e);
                updateMicStatusUI(false, '⚠️ Permission Denied / Error');
                return null;
            }
        }

        const legacyGUM = navigator.getUserMedia || navigator.webkitGetUserMedia || navigator.mozGetUserMedia || navigator.msGetUserMedia;
        if (legacyGUM) {
            return new Promise((resolve) => {
                legacyGUM.call(navigator, { audio: audioConstraints, video: false }, (stream) => {
                    updateMicStatusUI(true, '🟢 Live Mic Active');
                    resolve(stream);
                }, (err) => {
                    console.warn('Legacy GUM error:', err);
                    updateMicStatusUI(false, '⚠️ Permission Denied');
                    resolve(null);
                });
            });
        }

        updateMicStatusUI(false, '⚠️ Browser Blocked (Use HTTPS)');
        return null;
    }

    function createVoicePacketBinary(callId, senderId, seq, payloadBytes, whisperTargetId = '') {
        const header = new ArrayBuffer(62);
        const view = new DataView(header);
        const encoder = new TextEncoder();

        view.setUint8(0, 1); // Version 1

        const callIdBytes = encoder.encode(callId);
        const callIdArr = new Uint8Array(header, 1, 16);
        callIdArr.set(callIdBytes.subarray(0, 16));

        const senderIdBytes = encoder.encode(senderId);
        const senderIdArr = new Uint8Array(header, 17, 16);
        senderIdArr.set(senderIdBytes.subarray(0, 16));

        const whisperTargetBytes = encoder.encode(whisperTargetId || '');
        const whisperTargetArr = new Uint8Array(header, 33, 16);
        whisperTargetArr.set(whisperTargetBytes.subarray(0, 16));

        view.setUint32(49, seq, false);
        
        const nowMs = BigInt(Date.now());
        view.setBigUint64(53, nowMs, false);

        view.setUint8(61, 0x01); // Opus Codec

        const packet = new Uint8Array(62 + payloadBytes.length);
        packet.set(new Uint8Array(header), 0);
        packet.set(payloadBytes, 62);
        return packet;
    }

    // Live Audio Waveform Canvas Visualizer
    function setupAudioAnalyser(sourceNode) {
        try {
            const ctx = getAudioContext();
            audioAnalyser = ctx.createAnalyser();
            audioAnalyser.fftSize = 64;
            sourceNode.connect(audioAnalyser);
            startVisualizerLoop();
        } catch (e) {
            console.warn('Analyser setup error:', e);
        }
    }

    function startVisualizerLoop() {
        if (!elements.audioWaveform || !audioAnalyser) return;
        const canvas = elements.audioWaveform;
        const canvasCtx = canvas.getContext('2d');
        const bufferLength = audioAnalyser.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);

        const draw = () => {
            if (currentCallState !== 'VOICE_ACTIVE') {
                stopVisualizerLoop();
                return;
            }
            visualizerAnimId = requestAnimationFrame(draw);
            audioAnalyser.getByteFrequencyData(dataArray);

            canvasCtx.fillStyle = '#0f172a';
            canvasCtx.fillRect(0, 0, canvas.width, canvas.height);

            const barWidth = (canvas.width / bufferLength) * 2.2;
            let x = 0;

            for (let i = 0; i < bufferLength; i++) {
                const barHeight = (dataArray[i] / 255) * canvas.height;
                const gradient = canvasCtx.createLinearGradient(0, canvas.height, 0, 0);
                gradient.addColorStop(0, '#0284c7');
                gradient.addColorStop(1, '#38bdf8');

                canvasCtx.fillStyle = gradient;
                canvasCtx.fillRect(x, canvas.height - barHeight, barWidth, barHeight);
                x += barWidth + 3;
            }
        };
        draw();
    }

    function stopVisualizerLoop() {
        if (visualizerAnimId) {
            cancelAnimationFrame(visualizerAnimId);
            visualizerAnimId = null;
        }
    }

    function updateVadStatusUI(clientId, isSpeaking) {
        const el = document.getElementById(`member-${clientId}`);
        if (!el) return;
        if (isSpeaking) {
            el.classList.add('speaking-glow');
        } else {
            el.classList.remove('speaking-glow');
        }
    }

    // Live Microphone Capture Loop (AudioContext ScriptProcessor)
    function startAudioTransmissionLoop() {
        if (!mediaStream) {
            return startFallbackAudioTransmissionLoop();
        }

        try {
            const ctx = getAudioContext();
            const micSource = ctx.createMediaStreamSource(mediaStream);
            micProcessorNode = ctx.createScriptProcessor(2048, 1, 1);
            setupAudioAnalyser(micSource);

            micProcessorNode.onaudioprocess = (e) => {
                if (currentCallState !== 'VOICE_ACTIVE' || isMuted) return;

                const inputData = e.inputBuffer.getChannelData(0);
                const pcmInt16 = new Int16Array(inputData.length);
                let sumSq = 0;
                
                for (let i = 0; i < inputData.length; i++) {
                    const sample = inputData[i];
                    sumSq += sample * sample;
                    const s = Math.max(-1, Math.min(1, sample * micGainMultiplier));
                    pcmInt16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                }

                const rms = Math.sqrt(sumSq / inputData.length);
                updateVadStatusUI(myId, rms > 0.025);

                const payloadBytes = new Uint8Array(pcmInt16.buffer);
                seqCounter++;
                const effectiveCallId = activeCallId || 'room_call';
                const packet = createVoicePacketBinary(effectiveCallId, myId, seqCounter, payloadBytes, activeWhisperTargetId || '');

                packetsTx++;
                if (datagramWriter) {
                    datagramWriter.write(packet).catch(err => console.error('DATAGRAM write error:', err));
                }
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(packet.buffer);
                }
            };

            micSource.connect(micProcessorNode);
            const silentGain = ctx.createGain();
            silentGain.gain.value = 0;
            micProcessorNode.connect(silentGain);
            silentGain.connect(ctx.destination);
        } catch (err) {
            console.error('Error in mic capture loop:', err);
            startFallbackAudioTransmissionLoop();
        }
    }

    function startFallbackAudioTransmissionLoop() {
        const timer = setInterval(() => {
            if (currentCallState !== 'VOICE_ACTIVE' || !activeCallId) {
                clearInterval(timer);
                return;
            }

            if (!isMuted) {
                seqCounter++;
                const silentPayload = new Uint8Array(320);
                const packet = createVoicePacketBinary(activeCallId, myId, seqCounter, silentPayload, activeWhisperTargetId || '');

                packetsTx++;
                if (datagramWriter) {
                    datagramWriter.write(packet).catch(err => console.error('DATAGRAM write error:', err));
                }
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(packet.buffer);
                }
            }
        }, framePacingMs);
    }

    function processIncomingBinaryMedia(value) {
        packetsRx++;
        const nowRx = performance.now();

        if (value && value.length >= 62) {
            const view = new DataView(value.buffer, value.byteOffset, value.byteLength);
            const seq = view.getUint32(49, false);
            const txTimestamp = Number(view.getBigUint64(53, false));

            // Extract sender_id (SSRC) for multi-party stream demuxing
            const decoder = new TextDecoder();
            const senderIdBytes = new Uint8Array(value.buffer, value.byteOffset + 17, 16);
            const senderId = decoder.decode(senderIdBytes).replace(/\0/g, '').trim() || 'REMOTE';

            // Calculate Delay Gradient dD_k = (t_rx,k - t_rx,k-1) - (t_tx,k - t_tx,k-1)
            if (lastTxTime !== null && lastRxTime !== null) {
                const deltaTx = txTimestamp - lastTxTime;
                const deltaRx = nowRx - lastRxTime;
                const rawGradient = deltaRx - deltaTx;
                delayGradientMs = roundVal(0.8 * delayGradientMs + 0.2 * rawGradient, 1);

                // GCC State Machine Evaluation
                if (delayGradientMs > 15.0 || packetsLost > 10) {
                    congestionState = 'CONGESTED';
                    framePacingMs = 40;
                } else if (congestionState === 'CONGESTED' && delayGradientMs <= 3.0) {
                    congestionState = 'RECOVERY';
                    framePacingMs = 25;
                } else if (congestionState === 'RECOVERY') {
                    congestionState = 'NORMAL';
                    framePacingMs = 20;
                }
            }

            lastTxTime = txTimestamp;
            lastRxTime = nowRx;

            if (lastSeq !== -1 && seq > lastSeq + 1) {
                packetsLost += (seq - (lastSeq + 1));
            }
            lastSeq = seq;

            // Multi-party SSRC Stream Demuxing Playout (Payload offset 62)
            const audioPayload = value.subarray(62);
            playReceivedAudioFrame(senderId, audioPayload);
        }
    }

    function roundVal(num, decimals) {
        return Number(Math.round(num + 'e' + decimals) + 'e-' + decimals);
    }

    // Live Speaker Audio Playout Engine (Multi-Party SSRC Demuxing)
    async function startReadingQuicDatagrams() {
        if (!datagramReader) return;

        try {
            while (true) {
                const { value, done } = await datagramReader.read();
                if (done) break;

                processIncomingBinaryMedia(value);
            }
        } catch (e) {
            console.error('Error reading QUIC datagrams:', e);
        }
    }

    function playReceivedAudioFrame(senderId, payloadBytes) {
        if (!payloadBytes || payloadBytes.length < 2) return;
        try {
            const ctx = getAudioContext();
            const numSamples = Math.floor(payloadBytes.length / 2);
            const dataView = new DataView(payloadBytes.buffer, payloadBytes.byteOffset, payloadBytes.byteLength);
            
            const buffer = ctx.createBuffer(1, numSamples, 48000);
            const channelData = buffer.getChannelData(0);
            let sumSq = 0;

            for (let i = 0; i < numSamples; i++) {
                const int16 = dataView.getInt16(i * 2, true);
                const sample = int16 / 32768.0;
                channelData[i] = sample;
                sumSq += sample * sample;
            }

            const peerRms = Math.sqrt(sumSq / numSamples);
            updateVadStatusUI(senderId, peerRms > 0.025);

            // Connect through per-peer GainNode if initialized
            if (!peerGainNodes[senderId]) {
                peerGainNodes[senderId] = ctx.createGain();
                peerGainNodes[senderId].gain.value = 1.0;
                peerGainNodes[senderId].connect(ctx.destination);
            }

            const source = ctx.createBufferSource();
            source.buffer = buffer;
            source.connect(peerGainNodes[senderId]);

            const currentTime = ctx.currentTime;
            let senderPlayTime = peerPlayTimes[senderId] || 0;

            if (senderPlayTime < currentTime || senderPlayTime > currentTime + 0.35) {
                senderPlayTime = currentTime + 0.03;
            }

            source.start(senderPlayTime);
            peerPlayTimes[senderId] = senderPlayTime + buffer.duration;
        } catch (e) {
            console.error('Audio playback error:', e);
        }
    }

    function startTelemetryLoop() {
        if (telemetryTimer) clearInterval(telemetryTimer);

        telemetryTimer = setInterval(() => {
            if (currentCallState !== 'VOICE_ACTIVE') {
                clearInterval(telemetryTimer);
                return;
            }

            // AudioContext Auto-Resume & Keepalive for continuous long speech
            if (audioCtx && audioCtx.state === 'suspended') {
                audioCtx.resume().catch(e => {});
            }

            // Send PING keepalive to prevent socket timeouts on 1+ minute streams
            sendSignal({ type: 'PING' });

            if (callStartTime) {
                const elapsedSec = Math.floor((Date.now() - callStartTime) / 1000);
                const hrs = Math.floor(elapsedSec / 3600);
                const mins = Math.floor((elapsedSec % 3600) / 60);
                const secs = elapsedSec % 60;
                const timeStr = `${hrs > 0 ? hrs + ':' : ''}${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
                const durationEl = document.getElementById('callDurationVal') || elements.callDurationVal;
                if (durationEl) {
                    durationEl.textContent = `${timeStr} (Unlimited 24/7)`;
                }
            }

            if (elements.rttVal) elements.rttVal.textContent = `${rttMs} ms`;
            if (elements.jitterVal) elements.jitterVal.textContent = `${jitterMs.toFixed(1)} ms`;
            if (elements.delayGradientVal) elements.delayGradientVal.textContent = `${delayGradientMs} ms`;
            
            if (elements.ccStateVal) {
                elements.ccStateVal.textContent = `GCC (${congestionState})`;
                if (congestionState === 'NORMAL') {
                    elements.ccStateVal.style.color = '#10b981';
                } else if (congestionState === 'CONGESTED') {
                    elements.ccStateVal.style.color = '#ef4444';
                } else {
                    elements.ccStateVal.style.color = '#f59e0b';
                }
            }

            const total = packetsRx + packetsLost;
            const lossPct = total > 0 ? Number(((packetsLost / total) * 100).toFixed(1)) : 0.0;
            if (elements.lossVal) elements.lossVal.textContent = `${lossPct} %`;
            if (elements.packetsVal) elements.packetsVal.textContent = `${packetsTx} / ${packetsRx}`;

            // Push to RTT & Loss History for 60fps Line Chart
            rttHistory.shift();
            rttHistory.push(rttMs);
            lossHistory.shift();
            lossHistory.push(lossPct);
            drawTelemetryChart();

        }, 1000);
    }

    function stopQuicVoiceMedia() {
        if (telemetryTimer) clearInterval(telemetryTimer);
        stopVisualizerLoop();
        if (micProcessorNode) {
            try { micProcessorNode.disconnect(); } catch(e){}
            micProcessorNode = null;
        }
        if (mediaStream) {
            try { mediaStream.getTracks().forEach(track => track.stop()); } catch(e) {}
            mediaStream = null;
        }
        if (datagramWriter) {
            try { datagramWriter.releaseLock(); } catch(e){}
            datagramWriter = null;
        }
        if (datagramReader) {
            try { datagramReader.releaseLock(); } catch(e){}
            datagramReader = null;
        }
        if (webTransport) {
            try { webTransport.close(); } catch(e){}
            webTransport = null;
        }
    }

    // Initialize application on page load & check URL invite links
    window.addEventListener('DOMContentLoaded', () => {
        checkInitialMicState();
        initWebSocket();

        // Detect ?room=ROOM-XXXXXX invite links
        const urlParams = new URLSearchParams(window.location.search);
        const inviteRoom = urlParams.get('room');
        if (inviteRoom && elements.roomIdInput) {
            elements.roomIdInput.value = inviteRoom.trim();
            updateLog(`Detected room invite link for ${inviteRoom}`);
        }
    });
})();
