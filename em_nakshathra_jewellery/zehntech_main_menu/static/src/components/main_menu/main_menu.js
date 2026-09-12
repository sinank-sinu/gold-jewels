/** @odoo-module **/

import { Component, onWillStart, onMounted, onWillUnmount, useState, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { WidgetHour } from "@zehntech_main_menu/components/widget_hour/widget_hour";
import { WidgetAnnouncement } from "@zehntech_main_menu/components/widget_announcement/widget_announcement";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

// ============================================================================
// THEME 1 ENGINE: MOLTEN LIQUID GOLD & 3D MAGNETIC ELASTIC APP SUSPENSION
// ============================================================================
class LiquidGoldEngine {
    constructor(canvas, appsContainerEl) {
        this.canvas = canvas;
        this.ctx = canvas.getContext("2d");
        this.container = appsContainerEl;
        this.audioCtx = null;
        this.animId = null;

        this.width = window.innerWidth;
        this.height = window.innerHeight;
        this.dpr = Math.min(window.devicePixelRatio || 1, 2);

        this.mouseX = -1000;
        this.mouseY = -1000;
        this.lastMouseX = -1000;
        this.lastMouseY = -1000;
        this.mouseSpeed = 0;

        this.trail = [];
        this.shockwaves = [];
        this.droplets = [];
        this.dust = [];
        this.cardMap = new Map();

        this.initDust();
        this.resize();

        this.onResize = () => this.resize();
        this.onPointerMove = (e) => this.handlePointerMove(e);
        this.onPointerDown = (e) => this.handlePointerDown(e);
        this.onDblClick = (e) => this.handleDblClick(e);

        window.addEventListener("resize", this.onResize);
        window.addEventListener("pointermove", this.onPointerMove);
        window.addEventListener("pointerdown", this.onPointerDown);
        window.addEventListener("dblclick", this.onDblClick);

        this.loop = this.loop.bind(this);
        this.animId = requestAnimationFrame(this.loop);
    }

    resize() {
        this.width = window.innerWidth;
        this.height = window.innerHeight;
        this.dpr = Math.min(window.devicePixelRatio || 1, 2);
        this.canvas.width = this.width * this.dpr;
        this.canvas.height = this.height * this.dpr;
    }

    initDust() {
        this.dust = [];
        for (let i = 0; i < 40; i++) {
            this.dust.push({
                x: Math.random() * window.innerWidth,
                y: Math.random() * window.innerHeight,
                radius: Math.random() * 2.2 + 0.8,
                vx: (Math.random() - 0.5) * 0.25,
                vy: -Math.random() * 0.35 - 0.1,
                alpha: Math.random() * 0.5 + 0.2,
                pulse: Math.random() * Math.PI * 2,
                pulseSpeed: Math.random() * 0.02 + 0.01,
            });
        }
    }

    handlePointerMove(e) {
        const x = e.clientX;
        const y = e.clientY;
        if (this.lastMouseX > 0) {
            const dx = x - this.lastMouseX;
            const dy = y - this.lastMouseY;
            this.mouseSpeed = Math.hypot(dx, dy);

            if (this.mouseSpeed > 2) {
                this.trail.push({
                    x,
                    y,
                    vx: dx * 0.2,
                    vy: dy * 0.2,
                    radius: Math.min(18, Math.max(4, this.mouseSpeed * 0.4)),
                    alpha: 0.85,
                    decay: 0.022,
                });

                if (Math.random() > 0.4) {
                    this.droplets.push({
                        x,
                        y,
                        vx: (Math.random() - 0.5) * 2 + dx * 0.1,
                        vy: (Math.random() - 0.5) * 2 + dy * 0.1 - 0.5,
                        radius: Math.random() * 2.5 + 1.2,
                        alpha: 1,
                        decay: 0.035,
                        color: Math.random() > 0.3 ? "#ffd700" : "#fff2b2",
                        gravity: 0.08,
                    });
                }
            }
        }
        this.mouseX = x;
        this.mouseY = y;
        this.lastMouseX = x;
        this.lastMouseY = y;
    }

    handlePointerDown(e) {
        const target = e.target;
        if (target && (
            target.tagName === "INPUT" ||
            target.tagName === "TEXTAREA" ||
            target.closest(".theme-drawer") ||
            target.closest(".theme-switcher-btn") ||
            target.closest(".launchpad-search-container") ||
            target.closest(".widgets")
        )) {
            return;
        }

        this.triggerShockwave(e.clientX, e.clientY, 1.0);
    }

    handleDblClick(e) {
        const target = e.target;
        if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.closest(".theme-drawer"))) return;
        this.onSpacePress();
    }

    onSpacePress() {
        this.shockwaves.push({
            x: this.width / 2,
            y: this.height / 2,
            radius: 10,
            maxRadius: Math.max(this.width, this.height),
            speed: 18,
            alpha: 1,
            color: "#ffd700",
            thickness: 6,
        });

        if (!this.container) return;
        const cards = this.container.querySelectorAll(".app-card");
        cards.forEach((el) => {
            let s = this.cardMap.get(el);
            if (!s) {
                s = this.initCardState(el);
            }
            const angle = Math.random() * Math.PI * 2;
            const force = 18 + Math.random() * 16;
            s.vx = Math.cos(angle) * force;
            s.vy = Math.sin(angle) * force - 6;
            s.vRotX = (Math.random() - 0.5) * 8;
            s.vRotY = (Math.random() - 0.5) * 8;
            s.zeroGravityUntil = performance.now() + 1800;
        });
        this.playWaterDropSound(1.3);
    }

    triggerShockwave(cx, cy, intensity = 1.0) {
        this.shockwaves.push({
            x: cx,
            y: cy,
            radius: 8,
            maxRadius: Math.max(this.width, this.height) * 0.85,
            speed: 14 * intensity,
            alpha: 1,
            color: "#ffd700",
            thickness: 4 * intensity,
        });

        this.shockwaves.push({
            x: cx,
            y: cy,
            radius: 4,
            maxRadius: Math.max(this.width, this.height) * 0.7,
            speed: 10 * intensity,
            alpha: 0.8,
            color: "#fff1a8",
            thickness: 2 * intensity,
        });

        for (let i = 0; i < 24; i++) {
            const angle = Math.random() * Math.PI * 2;
            const speed = (Math.random() * 5 + 2) * intensity;
            this.droplets.push({
                x: cx,
                y: cy,
                vx: Math.cos(angle) * speed,
                vy: Math.sin(angle) * speed - 1.5,
                radius: Math.random() * 3.5 + 1.5,
                alpha: 1,
                decay: 0.02 + Math.random() * 0.015,
                color: ["#ffe484", "#ffd700", "#ffaa00", "#ffffff"][Math.floor(Math.random() * 4)],
                gravity: 0.18,
            });
        }

        this.playWaterDropSound();
        this.applyShockwaveToCards(cx, cy, intensity);
    }

    applyShockwaveToCards(cx, cy, intensity) {
        if (!this.container) return;
        const cards = this.container.querySelectorAll(".app-card");
        const waveSpeed = 14 * intensity;

        cards.forEach((el) => {
            const rect = el.getBoundingClientRect();
            const cardCenterX = rect.left + rect.width / 2;
            const cardCenterY = rect.top + rect.height / 2;
            const dist = Math.hypot(cardCenterX - cx, cardCenterY - cy);
            const delayMs = (dist / waveSpeed) * 16;

            setTimeout(() => {
                let s = this.cardMap.get(el);
                if (!s) {
                    s = this.initCardState(el);
                }
                const angle = Math.atan2(cardCenterY - cy, cardCenterX - cx);
                const force = Math.min(24, Math.max(6, (700 - dist) / 700 * 22)) * intensity;
                s.vx += Math.cos(angle) * force;
                s.vy += Math.sin(angle) * force;
                s.rotX += -Math.sin(angle) * 16;
                s.rotY += Math.cos(angle) * 16;
            }, Math.max(0, delayMs));
        });
    }

    initCardState(el) {
        const state = {
            el,
            x: 0,
            y: 0,
            vx: 0,
            vy: 0,
            rotX: 0,
            rotY: 0,
            vRotX: 0,
            vRotY: 0,
            zeroGravityUntil: 0,
        };
        this.cardMap.set(el, state);
        return state;
    }

    playWaterDropSound(pitchMult = 1.0) {
        try {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            if (!AudioCtx) return;
            if (!this.audioCtx) {
                this.audioCtx = new AudioCtx();
            }
            if (this.audioCtx.state === "suspended") {
                this.audioCtx.resume();
            }
            const ctx = this.audioCtx;
            const now = ctx.currentTime;

            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            const startFreq = 420 * pitchMult;

            osc.type = "sine";
            osc.frequency.setValueAtTime(startFreq, now);
            osc.frequency.exponentialRampToValueAtTime(startFreq * 2.4, now + 0.12);

            gain.gain.setValueAtTime(0.08, now);
            gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.28);

            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start(now);
            osc.stop(now + 0.29);
        } catch (e) {}
    }

    updateCards(now) {
        if (!this.container) return;
        const cards = this.container.querySelectorAll(".app-card");
        const isMouseActive = this.mouseX > 0 && this.mouseY > 0;

        cards.forEach((el) => {
            let s = this.cardMap.get(el);
            if (!s) {
                s = this.initCardState(el);
            }

            const inZeroG = now < s.zeroGravityUntil;

            if (inZeroG) {
                s.x += s.vx;
                s.y += s.vy;
                s.vx *= 0.97;
                s.vy *= 0.97;
                s.rotX += s.vRotX;
                s.rotY += s.vRotY;
                s.vRotX *= 0.98;
                s.vRotY *= 0.98;
            } else {
                let targetX = 0;
                let targetY = 0;
                let targetRotX = 0;
                let targetRotY = 0;

                if (isMouseActive) {
                    const rect = el.getBoundingClientRect();
                    const cx = rect.left + rect.width / 2;
                    const cy = rect.top + rect.height / 2;
                    const dist = Math.hypot(cx - this.mouseX, cy - this.mouseY);

                    if (dist < 200 && dist > 1) {
                        const strength = Math.pow((200 - dist) / 200, 1.8);
                        const angle = Math.atan2(cy - this.mouseY, cx - this.mouseX);
                        targetX = Math.cos(angle) * (strength * 22);
                        targetY = Math.sin(angle) * (strength * 22);
                        targetRotX = -(cy - this.mouseY) * 0.08;
                        targetRotY = (cx - this.mouseX) * 0.08;
                    }
                }

                const springK = 0.14;
                const damping = 0.74;

                const ax = (targetX - s.x) * springK;
                const ay = (targetY - s.y) * springK;
                s.vx = (s.vx + ax) * damping;
                s.vy = (s.vy + ay) * damping;
                s.x += s.vx;
                s.y += s.vy;

                s.rotX = s.rotX * 0.85 + targetRotX * 0.15;
                s.rotY = s.rotY * 0.85 + targetRotY * 0.15;
            }

            if (Math.abs(s.x) > 0.05 || Math.abs(s.y) > 0.05 || Math.abs(s.rotX) > 0.05 || Math.abs(s.rotY) > 0.05) {
                el.style.transform = `translate3d(${s.x.toFixed(2)}px, ${s.y.toFixed(2)}px, 0) rotateX(${s.rotX.toFixed(2)}deg) rotateY(${s.rotY.toFixed(2)}deg)`;
            } else if (el.style.transform) {
                el.style.transform = "";
            }
        });
    }

    loop(time) {
        this.ctx.save();
        this.ctx.scale(this.dpr, this.dpr);
        this.ctx.clearRect(0, 0, this.width, this.height);

        // 1. Ambient Gold Dust
        for (let i = 0; i < this.dust.length; i++) {
            const d = this.dust[i];
            d.y += d.vy;
            d.x += d.vx;
            d.pulse += d.pulseSpeed;
            if (d.y < -10) d.y = this.height + 10;
            if (d.x < -10) d.x = this.width + 10;
            if (d.x > this.width + 10) d.x = -10;

            const alpha = d.alpha * (0.6 + 0.4 * Math.sin(d.pulse));
            this.ctx.fillStyle = `rgba(243, 207, 122, ${alpha})`;
            this.ctx.beginPath();
            this.ctx.arc(d.x, d.y, d.radius, 0, Math.PI * 2);
            this.ctx.fill();
        }

        // 2. Liquid Gold Ribbon Trail
        for (let i = this.trail.length - 1; i >= 0; i--) {
            const pt = this.trail[i];
            pt.alpha -= pt.decay;
            pt.radius *= 0.97;
            if (pt.alpha <= 0 || pt.radius < 0.5) {
                this.trail.splice(i, 1);
                continue;
            }

            this.ctx.save();
            const grad = this.ctx.createRadialGradient(pt.x, pt.y, 0, pt.x, pt.y, pt.radius * 2);
            grad.addColorStop(0, `rgba(255, 240, 160, ${pt.alpha})`);
            grad.addColorStop(0.4, `rgba(255, 215, 0, ${pt.alpha * 0.7})`);
            grad.addColorStop(1, `rgba(180, 120, 20, 0)`);
            this.ctx.fillStyle = grad;
            this.ctx.beginPath();
            this.ctx.arc(pt.x, pt.y, pt.radius * 2, 0, Math.PI * 2);
            this.ctx.fill();
            this.ctx.restore();
        }

        // 3. Shockwave Concentric Wave Fronts
        for (let i = this.shockwaves.length - 1; i >= 0; i--) {
            const sw = this.shockwaves[i];
            sw.radius += sw.speed;
            sw.alpha = Math.max(0, 1 - sw.radius / sw.maxRadius);

            if (sw.radius >= sw.maxRadius || sw.alpha <= 0) {
                this.shockwaves.splice(i, 1);
                continue;
            }

            this.ctx.save();
            this.ctx.strokeStyle = sw.color;
            this.ctx.globalAlpha = sw.alpha;
            this.ctx.lineWidth = sw.thickness * sw.alpha;
            this.ctx.shadowColor = "#ffd700";
            this.ctx.shadowBlur = 12 * sw.alpha;

            this.ctx.beginPath();
            this.ctx.arc(sw.x, sw.y, sw.radius, 0, Math.PI * 2);
            this.ctx.stroke();

            this.ctx.strokeStyle = "rgba(255, 255, 255, 0.6)";
            this.ctx.lineWidth = Math.max(1, sw.thickness * 0.4);
            this.ctx.beginPath();
            this.ctx.arc(sw.x, sw.y, Math.max(0, sw.radius - 3), 0, Math.PI * 2);
            this.ctx.stroke();
            this.ctx.restore();
        }

        // 4. Liquid Droplets
        for (let i = this.droplets.length - 1; i >= 0; i--) {
            const p = this.droplets[i];
            p.x += p.vx;
            p.y += p.vy;
            p.vy += p.gravity;
            p.vx *= 0.98;
            p.alpha -= p.decay;

            if (p.alpha <= 0) {
                this.droplets.splice(i, 1);
                continue;
            }

            this.ctx.save();
            this.ctx.globalAlpha = Math.max(0, p.alpha);
            this.ctx.fillStyle = p.color;
            this.ctx.shadowColor = p.color;
            this.ctx.shadowBlur = 6;
            this.ctx.beginPath();
            this.ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
            this.ctx.fill();
            this.ctx.restore();
        }

        this.ctx.restore();
        this.updateCards(time);
        this.animId = requestAnimationFrame(this.loop);
    }

    destroy() {
        if (this.animId) {
            cancelAnimationFrame(this.animId);
        }
        window.removeEventListener("resize", this.onResize);
        window.removeEventListener("pointermove", this.onPointerMove);
        window.removeEventListener("pointerdown", this.onPointerDown);
        window.removeEventListener("dblclick", this.onDblClick);
        if (this.audioCtx) {
            try {
                this.audioCtx.close();
            } catch (e) {}
        }
        if (this.container) {
            const cards = this.container.querySelectorAll(".app-card");
            cards.forEach((el) => {
                el.style.transform = "";
            });
        }
    }
}

// ============================================================================
// THEME 2 ENGINE: NAKSHATHRA CYBER STAR (CONSTELLATION MATRIX & SUPERNOVA)
// ============================================================================
class CyberConstellationEngine {
    constructor(canvas, appsContainerEl) {
        this.canvas = canvas;
        this.ctx = canvas.getContext("2d");
        this.container = appsContainerEl;
        this.animId = null;
        this.audioCtx = null;

        this.width = window.innerWidth;
        this.height = window.innerHeight;
        this.dpr = Math.min(window.devicePixelRatio || 1, 2);

        this.mouseX = -1000;
        this.mouseY = -1000;

        this.stars = [];
        this.pulses = [];
        this.sparks = [];

        this.initStars();
        this.resize();

        this.onResize = () => this.resize();
        this.onPointerMove = (e) => {
            this.mouseX = e.clientX;
            this.mouseY = e.clientY;
        };
        this.onPointerDown = (e) => this.handlePointerDown(e);

        window.addEventListener("resize", this.onResize);
        window.addEventListener("pointermove", this.onPointerMove);
        window.addEventListener("pointerdown", this.onPointerDown);

        this.loop = this.loop.bind(this);
        this.animId = requestAnimationFrame(this.loop);
    }

    resize() {
        this.width = window.innerWidth;
        this.height = window.innerHeight;
        this.dpr = Math.min(window.devicePixelRatio || 1, 2);
        this.canvas.width = this.width * this.dpr;
        this.canvas.height = this.height * this.dpr;
    }

    initStars() {
        this.stars = [];
        const count = 65;
        for (let i = 0; i < count; i++) {
            this.stars.push({
                x: Math.random() * window.innerWidth,
                y: Math.random() * window.innerHeight,
                vx: (Math.random() - 0.5) * 0.6,
                vy: (Math.random() - 0.5) * 0.6,
                radius: Math.random() * 2 + 1.2,
                color: Math.random() > 0.4 ? "#00f3ff" : "#ff007f",
                pulse: Math.random() * Math.PI * 2,
            });
        }
    }

    handlePointerDown(e) {
        const target = e.target;
        if (target && (
            target.tagName === "INPUT" ||
            target.tagName === "TEXTAREA" ||
            target.closest(".theme-drawer") ||
            target.closest(".theme-switcher-btn") ||
            target.closest(".launchpad-search-container") ||
            target.closest(".widgets")
        )) {
            return;
        }

        // Supernova Pulse at cursor
        this.triggerSupernova(e.clientX, e.clientY);
    }

    onSpacePress() {
        // Spacebar warp jump
        this.triggerSupernova(this.width / 2, this.height / 2, 1.8);
    }

    triggerSupernova(cx, cy, mult = 1.0) {
        this.pulses.push({
            x: cx,
            y: cy,
            radius: 5,
            maxRadius: 450 * mult,
            speed: 16 * mult,
            alpha: 1,
            color: "#00f3ff",
        });

        for (let i = 0; i < 28; i++) {
            const angle = Math.random() * Math.PI * 2;
            const speed = (Math.random() * 6 + 3) * mult;
            this.sparks.push({
                x: cx,
                y: cy,
                vx: Math.cos(angle) * speed,
                vy: Math.sin(angle) * speed,
                color: Math.random() > 0.5 ? "#00f3ff" : "#ff007f",
                radius: Math.random() * 2.8 + 1.2,
                alpha: 1,
                decay: 0.025,
            });
        }

        this.playCyberSynth();
    }

    playCyberSynth() {
        try {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            if (!AudioCtx) return;
            if (!this.audioCtx) {
                this.audioCtx = new AudioCtx();
            }
            if (this.audioCtx.state === "suspended") {
                this.audioCtx.resume();
            }
            const ctx = this.audioCtx;
            const now = ctx.currentTime;

            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = "sawtooth";
            osc.frequency.setValueAtTime(880, now);
            osc.frequency.exponentialRampToValueAtTime(220, now + 0.25);

            gain.gain.setValueAtTime(0.06, now);
            gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.26);

            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start(now);
            osc.stop(now + 0.27);
        } catch (e) {}
    }

    loop() {
        this.ctx.save();
        this.ctx.scale(this.dpr, this.dpr);
        this.ctx.clearRect(0, 0, this.width, this.height);

        // 1. Update & Draw Constellation Star Nodes
        for (let i = 0; i < this.stars.length; i++) {
            const s = this.stars[i];
            s.x += s.vx;
            s.y += s.vy;
            s.pulse += 0.03;

            if (s.x < 0) s.x = this.width;
            if (s.x > this.width) s.x = 0;
            if (s.y < 0) s.y = this.height;
            if (s.y > this.height) s.y = 0;

            this.ctx.save();
            this.ctx.fillStyle = s.color;
            this.ctx.shadowColor = s.color;
            this.ctx.shadowBlur = 8;
            this.ctx.beginPath();
            this.ctx.arc(s.x, s.y, s.radius * (0.8 + 0.3 * Math.sin(s.pulse)), 0, Math.PI * 2);
            this.ctx.fill();
            this.ctx.restore();

            // Connect lines between nearby stars
            for (let j = i + 1; j < this.stars.length; j++) {
                const s2 = this.stars[j];
                const d = Math.hypot(s.x - s2.x, s.y - s2.y);
                if (d < 85) {
                    const a = (1 - d / 85) * 0.28;
                    this.ctx.strokeStyle = `rgba(0, 243, 255, ${a})`;
                    this.ctx.lineWidth = 1;
                    this.ctx.beginPath();
                    this.ctx.moveTo(s.x, s.y);
                    this.ctx.lineTo(s2.x, s2.y);
                    this.ctx.stroke();
                }
            }

            // Connect laser constellation line to cursor!
            if (this.mouseX > 0 && this.mouseY > 0) {
                const distToMouse = Math.hypot(s.x - this.mouseX, s.y - this.mouseY);
                if (distToMouse < 170) {
                    const a = (1 - distToMouse / 170) * 0.7;
                    this.ctx.strokeStyle = `rgba(255, 0, 127, ${a})`;
                    this.ctx.lineWidth = 1.4;
                    this.ctx.shadowColor = "#ff007f";
                    this.ctx.shadowBlur = 6;
                    this.ctx.beginPath();
                    this.ctx.moveTo(s.x, s.y);
                    this.ctx.lineTo(this.mouseX, this.mouseY);
                    this.ctx.stroke();
                }
            }
        }

        // 2. Draw Supernova Pulses
        for (let i = this.pulses.length - 1; i >= 0; i--) {
            const p = this.pulses[i];
            p.radius += p.speed;
            p.alpha = Math.max(0, 1 - p.radius / p.maxRadius);

            if (p.radius >= p.maxRadius || p.alpha <= 0) {
                this.pulses.splice(i, 1);
                continue;
            }

            this.ctx.save();
            this.ctx.strokeStyle = p.color;
            this.ctx.globalAlpha = p.alpha;
            this.ctx.lineWidth = 3;
            this.ctx.shadowColor = "#00f3ff";
            this.ctx.shadowBlur = 14;
            this.ctx.beginPath();
            this.ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
            this.ctx.stroke();
            this.ctx.restore();
        }

        // 3. Draw Laser Sparks
        for (let i = this.sparks.length - 1; i >= 0; i--) {
            const sp = this.sparks[i];
            sp.x += sp.vx;
            sp.y += sp.vy;
            sp.vx *= 0.96;
            sp.vy *= 0.96;
            sp.alpha -= sp.decay;

            if (sp.alpha <= 0) {
                this.sparks.splice(i, 1);
                continue;
            }

            this.ctx.save();
            this.ctx.globalAlpha = Math.max(0, sp.alpha);
            this.ctx.fillStyle = sp.color;
            this.ctx.shadowColor = sp.color;
            this.ctx.shadowBlur = 6;
            this.ctx.beginPath();
            this.ctx.arc(sp.x, sp.y, sp.radius, 0, Math.PI * 2);
            this.ctx.fill();
            this.ctx.restore();
        }

        this.ctx.restore();
        this.animId = requestAnimationFrame(this.loop);
    }

    destroy() {
        if (this.animId) {
            cancelAnimationFrame(this.animId);
        }
        window.removeEventListener("resize", this.onResize);
        window.removeEventListener("pointermove", this.onPointerMove);
        window.removeEventListener("pointerdown", this.onPointerDown);
        if (this.audioCtx) {
            try {
                this.audioCtx.close();
            } catch (e) {}
        }
    }
}

// ============================================================================
// THEME 3 ENGINE: PEARL & DIAMOND STUDIO (HAUTE FLOATING GEM POPPING)
// ============================================================================
class GemStudioEngine {
    constructor(canvas, appsContainerEl) {
        this.canvas = canvas;
        this.ctx = canvas.getContext("2d");
        this.container = appsContainerEl;
        this.animId = null;
        this.audioCtx = null;

        this.width = window.innerWidth;
        this.height = window.innerHeight;
        this.dpr = Math.min(window.devicePixelRatio || 1, 2);

        this.gems = [];
        this.particles = [];
        this.dust = [];
        this.lastSpawn = performance.now();

        this.initDust();
        this.resize();

        // Pre-populate 5 floating jewels
        for (let i = 0; i < 5; i++) {
            this.spawnGem(Math.random() * this.height * 0.75 + this.height * 0.15);
        }

        this.onResize = () => this.resize();
        this.onPointerDown = (e) => this.handlePointerDown(e);

        window.addEventListener("resize", this.onResize);
        window.addEventListener("pointerdown", this.onPointerDown);

        this.loop = this.loop.bind(this);
        this.animId = requestAnimationFrame(this.loop);
    }

    resize() {
        this.width = window.innerWidth;
        this.height = window.innerHeight;
        this.dpr = Math.min(window.devicePixelRatio || 1, 2);
        this.canvas.width = this.width * this.dpr;
        this.canvas.height = this.height * this.dpr;
    }

    initDust() {
        this.dust = [];
        for (let i = 0; i < 30; i++) {
            this.dust.push({
                x: Math.random() * window.innerWidth,
                y: Math.random() * window.innerHeight,
                radius: Math.random() * 2 + 0.8,
                vx: (Math.random() - 0.5) * 0.3,
                vy: -Math.random() * 0.4 - 0.1,
                alpha: Math.random() * 0.5 + 0.2,
                pulse: Math.random() * Math.PI * 2,
            });
        }
    }

    spawnGem(customY = null) {
        const types = [
            { icon: "💎", color: "#4deeea", glow: "rgba(77, 238, 234, 0.7)" },
            { icon: "✨", color: "#ffd700", glow: "rgba(255, 215, 0, 0.7)" },
            { icon: "♦", color: "#ff2a6d", glow: "rgba(255, 42, 109, 0.7)" },
            { icon: "💚", color: "#05ffa1", glow: "rgba(5, 255, 161, 0.7)" },
            { icon: "🔮", color: "#b967ff", glow: "rgba(185, 103, 255, 0.7)" },
        ];
        const def = types[Math.floor(Math.random() * types.length)];
        const radius = 24 + Math.random() * 6;
        const padding = 70;
        const x = padding + Math.random() * Math.max(100, this.width - padding * 2);
        const y = customY !== null ? customY : this.height + radius + 10;
        this.gems.push({
            x,
            y,
            baseX: x,
            radius,
            def,
            vy: -(0.55 + Math.random() * 0.45),
            angle: Math.random() * Math.PI * 2,
            wobbleSpeed: 0.02 + Math.random() * 0.02,
            wobbleAmp: 16 + Math.random() * 14,
        });
    }

    handlePointerDown(e) {
        const target = e.target;
        if (target && (
            target.tagName === "INPUT" ||
            target.tagName === "TEXTAREA" ||
            target.closest(".theme-drawer") ||
            target.closest(".theme-switcher-btn") ||
            target.closest(".launchpad-search-container") ||
            target.closest(".widgets")
        )) {
            return;
        }

        const clickX = e.clientX;
        const clickY = e.clientY;

        let poppedIndex = -1;
        for (let i = this.gems.length - 1; i >= 0; i--) {
            const g = this.gems[i];
            if (Math.hypot(g.x - clickX, g.y - clickY) <= g.radius + 18) {
                poppedIndex = i;
                break;
            }
        }

        if (poppedIndex >= 0) {
            const gem = this.gems[poppedIndex];
            this.popGem(gem);
            this.gems.splice(poppedIndex, 1);
        } else {
            // Sparkle burst
            this.createBurst(clickX, clickY, "#ffd700", 12);
        }
    }

    onSpacePress() {
        // Pop all gems at once!
        this.gems.forEach(g => this.popGem(g));
        this.gems = [];
    }

    popGem(gem) {
        this.createBurst(gem.x, gem.y, gem.def.color, 24);
        this.playCrystalChime();
    }

    createBurst(x, y, baseColor, count) {
        for (let i = 0; i < count; i++) {
            const angle = Math.random() * Math.PI * 2;
            const speed = Math.random() * 4 + 1.5;
            const colors = [baseColor, "#ffd700", "#ffffff", "#ffe082"];
            this.particles.push({
                x,
                y,
                vx: Math.cos(angle) * speed,
                vy: Math.sin(angle) * speed - 0.8,
                color: colors[Math.floor(Math.random() * colors.length)],
                radius: Math.random() * 3 + 1.5,
                alpha: 1,
                decay: 0.02 + Math.random() * 0.02,
                isStar: Math.random() > 0.4,
            });
        }
    }

    playCrystalChime() {
        try {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            if (!AudioCtx) return;
            if (!this.audioCtx) {
                this.audioCtx = new AudioCtx();
            }
            if (this.audioCtx.state === "suspended") {
                this.audioCtx.resume();
            }
            const ctx = this.audioCtx;
            const now = ctx.currentTime;
            const notes = [587.33, 659.25, 783.99, 880, 1046.5, 1174.66, 1318.51];
            const freq = notes[Math.floor(Math.random() * notes.length)];

            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = "sine";
            osc.frequency.setValueAtTime(freq, now);
            osc.frequency.exponentialRampToValueAtTime(freq * 1.5, now + 0.14);

            gain.gain.setValueAtTime(0.08, now);
            gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.32);

            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start(now);
            osc.stop(now + 0.33);
        } catch (e) {}
    }

    loop(time) {
        this.ctx.save();
        this.ctx.scale(this.dpr, this.dpr);
        this.ctx.clearRect(0, 0, this.width, this.height);

        if (time - this.lastSpawn > 3200 && this.gems.length < 6) {
            this.lastSpawn = time;
            this.spawnGem();
        }

        // 1. Ambient Stardust
        for (let i = 0; i < this.dust.length; i++) {
            const d = this.dust[i];
            d.y += d.vy;
            d.x += d.vx;
            d.pulse += 0.02;
            if (d.y < -10) d.y = this.height + 10;
            if (d.x < -10) d.x = this.width + 10;
            if (d.x > this.width + 10) d.x = -10;

            const alpha = d.alpha * (0.6 + 0.4 * Math.sin(d.pulse));
            this.ctx.fillStyle = `rgba(243, 207, 122, ${alpha})`;
            this.ctx.beginPath();
            this.ctx.arc(d.x, d.y, d.radius, 0, Math.PI * 2);
            this.ctx.fill();
        }

        // 2. Floating Jewels
        for (let i = this.gems.length - 1; i >= 0; i--) {
            const g = this.gems[i];
            g.y += g.vy;
            g.angle += g.wobbleSpeed;
            g.x = g.baseX + Math.sin(g.angle) * g.wobbleAmp;

            if (g.y < -g.radius - 20) {
                this.gems.splice(i, 1);
                continue;
            }

            this.ctx.save();
            this.ctx.translate(g.x, g.y);

            this.ctx.shadowColor = g.def.glow;
            this.ctx.shadowBlur = 18;

            const grad = this.ctx.createRadialGradient(-g.radius * 0.3, -g.radius * 0.3, 2, 0, 0, g.radius);
            grad.addColorStop(0, "rgba(255, 255, 255, 0.45)");
            grad.addColorStop(0.5, "rgba(255, 255, 255, 0.12)");
            grad.addColorStop(1, "rgba(255, 255, 255, 0.05)");

            this.ctx.fillStyle = grad;
            this.ctx.beginPath();
            this.ctx.arc(0, 0, g.radius, 0, Math.PI * 2);
            this.ctx.fill();

            this.ctx.strokeStyle = g.def.glow;
            this.ctx.lineWidth = 1.4;
            this.ctx.stroke();

            this.ctx.shadowBlur = 8;
            this.ctx.font = `${Math.round(g.radius * 1.05)}px sans-serif`;
            this.ctx.textAlign = "center";
            this.ctx.textBaseline = "middle";
            this.ctx.fillText(g.def.icon, 0, 1);

            this.ctx.shadowBlur = 0;
            this.ctx.strokeStyle = "rgba(255, 255, 255, 0.65)";
            this.ctx.lineWidth = 1.6;
            this.ctx.beginPath();
            this.ctx.arc(0, 0, g.radius * 0.78, -Math.PI * 0.75, -Math.PI * 0.25);
            this.ctx.stroke();

            this.ctx.restore();
        }

        // 3. Stardust Burst Particles
        for (let i = this.particles.length - 1; i >= 0; i--) {
            const p = this.particles[i];
            p.x += p.vx;
            p.y += p.vy;
            p.vy += 0.05;
            p.vx *= 0.98;
            p.alpha -= p.decay;

            if (p.alpha <= 0) {
                this.particles.splice(i, 1);
                continue;
            }

            this.ctx.save();
            this.ctx.globalAlpha = Math.max(0, p.alpha);
            this.ctx.fillStyle = p.color;
            this.ctx.shadowColor = p.color;
            this.ctx.shadowBlur = 6;

            if (p.isStar) {
                const s = p.radius * 1.5;
                this.ctx.beginPath();
                this.ctx.moveTo(p.x, p.y - s);
                this.ctx.quadraticCurveTo(p.x, p.y, p.x + s, p.y);
                this.ctx.quadraticCurveTo(p.x + s, p.y, p.x, p.y + s);
                this.ctx.quadraticCurveTo(p.x, p.y + s, p.x - s, p.y);
                this.ctx.quadraticCurveTo(p.x - s, p.y, p.x, p.y - s);
                this.ctx.fill();
            } else {
                this.ctx.beginPath();
                this.ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
                this.ctx.fill();
            }
            this.ctx.restore();
        }

        this.ctx.restore();
        this.animId = requestAnimationFrame(this.loop);
    }

    destroy() {
        if (this.animId) {
            cancelAnimationFrame(this.animId);
        }
        window.removeEventListener("resize", this.onResize);
        window.removeEventListener("pointerdown", this.onPointerDown);
        if (this.audioCtx) {
            try {
                this.audioCtx.close();
            } catch (e) {}
        }
    }
}

// ============================================================================
// MAIN MENU ACTION COMPONENT WITH MULTI-THEME MANAGEMENT
// ============================================================================
class MenuAction extends Component {
    static components = { WidgetHour, WidgetAnnouncement };
    static props = {...standardActionServiceProps};
    static template = "zehntech_main_menu.MainMenu";

    setup() {
        this.orm = useService("orm");
        this.user = useService("user");
        this.menuService = useService("menu");
        const companyService = useService("company");
        this.currentCompanyId = companyService.currentCompany.id;

        const savedTheme = localStorage.getItem("nakshathra_menu_theme") || "liquid_gold";
        this.state = useState({
            search: "",
            currentTheme: savedTheme,
            isThemeDrawerOpen: false,
        });

        this.searchInputRef = useRef("searchInput");
        this.themeCanvasRef = useRef("themeCanvas");
        this.appsContainerRef = useRef("appsContainer");
        this.currentEngine = null;

        this.apps = this.menuService.getApps()
                        .filter(app => app.xmlid != "zehntech_main_menu.main_menu_root")
                        .sort((a, b) => a.name.localeCompare(b.name));
        this.deg = `${90 + 180 * Math.atan(window.innerHeight / window.innerWidth) / Math.PI}deg`;

        this.onKeyDown = (ev) => {
            const tag = ev.target ? ev.target.tagName : "";
            if (tag === "TEXTAREA" || (tag === "INPUT" && ev.target !== this.searchInputRef.el)) {
                return;
            }

            if (ev.key === "Escape") {
                if (this.state.isThemeDrawerOpen) {
                    this.state.isThemeDrawerOpen = false;
                    ev.preventDefault();
                    return;
                }
                if (this.state.search) {
                    this.state.search = "";
                    if (this.searchInputRef.el) {
                        this.searchInputRef.el.blur();
                    }
                    ev.preventDefault();
                }
                return;
            }

            if (ev.key === "Enter") {
                const apps = this.displayedApps;
                if (apps && apps.length > 0) {
                    this.onClickModule(apps[0]);
                    ev.preventDefault();
                }
                return;
            }

            // Spacebar trigger: Theme-specific action if search input is not active
            if (ev.code === "Space" && document.activeElement !== this.searchInputRef.el) {
                if (this.currentEngine && this.currentEngine.onSpacePress) {
                    this.currentEngine.onSpacePress();
                    ev.preventDefault();
                    return;
                }
            }

            if (ev.ctrlKey || ev.altKey || ev.metaKey) {
                return;
            }

            if (ev.key && ev.key.length === 1 && document.activeElement !== this.searchInputRef.el) {
                this.state.search += ev.key;
                if (this.searchInputRef.el) {
                    const el = this.searchInputRef.el;
                    el.focus();
                    Promise.resolve().then(() => {
                        if (el) {
                            const len = el.value ? el.value.length : 0;
                            el.setSelectionRange(len, len);
                        }
                    });
                }
                ev.preventDefault();
            }

            if (ev.key === "Backspace" && document.activeElement !== this.searchInputRef.el) {
                if (this.state.search.length > 0) {
                    this.state.search = this.state.search.slice(0, -1);
                    if (this.searchInputRef.el) {
                        this.searchInputRef.el.focus();
                    }
                    ev.preventDefault();
                }
            }
        };

        onMounted(() => {
            window.addEventListener("keydown", this.onKeyDown);
            this.initThemeEngine();
        });

        onWillUnmount(() => {
            window.removeEventListener("keydown", this.onKeyDown);
            if (this.currentEngine) {
                this.currentEngine.destroy();
                this.currentEngine = null;
            }
        });

        onWillStart(async () => {
            try {
                this.userIsAdmin = await this.user.hasGroup("base.group_system");
                const res = await this.orm.searchRead(
                    "res.company",
                    [["id", "=", this.currentCompanyId]],
                    ["announcement", "show_widgets"]
                );
                this.announcement = res[0].announcement;
                this.showWidgets = res[0].show_widgets;
            } catch (error) {
                console.error("Error loading data:", error);
            }
        });
    }

    initThemeEngine() {
        if (this.currentEngine) {
            this.currentEngine.destroy();
            this.currentEngine = null;
        }

        const canvas = this.themeCanvasRef.el;
        const container = this.appsContainerRef.el;

        // Reset any inline physics/transforms applied to app cards by previous interactive engines
        if (container) {
            const cards = container.querySelectorAll(".app-card, a");
            cards.forEach(card => {
                card.style.transform = "";
                card.style.transition = "";
            });
        }

        if (!canvas) return;

        // Clear canvas context
        const ctx = canvas.getContext("2d");
        if (ctx) {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
        }

        // Standard Theme: Completely silent, non-entertainment, zero CPU/GPU overhead
        if (this.state.currentTheme === "standard") {
            return;
        }

        switch (this.state.currentTheme) {
            case "cyber_star":
                this.currentEngine = new CyberConstellationEngine(canvas, container);
                break;
            case "pearl_studio":
                this.currentEngine = new GemStudioEngine(canvas, container);
                break;
            case "liquid_gold":
            default:
                this.currentEngine = new LiquidGoldEngine(canvas, container);
                break;
        }
    }

    toggleThemeDrawer() {
        this.state.isThemeDrawerOpen = !this.state.isThemeDrawerOpen;
    }

    closeThemeDrawer() {
        this.state.isThemeDrawerOpen = false;
    }

    selectTheme(themeKey) {
        if (this.state.currentTheme === themeKey) {
            this.state.isThemeDrawerOpen = false;
            return;
        }
        this.state.currentTheme = themeKey;
        localStorage.setItem("nakshathra_menu_theme", themeKey);
        this.initThemeEngine();
        this.state.isThemeDrawerOpen = false;
    }

    get displayedApps() {
        const query = (this.state.search || "").trim().toLowerCase();
        if (!query) {
            return this.apps;
        }
        return this.apps.filter(app => (app.name || "").toLowerCase().includes(query));
    }

    onClickModule(menu){
        menu && this.menuService.selectMenu(menu);
    }

    onChangeAnnouncement(value){
        this.announcement = value;
    }

    async onSaveAnnouncement(){
        try {
            await this.orm.write("res.company", [this.currentCompanyId], {
                "announcement": this.announcement
            });
        } catch (error) {
            console.error("Error saving data:", error);
        }
    }
}

registry
    .category("actions")
    .add("zehntech_main_menu.action_open_main_menu", MenuAction);

