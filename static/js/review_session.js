/**
 * Nightly Vocab — SRS Review Session Controller (Step 6)
 * Handles Type 1, 2, 3 flashcards, masked letter boxes,
 * spelling check, meaning reveal, idempotency, "!" context modal,
 * and keyboard shortcuts (Space, Enter, 1, 2, I, Esc).
 */

(function () {
  "use strict";

  const config = window.LEXICONTEXT_REVIEW_CONFIG || {};
  const csrfToken = config.csrfToken;

  // DOM Elements
  const progressText = document.getElementById("progress-text");
  const progressBarFill = document.getElementById("progress-bar-fill");
  const cardStageBadge = document.getElementById("card-stage-badge");
  const cardContainer = document.getElementById("card-container");
  const cardFrontArea = document.getElementById("card-front-area");
  const cardInteractionArea = document.getElementById("card-interaction-area");
  const cardBackArea = document.getElementById("card-back-area");
  const btnContext = document.getElementById("btn-context");
  const recoveryBanner = document.getElementById("recovery-banner");
  const sessionEndScreen = document.getElementById("session-end-screen");
  const statTotalReviewed = document.getElementById("stat-total-reviewed");
  const statKnown = document.getElementById("stat-known");
  const statTomorrowDue = document.getElementById("stat-tomorrow-due");

  // Context Modal Elements
  const contextModal = document.getElementById("context-modal");
  const modalTextTitle = document.getElementById("modal-text-title");
  const modalTextBody = document.getElementById("modal-text-body");
  const btnCloseModal = document.getElementById("btn-close-modal");

  // State
  let cardsQueue = [];
  let currentCardIndex = 0;
  let currentCard = null;
  let isAnswerRevealed = false;
  let lastCheckedSpelling = null;
  let currentTypedInput = "";
  let progressState = { done: 0, total: 0 };
  let stats = { reviewed: 0, known: 0, missed: 0 };
  let tomorrowDueCount = 0;
  let isPracticeMode = false;

  function getCsrfToken() {
    if (config.csrfToken) return config.csrfToken;
    const cookie = document.cookie.split("; ").find((row) => row.startsWith("csrftoken="));
    return cookie ? decodeURIComponent(cookie.split("=")[1]) : "";
  }

  /**
   * Initializes the session by calling GET /api/review/session/
   */
  async function initSession() {
    try {
      const urlParams = new URLSearchParams(window.location.search);
      if (urlParams.get("practice") === "1") {
        isPracticeMode = true;
      }
      const fetchUrl = isPracticeMode ? "/api/review/session/?practice=1" : "/api/review/session/";
      const res = await fetch(fetchUrl, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      const data = await res.json();
      if (data.practice) {
        isPracticeMode = true;
      }

      if (data.recovery_banner && recoveryBanner) {
        recoveryBanner.style.display = "block";
      }

      progressState = data.progress || { done: 0, total: 0 };
      tomorrowDueCount = data.tomorrow_due || 0;

      if (data.done || !data.cards || data.cards.length === 0) {
        showEndScreen();
        return;
      }

      cardsQueue = data.cards;
      currentCardIndex = 0;
      stats.reviewed = progressState.done;
      renderCurrentCard();
    } catch (err) {
      console.error("Failed to load review session:", err);
      cardFrontArea.innerHTML = `
        <div class="alert alert-error" style="text-align: center;">
          خطا در برقراری ارتباط با سرور. لطفاً صفحه را تازه‌سازی کنید.
        </div>
      `;
    }
  }

  /**
   * Updates progress bar and badge
   */
  function updateProgress() {
    const done = progressState.done;
    const total = progressState.total;
    if (progressText) progressText.textContent = `${done} / ${total}`;
    if (progressBarFill) {
      const pct = total > 0 ? Math.min(100, (done / total) * 100) : 100;
      progressBarFill.style.width = `${pct}%`;
    }
    if (cardStageBadge && currentCard) {
      cardStageBadge.textContent = `مرحله ${currentCard.stage}`;
    }
  }

  /**
   * Renders the current card in the queue
   */
  function renderCurrentCard() {
    if (currentCardIndex >= cardsQueue.length) {
      showEndScreen();
      return;
    }

    currentCard = cardsQueue[currentCardIndex];
    if (!currentCard.word && currentCard.audio_text) {
      currentCard.word = currentCard.audio_text;
    }
    isAnswerRevealed = false;
    lastCheckedSpelling = null;
    currentTypedInput = "";

    updateProgress();

    // Reset "!" button
    btnContext.disabled = true;
    if (currentCard.has_source_text) {
      btnContext.style.display = "inline-flex";
      // Type 1 reveals immediately; Types 2 & 3 unlock after answer check
      if (currentCard.display_type === 1) {
        btnContext.disabled = false;
      }
    } else {
      btnContext.style.display = "none";
    }

    // Clear areas
    cardFrontArea.innerHTML = "";
    cardInteractionArea.innerHTML = "";
    cardBackArea.innerHTML = "";

    // Preload next card audio
    if (window.LexiAudio && currentCardIndex + 1 < cardsQueue.length) {
      window.LexiAudio.preloadNext(cardsQueue[currentCardIndex + 1]);
    }

    // Dispatch render based on display_type
    if (currentCard.display_type === 1) {
      renderType1();
    } else if (currentCard.display_type === 2) {
      renderType2();
    } else if (currentCard.display_type === 3) {
      renderType3();
    }
  }

  // -------------------------------------------------------------
  // Card Type 1: Recognition (Word + Sentence shown)
  // -------------------------------------------------------------
  function renderType1() {
    const wordHtml = `
      <div style="display: flex; align-items: center; justify-content: center; gap: 12px; margin-bottom: 8px; direction: ltr;">
        <h2 class="target-word-display" dir="ltr" lang="en" style="margin-bottom: 0;">${escapeHtml(currentCard.word)}</h2>
        <button type="button" class="btn-audio-replay" id="btn-audio-front" title="پخش تلفظ (P)" aria-label="پخش تلفظ">🔊</button>
      </div>
    `;

    let sentenceHtml = "";
    if (currentCard.context_sentence) {
      const s = currentCard.context_sentence;
      const start = currentCard.ctx_start;
      const end = currentCard.ctx_end;
      const before = escapeHtml(s.slice(0, start));
      const target = escapeHtml(s.slice(start, end));
      const after = escapeHtml(s.slice(end));
      sentenceHtml = `<div class="context-sentence-box" dir="ltr" lang="en">${before}<mark>${target}</mark>${after}</div>`;
    }

    cardFrontArea.innerHTML = wordHtml + sentenceHtml;

    // Attach front audio button
    const btnAudioFront = document.getElementById("btn-audio-front");
    if (btnAudioFront) {
      btnAudioFront.addEventListener("click", () => {
        if (window.LexiAudio) window.LexiAudio.playCard(currentCard);
      });
    }

    // Automatically trigger audio playback for Type 1
    if (window.LexiAudio) {
      window.LexiAudio.playCard(currentCard, true);
    }

    // "Show Answer" button
    const btnShow = document.createElement("button");
    btnShow.id = "btn-primary-action";
    btnShow.type = "button";
    btnShow.className = "btn btn-primary";
    btnShow.style.width = "100%";
    btnShow.style.padding = "12px";
    btnShow.textContent = "نمایش پاسخ (Space / Enter)";
    btnShow.addEventListener("click", revealType1Answer);
    cardBackArea.appendChild(btnShow);
  }

  function revealType1Answer() {
    if (isAnswerRevealed) return;
    isAnswerRevealed = true;

    cardBackArea.innerHTML = `
      <div style="border-top: 1px solid var(--border); padding-top: 20px; text-align: center;">
        <div style="margin-bottom: 12px; display: flex; align-items: center; justify-content: center; gap: 10px;">
          <span class="brand-badge" style="font-size: 13px;">${escapeHtml(currentCard.pos || "واژه")}</span>
          <span style="font-size: 22px; font-weight: 700; color: var(--text);">${escapeHtml(currentCard.meaning || "—")}</span>
        </div>
        ${
          currentCard.ai_example
            ? `<div class="text-muted" style="font-size: 13px; direction: ltr; margin-bottom: 16px;">💡 ${escapeHtml(currentCard.ai_example)}</div>`
            : ""
        }
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 20px;">
          <button id="btn-grade-wrong" type="button" class="btn" style="padding: 12px; font-weight: 700;">
            بلد نبودم
          </button>
          <button id="btn-grade-right" type="button" class="btn btn-primary" style="padding: 12px; font-weight: 700;">
            بلد بودم
          </button>
        </div>
      </div>
    `;

    document.getElementById("btn-grade-wrong").addEventListener("click", () => submitAnswer(false));
    document.getElementById("btn-grade-right").addEventListener("click", () => submitAnswer(true));
  }

  // -------------------------------------------------------------
  // Card Type 2: Guided Spelling (Masked Letter Boxes)
  // -------------------------------------------------------------
  function renderType2() {
    const sentenceHtml = `<div class="context-sentence-box" dir="ltr" lang="en">${escapeHtml(currentCard.blanked_sentence || "")}</div>`;
    cardFrontArea.innerHTML = sentenceHtml;

    // Masked input boxes (strictly horizontal row)
    const boxesContainer = document.createElement("div");
    boxesContainer.className = "masked-boxes-container";
    boxesContainer.style.display = "flex";
    boxesContainer.style.flexDirection = "row";
    boxesContainer.style.justifyContent = "center";
    boxesContainer.style.alignItems = "center";
    boxesContainer.style.gap = "8px";
    boxesContainer.style.flexWrap = "nowrap";
    boxesContainer.style.margin = "24px 0";
    boxesContainer.style.direction = "ltr";
    boxesContainer.style.overflowX = "auto";
    boxesContainer.style.padding = "8px 0";

    const boxes = currentCard.masked_boxes || [];
    const inputElements = [];

    boxes.forEach((b, idx) => {
      if (b.is_space) {
        const sp = document.createElement("div");
        sp.className = "letter-box space";
        sp.style.width = "14px";
        sp.style.minWidth = "14px";
        sp.style.maxWidth = "14px";
        sp.style.flex = "0 0 14px";
        boxesContainer.appendChild(sp);
        return;
      }

      const inp = document.createElement("input");
      inp.type = "text";
      inp.maxLength = 1;
      inp.className = "letter-box" + (b.masked ? "" : " unmasked");
      inp.dataset.index = idx;
      inp.style.width = "44px";
      inp.style.minWidth = "44px";
      inp.style.maxWidth = "44px";
      inp.style.height = "52px";
      inp.style.flex = "0 0 44px";
      inp.style.textAlign = "center";
      inp.style.fontSize = "22px";
      inp.style.fontWeight = "700";
      inp.style.fontFamily = "'Inter', monospace";
      inp.style.boxSizing = "border-box";

      if (!b.masked) {
        inp.value = b.char;
        inp.readOnly = true;
        inp.tabIndex = -1;
      } else {
        inp.value = "";
        inputElements.push(inp);

        inp.addEventListener("input", (e) => {
          if (inp.value.length > 0) {
            const nextIdx = inputElements.indexOf(inp) + 1;
            if (nextIdx < inputElements.length) {
              inputElements[nextIdx].focus();
            }
          }
        });

        inp.addEventListener("keydown", (e) => {
          if (e.key === "Backspace" && inp.value === "") {
            const prevIdx = inputElements.indexOf(inp) - 1;
            if (prevIdx >= 0) {
              inputElements[prevIdx].focus();
            }
          } else if (e.key === "Enter") {
            e.preventDefault();
            checkType2Answer(inputElements, boxes);
          }
        });
      }

      boxesContainer.appendChild(inp);
    });

    // Masked input boxes and audio replay button on the right
    const boxesRow = document.createElement("div");
    boxesRow.style.display = "flex";
    boxesRow.style.alignItems = "center";
    boxesRow.style.justifyContent = "center";
    boxesRow.style.gap = "12px";
    boxesRow.style.margin = "20px 0";
    boxesRow.style.direction = "ltr";
    boxesRow.style.overflowX = "auto";
    boxesRow.style.padding = "6px 0";

    boxesContainer.style.margin = "0";
    boxesContainer.style.overflowX = "visible";
    boxesRow.appendChild(boxesContainer);

    const btnAudioType2 = document.createElement("button");
    btnAudioType2.type = "button";
    btnAudioType2.className = "btn-audio-replay";
    btnAudioType2.id = "btn-audio-type2-front";
    btnAudioType2.title = "پخش تلفظ (P)";
    btnAudioType2.setAttribute("aria-label", "پخش تلفظ");
    btnAudioType2.style.flexShrink = "0";
    btnAudioType2.style.width = "44px";
    btnAudioType2.style.height = "44px";
    btnAudioType2.style.fontSize = "19px";
    btnAudioType2.textContent = "🔊";
    btnAudioType2.addEventListener("click", () => {
      if (window.LexiAudio) window.LexiAudio.playCard(currentCard);
    });
    boxesRow.appendChild(btnAudioType2);

    cardInteractionArea.appendChild(boxesRow);

    // Check Answer button
    const btnCheck = document.createElement("button");
    btnCheck.id = "btn-primary-action";
    btnCheck.type = "button";
    btnCheck.className = "btn btn-primary";
    btnCheck.style.width = "100%";
    btnCheck.style.padding = "12px";
    btnCheck.textContent = "بررسی پاسخ (Enter)";
    btnCheck.addEventListener("click", () => checkType2Answer(inputElements, boxes));
    cardBackArea.appendChild(btnCheck);

    // Autofocus first blank
    if (inputElements.length > 0) {
      setTimeout(() => inputElements[0].focus(), 50);
    }
  }

  async function checkType2Answer(inputElements, boxes) {
    if (isAnswerRevealed) return;

    // Collect reconstructed typed word
    let typed = "";
    let inpCursor = 0;
    boxes.forEach((b) => {
      if (b.is_space) {
        typed += " ";
      } else if (!b.masked) {
        typed += b.char;
      } else {
        const val = inputElements[inpCursor] ? inputElements[inpCursor].value : "";
        typed += val || " ";
        inpCursor++;
      }
    });

    currentTypedInput = typed;
    await verifySpellingWithServer(currentTypedInput.trim());
  }

  // -------------------------------------------------------------
  // Card Type 3: Full Dictation (Single Text Input)
  // -------------------------------------------------------------
  function renderType3() {
    const sentenceHtml = `<div class="context-sentence-box" dir="ltr" lang="en">${escapeHtml(currentCard.blanked_sentence || "")}</div>`;
    cardFrontArea.innerHTML = sentenceHtml;

    const inputContainer = document.createElement("div");
    inputContainer.style.display = "flex";
    inputContainer.style.alignItems = "center";
    inputContainer.style.justifyContent = "center";
    inputContainer.style.gap = "10px";
    inputContainer.style.margin = "24px 0";
    inputContainer.style.direction = "ltr";

    const input = document.createElement("input");
    input.type = "text";
    input.className = "form-input";
    input.style.fontSize = "20px";
    input.style.textAlign = "center";
    input.style.fontFamily = "'Inter', sans-serif";
    input.style.direction = "ltr";
    input.style.flex = "1";
    input.placeholder = "کلمه یا عبارت را به طور کامل بنویسید...";

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        currentTypedInput = input.value.trim();
        verifySpellingWithServer(currentTypedInput);
      }
    });

    const btnAudioType3 = document.createElement("button");
    btnAudioType3.type = "button";
    btnAudioType3.className = "btn-audio-replay";
    btnAudioType3.id = "btn-audio-type3-front";
    btnAudioType3.title = "پخش تلفظ (P)";
    btnAudioType3.setAttribute("aria-label", "پخش تلفظ");
    btnAudioType3.style.flexShrink = "0";
    btnAudioType3.style.width = "48px";
    btnAudioType3.style.height = "48px";
    btnAudioType3.style.fontSize = "20px";
    btnAudioType3.textContent = "🔊";
    btnAudioType3.addEventListener("click", () => {
      if (window.LexiAudio) window.LexiAudio.playCard(currentCard);
    });

    inputContainer.appendChild(input);
    inputContainer.appendChild(btnAudioType3);
    cardInteractionArea.appendChild(inputContainer);

    const btnCheck = document.createElement("button");
    btnCheck.id = "btn-primary-action";
    btnCheck.type = "button";
    btnCheck.className = "btn btn-primary";
    btnCheck.style.width = "100%";
    btnCheck.style.padding = "12px";
    btnCheck.textContent = "بررسی دیکته (Enter)";
    btnCheck.addEventListener("click", () => {
      currentTypedInput = input.value.trim();
      verifySpellingWithServer(currentTypedInput);
    });
    cardBackArea.appendChild(btnCheck);

    setTimeout(() => input.focus(), 50);
  }

  /**
   * Calls POST /api/review/check/ to verify spelling and reveal meaning
   */
  async function verifySpellingWithServer(typedInput) {
    if (isAnswerRevealed) return;

    try {
      const res = await fetch("/api/review/check/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify({
          card_id: currentCard.id,
          typed_input: typedInput,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        alert(data.error || "خطا در بررسی پاسخ.");
        return;
      }

      isAnswerRevealed = true;
      lastCheckedSpelling = data.spelling_correct;

      // Unlock "!" button
      btnContext.disabled = false;

      // Render spelling result & meaning
      renderCheckedAnswerView(data);
    } catch (err) {
      console.error(err);
      alert("خطای ارتباط با سرور هنگام بررسی پاسخ.");
    }
  }

  function buildResultBoxes(str, isGreenAll = false, targetStr = "") {
    const chars = Array.from(str || "");
    const targetChars = Array.from(targetStr || "");
    const maxLen = isGreenAll ? chars.length : Math.max(chars.length, targetChars.length);

    if (maxLen === 0) {
      return `<span style="color: #ef4444; font-size: 14px; font-weight: 600;">(بدون پاسخ)</span>`;
    }

    let html = "";
    for (let i = 0; i < maxLen; i++) {
      const targetChar = i < targetChars.length ? targetChars[i] : "";
      const userChar = i < chars.length ? chars[i] : "";

      if (isGreenAll) {
        if (userChar === " ") {
          html += `<div style="width: 14px; min-width: 14px; flex: 0 0 14px; display: inline-block;"></div>`;
        } else {
          html += `<span style="width: 42px; min-width: 42px; max-width: 42px; height: 50px; flex: 0 0 42px; display: inline-flex; align-items: center; justify-content: center; font-size: 22px; font-weight: 700; font-family: 'Inter', monospace; border-radius: 8px; border: 2px solid #22c55e; color: #4ade80; background: rgba(34, 197, 94, 0.12); box-sizing: border-box; text-decoration: none;">${escapeHtml(userChar)}</span>`;
        }
        continue;
      }

      // Checking user typed characters against target
      if (targetChar === " " && (!userChar || userChar === " ")) {
        html += `<div style="width: 14px; min-width: 14px; flex: 0 0 14px; display: inline-block;"></div>`;
        continue;
      }

      if (!userChar || userChar === " ") {
        // Missed letter blank
        html += `<span style="width: 42px; min-width: 42px; max-width: 42px; height: 50px; flex: 0 0 42px; display: inline-flex; align-items: center; justify-content: center; font-size: 20px; font-weight: 700; font-family: 'Inter', monospace; border-radius: 8px; border: 2px dashed #ef4444; color: #ef4444; background: rgba(239, 68, 68, 0.08); box-sizing: border-box; text-decoration: none;">—</span>`;
      } else {
        const isMatch = Boolean(targetChar) && userChar.toLowerCase() === targetChar.toLowerCase();
        const borderColor = isMatch ? "#22c55e" : "#ef4444";
        const textColor = isMatch ? "#4ade80" : "#ef4444";
        const bgColor = isMatch ? "rgba(34, 197, 94, 0.12)" : "rgba(239, 68, 68, 0.15)";
        html += `<span style="width: 42px; min-width: 42px; max-width: 42px; height: 50px; flex: 0 0 42px; display: inline-flex; align-items: center; justify-content: center; font-size: 22px; font-weight: 700; font-family: 'Inter', monospace; border-radius: 8px; border: 2px solid ${borderColor}; color: ${textColor}; background: ${bgColor}; box-sizing: border-box; text-decoration: none;">${escapeHtml(userChar)}</span>`;
      }
    }

    return html;
  }

  function renderCheckedAnswerView(data) {
    const isCorrect = data.spelling_correct;

    // Update current card with revealed word & audio data
    if (data.word) currentCard.word = data.word;
    if (data.audio_url) currentCard.audio_url = data.audio_url;
    if (data.audio_url_uk) currentCard.audio_url_uk = data.audio_url_uk;
    if (data.audio_url_us) currentCard.audio_url_us = data.audio_url_us;
    if (data.accent) currentCard.accent = data.accent;

    const targetWord = (data.word || "").trim();
    const typedWord = (data.typed_input !== undefined ? data.typed_input : (currentTypedInput || "")).trim();

    if (isCorrect) {
      // -------------------------------------------------------------
      // SPELLING IS CORRECT:
      // Show word with green letters in horizontal row and speaker button next to it.
      // Do NOT repeat the word below it!
      // -------------------------------------------------------------
      const greenBoxes = buildResultBoxes(targetWord, true);

      cardInteractionArea.innerHTML = `
        <div style="text-align: center; margin: 16px 0;">
          <div style="font-size: 14px; font-weight: 700; color: #4ade80; margin-bottom: 12px; display: flex; align-items: center; justify-content: center; gap: 6px;">
            <span>✓</span><span>املای درست</span>
          </div>
          <div style="display: flex; align-items: center; justify-content: center; gap: 10px; direction: ltr; margin: 12px 0 20px; overflow-x: auto; padding: 6px 4px;">
            <div style="width: 44px; height: 44px; flex-shrink: 0; visibility: hidden;"></div>
            <div style="display: flex; align-items: center; justify-content: center; gap: 6px; direction: ltr; flex-wrap: nowrap;">
              ${greenBoxes}
            </div>
            <button type="button" class="btn-audio-replay" id="btn-audio-checked" title="پخش تلفظ (P)" aria-label="پخش تلفظ" style="flex-shrink: 0; width: 44px; height: 44px; font-size: 19px;">🔊</button>
          </div>
        </div>
      `;
    } else {
      // -------------------------------------------------------------
      // SPELLING IS INCORRECT:
      // Line 1: What user typed with correct letters in green and wrong letters in red.
      // Line 2: Complete correct word in green with speaker button on the right.
      // Both lines strictly aligned vertically!
      // -------------------------------------------------------------
      const typedBoxes = buildResultBoxes(typedWord, false, targetWord);
      const correctBoxes = buildResultBoxes(targetWord, true);

      cardInteractionArea.innerHTML = `
        <div style="text-align: center; margin: 14px 0;">
          <div style="font-size: 14px; font-weight: 700; color: #ef4444; margin-bottom: 14px; display: flex; align-items: center; justify-content: center; gap: 6px;">
            <span>✗</span><span>املای نادرست</span>
          </div>

          <!-- Line 1: What user typed (Green for correct, Red for mistakes) -->
          <div style="margin-bottom: 16px;">
            <div style="font-size: 12px; font-weight: 600; color: var(--muted); margin-bottom: 6px;">پاسخ شما:</div>
            <div style="display: flex; align-items: center; justify-content: center; gap: 10px; direction: ltr; overflow-x: auto; padding: 6px 4px;">
              <div style="width: 44px; height: 44px; flex-shrink: 0; visibility: hidden;"></div>
              <div style="display: flex; align-items: center; justify-content: center; gap: 6px; direction: ltr; flex-wrap: nowrap;">
                ${typedBoxes}
              </div>
              <div style="width: 44px; height: 44px; flex-shrink: 0; visibility: hidden;"></div>
            </div>
          </div>

          <!-- Line 2: Correct word with speaker button on the right -->
          <div style="margin-bottom: 12px;">
            <div style="font-size: 12px; font-weight: 600; color: var(--muted); margin-bottom: 6px;">کلمه صحیح:</div>
            <div style="display: flex; align-items: center; justify-content: center; gap: 10px; direction: ltr; overflow-x: auto; padding: 6px 4px;">
              <div style="width: 44px; height: 44px; flex-shrink: 0; visibility: hidden;"></div>
              <div style="display: flex; align-items: center; justify-content: center; gap: 6px; direction: ltr; flex-wrap: nowrap;">
                ${correctBoxes}
              </div>
              <button type="button" class="btn-audio-replay" id="btn-audio-checked" title="پخش تلفظ (P)" aria-label="پخش تلفظ" style="flex-shrink: 0; width: 44px; height: 44px; font-size: 19px;">🔊</button>
            </div>
          </div>
        </div>
      `;
    }

    // Meaning, Part of Speech, and SRS buttons
    cardBackArea.innerHTML = `
      <div style="border-top: 1px solid var(--border); padding-top: 20px; text-align: center;">
        <div style="margin-bottom: 12px; display: flex; align-items: center; justify-content: center; gap: 10px;">
          <span class="brand-badge" style="font-size: 13px;">${escapeHtml(data.pos || "")}</span>
          <span style="font-size: 22px; font-weight: 700;">${escapeHtml(data.meaning || "—")}</span>
        </div>
        ${
          data.ai_example
            ? `<div class="text-muted" style="font-size: 13px; direction: ltr; margin-bottom: 16px;">💡 ${escapeHtml(data.ai_example)}</div>`
            : ""
        }
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 20px;">
          <button id="btn-grade-wrong" type="button" class="btn" style="padding: 12px; font-weight: 700;">
            بلد نبودم
          </button>
          <button id="btn-grade-right" type="button" class="btn btn-primary" style="padding: 12px; font-weight: 700;">
            بلد بودم
          </button>
        </div>
      </div>
    `;

    // Hook up audio button
    const btnAudio = document.getElementById("btn-audio-checked");
    if (btnAudio) {
      btnAudio.addEventListener("click", () => {
        if (window.LexiAudio) {
          window.LexiAudio.playCard(currentCard);
        } else if ("speechSynthesis" in window) {
          const u = new SpeechSynthesisUtterance(currentCard.word || "");
          u.lang = currentCard.accent === "uk" ? "en-GB" : "en-US";
          window.speechSynthesis.speak(u);
        }
      });
    }

    // Automatically play audio for the revealed word
    if (window.LexiAudio) {
      window.LexiAudio.playCard(currentCard, true);
    } else if ("speechSynthesis" in window) {
      try {
        const u = new SpeechSynthesisUtterance(currentCard.word || "");
        u.lang = currentCard.accent === "uk" ? "en-GB" : "en-US";
        window.speechSynthesis.speak(u);
      } catch (_) {}
    }

    document.getElementById("btn-grade-wrong").addEventListener("click", () => submitAnswer(false));
    document.getElementById("btn-grade-right").addEventListener("click", () => submitAnswer(true));
  }

  /**
   * Submits card review to POST /api/review/submit/
   */
  async function submitAnswer(meaningCorrect) {
    if (!currentCard) return;

    const payload = {
      card_id: currentCard.id,
      display_type: currentCard.display_type,
      meaning_correct: meaningCorrect,
      typed_input: currentTypedInput || null,
      practice: isPracticeMode,
    };

    try {
      const res = await fetch("/api/review/submit/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken(),
        },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok) {
        if (res.status === 409) {
          alert("این کارت امروز قبلاً مرور شده است.");
        } else {
          alert(data.error || "خطا در ثبت مرور.");
        }
        return;
      }

      // Update statistics
      stats.reviewed++;
      if (meaningCorrect) {
        stats.known++;
      } else {
        stats.missed++;
      }
      if (data.progress) {
        progressState.done = data.progress.done;
        progressState.total = data.progress.total;
      } else {
        progressState.done++;
      }

      // Advance to next card
      currentCardIndex++;
      if (data.is_session_complete || currentCardIndex >= cardsQueue.length) {
        showEndScreen();
      } else {
        renderCurrentCard();
      }
    } catch (err) {
      console.error(err);
      alert("خطای ارتباط با سرور در هنگام ثبت نتیجه مرور.");
    }
  }

  /**
   * Displays the celebratory end-of-session screen
   */
  function showEndScreen() {
    cardContainer.style.display = "none";
    if (sessionEndScreen) {
      sessionEndScreen.style.display = "block";
      if (statTotalReviewed) statTotalReviewed.textContent = stats.reviewed;
      if (statKnown) statKnown.textContent = stats.known;
      if (statTomorrowDue) statTomorrowDue.textContent = tomorrowDueCount;
    }
    if (progressBarFill) progressBarFill.style.width = "100%";
    if (progressText) progressText.textContent = `${progressState.total} / ${progressState.total}`;
  }

  // -------------------------------------------------------------
  // "!" Full-Text Modal Inspection
  // -------------------------------------------------------------
  async function openContextModal() {
    if (!currentCard || btnContext.disabled) return;

    try {
      const res = await fetch(`/api/review/context/${currentCard.id}/`);
      const data = await res.json();
      if (!res.ok) {
        alert(data.error || "امکان باز کردن متن اصلی وجود ندارد.");
        return;
      }

      modalTextTitle.textContent = data.title || "متن اصلی";

      const body = data.body;
      const start = data.char_start;
      const end = data.char_end;

      if (start !== null && end !== null && start < end) {
        const before = escapeHtml(body.slice(0, start));
        const highlighted = escapeHtml(body.slice(start, end));
        const after = escapeHtml(body.slice(end));
        modalTextBody.innerHTML = `${before}<mark id="modal-highlight">${highlighted}</mark>${after}`;
      } else {
        modalTextBody.textContent = body;
      }

      contextModal.style.display = "flex";

      // Auto-scroll highlight into view
      setTimeout(() => {
        const hl = document.getElementById("modal-highlight");
        if (hl) {
          hl.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      }, 50);
    } catch (err) {
      console.error(err);
      alert("خطا در بارگذاری متن اصلی.");
    }
  }

  function closeContextModal() {
    contextModal.style.display = "none";
  }

  btnContext.addEventListener("click", openContextModal);
  btnCloseModal.addEventListener("click", closeContextModal);
  contextModal.addEventListener("click", (e) => {
    if (e.target === contextModal) closeContextModal();
  });

  // -------------------------------------------------------------
  // Keyboard Shortcuts
  // -------------------------------------------------------------
  window.addEventListener("keydown", (e) => {
    // If modal is open, Esc closes it
    if (contextModal.style.display !== "none") {
      if (e.key === "Escape") closeContextModal();
      return;
    }

    // Ignore shortcuts when user is typing inside an input element
    const tag = document.activeElement ? document.activeElement.tagName : "";
    const isTyping = tag === "INPUT" || tag === "TEXTAREA";

    if (e.key === "Escape") {
      closeContextModal();
      return;
    }

    // Space / Enter: Reveal Answer or Check
    if ((e.key === " " || e.key === "Enter") && !isTyping && !isAnswerRevealed) {
      const primaryBtn = document.getElementById("btn-primary-action");
      if (primaryBtn) {
        e.preventDefault();
        primaryBtn.click();
      }
      return;
    }

    // '1' and '2': Grade buttons after answer is revealed
    if (isAnswerRevealed && !isTyping) {
      if (e.key === "1") {
        e.preventDefault();
        submitAnswer(false);
      } else if (e.key === "2") {
        e.preventDefault();
        submitAnswer(true);
      }
    }

    // 'I' or 'i': Open "!" Context Modal (when unlocked)
    if ((e.key === "i" || e.key === "I") && !isTyping) {
      if (!btnContext.disabled) {
        e.preventDefault();
        openContextModal();
      }
    }

    // 'P' or 'p': Replay audio pronunciation
    if ((e.key === "p" || e.key === "P") && !isTyping) {
      if (window.LexiAudio) {
        e.preventDefault();
        window.LexiAudio.replay();
      }
    }
  });

  function escapeHtml(str) {
    if (!str) return "";
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  window.startPracticeMode = async function () {
    if (sessionEndScreen) sessionEndScreen.style.display = "none";
    if (cardContainer) cardContainer.style.display = "block";
    if (cardFrontArea) {
      cardFrontArea.innerHTML = "<div class='empty-state' style='padding: 28px;'>در حال آماده‌سازی کارت‌های آزمایشی...</div>";
    }
    isPracticeMode = true;
    try {
      const res = await fetch("/api/review/session/?practice=1", {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      const data = await res.json();
      if (data.cards && data.cards.length > 0) {
        cardsQueue = data.cards;
        currentCardIndex = 0;
        progressState = { done: 0, total: data.cards.length };
        stats = { reviewed: 0, known: 0, missed: 0 };
        updateProgress();
        renderCurrentCard();
      } else {
        alert("هیچ کارتی برای مرور تمرینی یافت نشد.");
        showEndScreen();
      }
    } catch (e) {
      console.error(e);
      alert("خطا در بارگذاری کارت‌های تمرین.");
      showEndScreen();
    }
  };

  // Start session
  initSession();
})();
