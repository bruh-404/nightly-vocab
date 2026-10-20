/**
 * Nightly Vocab — Interactive Token & Phrase Selection (Patch A & Roadmap Step 4)
 * Handles mouse drag, touch long-press (~250ms), phrase mode fallback,
 * boundary clamping (sentence & punctuation), continuous pill styling,
 * sticky bottom chips bar, manual meanings entry, and card saving API.
 */

(function () {
  "use strict";

  const config = window.LEXICONTEXT_CONFIG || {};
  const container = document.getElementById("reading-container");
  if (!container) return;

  const chipsContainer = document.getElementById("chips-container");
  const noChipsPlaceholder = document.getElementById("no-chips-placeholder");
  const selectedBadge = document.getElementById("selected-badge");
  const btnPhraseModeToggle = document.getElementById("btn-phrase-mode-toggle");
  const btnProceedToEntry = document.getElementById("btn-proceed-to-entry");
  const entrySection = document.getElementById("entry-section");
  const previewTbody = document.getElementById("preview-tbody");
  const btnBackToSelect = document.getElementById("btn-back-to-select");
  const btnCancelEntry = document.getElementById("btn-cancel-entry");
  const selectionAlert = document.getElementById("selection-alert");
  const saveStatusText = document.getElementById("save-status-text");
  const btnSaveCards = document.getElementById("btn-save-cards");
  const btnSaveAndView = document.getElementById("btn-save-and-view");
  const btnAiAnalyze = document.getElementById("btn-ai-analyze");
  const aiBtnText = document.getElementById("ai-btn-text");
  const aiSpinner = document.getElementById("ai-spinner");
  const chkAiExample = document.getElementById("chk-ai-example");

  // All tokens in document order
  const allTokens = Array.from(container.querySelectorAll(".tok"));
  const tokenIndexMap = new Map();
  allTokens.forEach((tok, idx) => tokenIndexMap.set(tok, idx));

  // Current active selections: Array<{ id: string, startIndex: number, endIndex: number, start: number, end: number, text: string, pos: string, meaning: string }>
  let selections = [];
  let phraseModeActive = false;

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
  let phraseModeFirstTok = null;
  let lastInteractedTok = null;

  // Touch & Pointer state
  let isPointerDown = false;
  let isPhraseDragging = false;
  let pointerStartTok = null;
  let touchHoldTimer = null;
  let touchStartPos = { x: 0, y: 0 };
  let currentDragTok = null;
  const DELIMITER_CHARS = new Set([",", ";", ":", "—", "(", ")", '"', "“", "”", "!", "?", "."]);

  // Prevent native context menu on text container
  container.addEventListener("contextmenu", (e) => e.preventDefault());

  // Technical Challenge 3: Register non-passive touchmove upfront on container
  // to avoid Safari iOS discarding preventDefault()
  container.addEventListener(
    "touchmove",
    function (e) {
      if (isPhraseDragging) {
        e.preventDefault();
      }
    },
    { passive: false }
  );

  // Irregular verbs mapping for simple base form (Lemma)
  const IRREGULAR_VERB_MAP = {
    arose: "arise", arisen: "arise", awoke: "awake", awoken: "awake", was: "be", were: "be", been: "be",
    bore: "bear", born: "bear", beat: "beat", beaten: "beat", became: "become", began: "begin", begun: "begin",
    bent: "bend", bound: "bind", bit: "bite", bitten: "bite", bled: "bleed", blew: "blow", blown: "blow",
    broke: "break", broken: "break", bred: "breed", brought: "bring", built: "build", burnt: "burn", burned: "burn",
    bought: "buy", caught: "catch", chose: "choose", chosen: "choose", clung: "cling", came: "come", cost: "cost",
    crept: "creep", dealt: "deal", dug: "dig", did: "do", done: "do", drew: "draw", drawn: "draw",
    dreamt: "dream", dreamed: "dream", drank: "drink", drunk: "drink", drove: "drive", driven: "drive",
    ate: "eat", eaten: "eat", fell: "fall", fallen: "fall", fed: "feed", felt: "feel", fought: "fight",
    found: "find", fled: "flee", flew: "fly", flown: "fly", forbade: "forbid", forbidden: "forbid",
    forgot: "forget", forgotten: "forget", forgave: "forgive", forgiven: "forgive", froze: "freeze", frozen: "freeze",
    got: "get", gotten: "get", gave: "give", given: "give", went: "go", gone: "go", ground: "grind",
    grew: "grow", grown: "grow", hung: "hang", had: "have", heard: "hear", hid: "hide", hidden: "hide",
    held: "hold", kept: "keep", knelt: "kneel", knew: "know", known: "know", laid: "lay", led: "lead",
    leant: "lean", leaned: "lean", leapt: "leap", leaped: "leap", learnt: "learn", learned: "learn",
    left: "leave", lent: "lend", lost: "lose", made: "make", meant: "mean", met: "meet", paid: "pay",
    put: "put", read: "read", rode: "ride", ridden: "ride", rang: "ring", rung: "ring", rose: "rise",
    risen: "rise", ran: "run", said: "say", saw: "see", seen: "see", sought: "seek", sold: "sell",
    sent: "send", shook: "shake", shaken: "shake", shone: "shine", shot: "shoot", showed: "show",
    shown: "show", shrank: "shrink", shrunk: "shrink", shut: "shut", sang: "sing", sung: "sing",
    sank: "sink", sunk: "sink", sat: "sit", slept: "sleep", slid: "slide", spoke: "speak", spoken: "speak",
    spent: "spend", spun: "spin", spat: "spit", split: "split", spread: "spread", sprung: "spring",
    sprang: "spring", stood: "stand", stole: "steal", stolen: "steal", stuck: "stick", stung: "sting",
    struck: "strike", swore: "swear", sworn: "swear", swept: "sweep", swam: "swim", swum: "swim",
    swung: "swing", took: "take", taken: "take", taught: "teach", tore: "tear", torn: "tear",
    told: "tell", thought: "think", threw: "throw", thrown: "throw", understood: "understand",
    woke: "wake", woken: "wake", wore: "wear", worn: "wear", wept: "weep", won: "win", wound: "wind",
    wrote: "write", written: "write"
  };

  const NON_INFLECTED_S_ENDINGS = ["us", "is", "os", "as", "ss", "cs"];

  function lemmatizeEnglishWord(surface, pos = "") {
    const cleaned = (surface || "").trim();
    if (!cleaned || cleaned.includes(" ")) {
      return cleaned;
    }

    const posLower = (pos || "").toLowerCase();
    // Only lemmatize if POS is noun or verb (or empty)
    if (posLower && posLower !== "noun" && posLower !== "verb") {
      return cleaned;
    }

    const w = cleaned.toLowerCase();

    // 1. Irregular verbs reverse lookup
    if (IRREGULAR_VERB_MAP[w]) {
      const base = IRREGULAR_VERB_MAP[w];
      return cleaned[0] === cleaned[0].toUpperCase() && cleaned[0] !== cleaned[0].toLowerCase()
        ? base.charAt(0).toUpperCase() + base.slice(1)
        : base;
    }

    // 2. -ies -> -y (e.g. memories -> memory, studies -> study, cities -> city)
    if (w.endsWith("ies") && w.length > 4 && !"aeiou".includes(w.charAt(w.length - 4))) {
      const base = w.slice(0, -3) + "y";
      return cleaned[0] === cleaned[0].toUpperCase() ? base.charAt(0).toUpperCase() + base.slice(1) : base;
    }

    // 3. -es (e.g. watches -> watch, boxes -> box, dishes -> dish, classes -> class)
    if (w.endsWith("es") && w.length > 3) {
      for (const ending of ["shes", "ches", "sses", "xes", "zes"]) {
        if (w.endsWith(ending)) {
          const base = w.slice(0, -2);
          return cleaned[0] === cleaned[0].toUpperCase() ? base.charAt(0).toUpperCase() + base.slice(1) : base;
        }
      }
    }

    // 4. -s (e.g. allows -> allow, requires -> require, books -> book, but NOT focus, status, virus, class, analysis)
    const hasProtectedSuffix = NON_INFLECTED_S_ENDINGS.some(ending => w.endsWith(ending));
    if (w.endsWith("s") && !hasProtectedSuffix && w.length > 3) {
      const base = w.slice(0, -1);
      return cleaned[0] === cleaned[0].toUpperCase() ? base.charAt(0).toUpperCase() + base.slice(1) : base;
    }

    // 5. -ing (e.g. running -> run, allowing -> allow, taking -> take)
    if (w.endsWith("ing") && w.length > 4) {
      const stem = w.slice(0, -3);
      if (stem.endsWith("t") && stem.length > 2 && "aeiou".includes(stem.charAt(stem.length - 2)) && !"aeiou".includes(stem.charAt(stem.length - 3))) {
        const base = stem.charAt(stem.length - 1) === stem.charAt(stem.length - 2) ? stem.slice(0, -1) : stem;
        return cleaned[0] === cleaned[0].toUpperCase() ? base.charAt(0).toUpperCase() + base.slice(1) : base;
      }
      if (["v", "s", "z", "c", "t", "d", "g", "r", "l", "m", "n", "p"].some(ch => stem.endsWith(ch))) {
        const base = stem + "e";
        return cleaned[0] === cleaned[0].toUpperCase() ? base.charAt(0).toUpperCase() + base.slice(1) : base;
      }
      return cleaned[0] === cleaned[0].toUpperCase() ? stem.charAt(0).toUpperCase() + stem.slice(1) : stem;
    }

    // 6. -ed (e.g. allowed -> allow, consolidated -> consolidate, studied -> study)
    if (w.endsWith("ed") && w.length > 3) {
      const stem = w.slice(0, -2);
      if (stem.endsWith("i")) {
        const base = stem.slice(0, -1) + "y";
        return cleaned[0] === cleaned[0].toUpperCase() ? base.charAt(0).toUpperCase() + base.slice(1) : base;
      }
      if (stem.endsWith("d") && stem.length > 2 && stem.charAt(stem.length - 1) === stem.charAt(stem.length - 2)) {
        const base = stem.slice(0, -1);
        return cleaned[0] === cleaned[0].toUpperCase() ? base.charAt(0).toUpperCase() + base.slice(1) : base;
      }
      if (["at", "id", "is", "iz", "ov", "ut"].some(ch => stem.endsWith(ch))) {
        const base = stem + "e";
        return cleaned[0] === cleaned[0].toUpperCase() ? base.charAt(0).toUpperCase() + base.slice(1) : base;
      }
      return cleaned[0] === cleaned[0].toUpperCase() ? stem.charAt(0).toUpperCase() + stem.slice(1) : stem;
    }

    return cleaned;
  }

  function guessSingleWordPos(word) {
    const w = (word || "").trim().toLowerCase();
    if (!w || w.includes(" ")) return "phrase";
    if (IRREGULAR_VERB_MAP[w]) return "verb";
    if (w.endsWith("ing") && w.length > 4) return "verb";
    if (w.endsWith("ed") && w.length > 3) return "verb";
    const COMMON_VERBS = [
      "allows", "allow", "requires", "require", "enables", "enable",
      "includes", "include", "contains", "contain", "provides", "provide",
      "improves", "improve", "increases", "increase", "decreases", "decrease",
      "suggests", "suggest", "indicates", "indicate", "enhances", "enhance",
      "focuses", "helps", "help", "needs", "need", "wants", "want", "uses", "use"
    ];
    if (COMMON_VERBS.includes(w)) {
      return "verb";
    }
    return "noun";
  }

  /**
   * Helper to show alerts
   */
  function showAlert(msg) {
    if (!selectionAlert) return;
    selectionAlert.textContent = msg;
    selectionAlert.style.display = "block";
    setTimeout(() => {
      selectionAlert.style.display = "none";
    }, 4000);
  }

  /**
   * Checks if range between token idx1 and idx2 crosses punctuation delimiters or sentence boundaries.
   */
  function isDelimitedBetween(idx1, idx2) {
    const low = Math.min(idx1, idx2);
    const high = Math.max(idx1, idx2);
    const sent = allTokens[low].dataset.sent;

    for (let i = low; i <= high; i++) {
      if (allTokens[i].dataset.sent !== sent) {
        return true; // Crossed sentence boundary
      }
    }

    // Check intermediate DOM text nodes for delimiters
    for (let i = low; i < high; i++) {
      let node = allTokens[i].nextSibling;
      while (node && node !== allTokens[i + 1]) {
        if (node.nodeType === Node.TEXT_NODE) {
          const text = node.textContent;
          for (let c of text) {
            if (DELIMITER_CHARS.has(c)) {
              return true;
            }
          }
        }
        node = node.nextSibling;
      }
    }

    return false;
  }

  /**
   * Clamps target token index to valid phrase range (max 5 tokens, same sentence, no delimiters)
   */
  function getClampedRange(startIdx, targetIdx) {
    const direction = targetIdx >= startIdx ? 1 : -1;
    let validEndIdx = startIdx;

    let step = 0;
    let curr = startIdx;
    while (step < 4) { // max 5 tokens total (start + 4)
      const next = curr + direction;
      if (next < 0 || next >= allTokens.length) break;
      if (isDelimitedBetween(curr, next)) break;
      curr = next;
      step++;
      validEndIdx = curr;
      if (curr === targetIdx) break;
    }

    const minIdx = Math.min(startIdx, validEndIdx);
    const maxIdx = Math.max(startIdx, validEndIdx);
    return { minIdx, maxIdx };
  }

  /**
   * Extracts clean text for token span
   */
  function extractSpanText(minIdx, maxIdx) {
    const words = [];
    for (let i = minIdx; i <= maxIdx; i++) {
      words.push(allTokens[i].textContent.trim());
    }
    return words.join(" ");
  }

  /**
   * Highlights or clears dragging preview tokens
   */
  function setDragPreview(minIdx, maxIdx) {
    allTokens.forEach((t) => t.classList.remove("dragging"));
    if (minIdx !== null && maxIdx !== null) {
      for (let i = minIdx; i <= maxIdx; i++) {
        allTokens[i].classList.add("dragging");
      }
    }
  }

  /**
   * Finds existing selection containing a token
   */
  function findSelectionForToken(tok) {
    const idx = tokenIndexMap.get(tok);
    if (idx === undefined) return null;
    return selections.find((s) => idx >= s.startIndex && idx <= s.endIndex) || null;
  }

  /**
   * Adds or replaces a selection
   */
  function applySelection(minIdx, maxIdx) {
    // Check maximum selections quota
    if (selections.length >= 30) {
      showAlert("حداکثر ۳۰ کلمه یا عبارت در هر متن قابل انتخاب است.");
      return;
    }

    // Remove any overlapping selections
    selections = selections.filter((s) => {
      const overlaps = !(s.endIndex < minIdx || s.startIndex > maxIdx);
      return !overlaps;
    });

    const firstTok = allTokens[minIdx];
    const lastTok = allTokens[maxIdx];
    const charStart = parseInt(firstTok.dataset.start, 10);
    const charEnd = parseInt(lastTok.dataset.end, 10);
    const phraseText = extractSpanText(minIdx, maxIdx);
    const isMultiWord = minIdx !== maxIdx || phraseText.includes(" ");
    const defaultPos = isMultiWord ? "phrase" : guessSingleWordPos(phraseText);
    const isNounOrVerb = defaultPos === "noun" || defaultPos === "verb";
    const initialLemma = isNounOrVerb ? lemmatizeEnglishWord(phraseText, defaultPos) : phraseText;

    // Check if this span matches or overlaps any previously saved card for editing
    let matchedSavedCard = null;
    const savedCardsList = config.savedCards || [];

    matchedSavedCard = savedCardsList.find((c) => {
      if (c.start !== null && c.end !== null) {
        return (
          (c.start <= charStart && c.end >= charEnd) ||
          (charStart <= c.start && charEnd >= c.end) ||
          (charStart < c.end && charEnd > c.start)
        );
      }
      return false;
    });

    if (!matchedSavedCard) {
      for (let i = minIdx; i <= maxIdx; i++) {
        const t = allTokens[i];
        if (t && t.dataset.saved === "1" && t.dataset.meaning !== undefined) {
          matchedSavedCard = {
            id: t.dataset.cardId ? parseInt(t.dataset.cardId, 10) : null,
            pos: t.dataset.pos || "",
            lemma: t.dataset.lemma || "",
            meaning: t.dataset.meaning || "",
            example: t.dataset.example || "",
          };
          break;
        }
      }
    }

    const isEditing = !!matchedSavedCard;
    const assignedPos = (matchedSavedCard && matchedSavedCard.pos) ? matchedSavedCard.pos : defaultPos;
    const assignedMeaning = (matchedSavedCard && matchedSavedCard.meaning) ? matchedSavedCard.meaning : "";
    const assignedLemma = (matchedSavedCard && matchedSavedCard.lemma) ? matchedSavedCard.lemma : initialLemma;
    const assignedExample = (matchedSavedCard && matchedSavedCard.example) ? matchedSavedCard.example : "";
    const cardId = matchedSavedCard ? matchedSavedCard.id : null;

    const newSel = {
      id: "sel-" + Date.now() + "-" + Math.random().toString(36).substr(2, 5),
      startIndex: minIdx,
      endIndex: maxIdx,
      start: charStart,
      end: charEnd,
      text: phraseText,
      pos: assignedPos,
      lemma: assignedLemma,
      meaning: assignedMeaning,
      example: assignedExample,
      isEditing: isEditing,
      cardId: cardId,
    };

    selections.push(newSel);
    renderAllSelections();
  }

  /**
   * Removes a selection
   */
  function removeSelection(id) {
    selections = selections.filter((s) => s.id !== id);
    renderAllSelections();
  }

  /**
   * Re-renders DOM styling and bottom bar chips
   */
  function renderAllSelections() {
    // Clear all token classes
    allTokens.forEach((tok) => {
      tok.classList.remove("selected", "editing-saved", "phrase-start", "phrase-mid", "phrase-end", "dragging");
    });

    // Apply classes for each selection
    selections.forEach((s) => {
      const isMulti = s.startIndex !== s.endIndex;
      for (let i = s.startIndex; i <= s.endIndex; i++) {
        const tok = allTokens[i];
        tok.classList.add("selected");
        if (s.isEditing || tok.classList.contains("already-saved")) {
          tok.classList.add("editing-saved");
        }
        if (isMulti) {
          if (i === s.startIndex) {
            tok.classList.add("phrase-start");
          } else if (i === s.endIndex) {
            tok.classList.add("phrase-end");
          } else {
            tok.classList.add("phrase-mid");
          }
        }
      }
    });

    // Update bottom chips
    chipsContainer.innerHTML = "";
    if (selections.length === 0) {
      chipsContainer.appendChild(noChipsPlaceholder);
      selectedBadge.textContent = "۰ مورد";
      btnProceedToEntry.disabled = true;
      btnProceedToEntry.textContent = "ورود دستی";
      if (btnAiAnalyze) btnAiAnalyze.disabled = true;
    } else {
      selectedBadge.textContent = `${selections.length} مورد`;
      btnProceedToEntry.disabled = false;
      btnProceedToEntry.textContent = `ورود دستی (${selections.length} مورد)`;
      if (btnAiAnalyze) btnAiAnalyze.disabled = false;

      selections.forEach((s) => {
        const chip = document.createElement("span");
        chip.className = "chip";
        if (s.isEditing) {
          chip.style.borderColor = "#eab308";
          chip.style.background = "rgba(234, 179, 8, 0.18)";
          chip.style.color = "#fef08a";
        }

        const textSpan = document.createElement("span");
        const displayText = s.text.length > 20 ? s.text.slice(0, 18) + "…" : s.text;
        textSpan.textContent = s.isEditing ? `${displayText} (ویرایش)` : displayText;
        chip.appendChild(textSpan);

        const btnRemove = document.createElement("button");
        btnRemove.type = "button";
        btnRemove.className = "chip-remove";
        btnRemove.textContent = "✕";
        btnRemove.setAttribute("aria-label", "حذف " + s.text);
        btnRemove.addEventListener("click", (e) => {
          e.stopPropagation();
          removeSelection(s.id);
        });
        chip.appendChild(btnRemove);

        chipsContainer.appendChild(chip);
      });
    }

    // Update manual table if visible
    if (entrySection.style.display !== "none") {
      populatePreviewTable();
    }
  }

  // -------------------------------------------------------------
  // Pointer & Touch Events
  // -------------------------------------------------------------

  container.addEventListener("pointerdown", (e) => {
    const tok = e.target.closest(".tok");
    if (!tok) return;

    isPointerDown = true;
    pointerStartTok = tok;
    isPhraseDragging = false;
    currentDragTok = tok;
    touchStartPos = { x: e.clientX, y: e.clientY };

    if (e.pointerType === "touch") {
      // Long-press detection (~250ms)
      clearTimeout(touchHoldTimer);
      touchHoldTimer = setTimeout(() => {
        if (isPointerDown) {
          isPhraseDragging = true;
          if (navigator.vibrate) {
            try { navigator.vibrate(10); } catch (_) {}
          }
          const idx = tokenIndexMap.get(pointerStartTok);
          setDragPreview(idx, idx);
        }
      }, 250);
    }
  });

  window.addEventListener("pointermove", (e) => {
    if (!isPointerDown || !pointerStartTok) return;

    if (e.pointerType === "touch" && !isPhraseDragging) {
      const dist = Math.hypot(e.clientX - touchStartPos.x, e.clientY - touchStartPos.y);
      if (dist > 8) {
        // Canceled long-press: treat as normal page scroll
        clearTimeout(touchHoldTimer);
        isPointerDown = false;
        pointerStartTok = null;
        return;
      }
    }

    if (e.pointerType === "mouse") {
      const dist = Math.hypot(e.clientX - touchStartPos.x, e.clientY - touchStartPos.y);
      if (dist > 4 && !isPhraseDragging) {
        isPhraseDragging = true;
      }
    }

    if (isPhraseDragging) {
      const el = document.elementFromPoint(e.clientX, e.clientY);
      const targetTok = el ? el.closest(".tok") : null;
      if (targetTok && targetTok !== currentDragTok) {
        currentDragTok = targetTok;
        const sIdx = tokenIndexMap.get(pointerStartTok);
        const tIdx = tokenIndexMap.get(targetTok);
        if (sIdx !== undefined && tIdx !== undefined) {
          const { minIdx, maxIdx } = getClampedRange(sIdx, tIdx);
          setDragPreview(minIdx, maxIdx);
        }
      }
    }
  });

  window.addEventListener("pointerup", (e) => {
    clearTimeout(touchHoldTimer);
    if (!isPointerDown) return;

    const startTok = pointerStartTok;
    const wasDragging = isPhraseDragging;

    isPointerDown = false;
    isPhraseDragging = false;
    pointerStartTok = null;
    currentDragTok = null;
    setDragPreview(null, null);

    if (!startTok) return;

    if (wasDragging) {
      const el = document.elementFromPoint(e.clientX, e.clientY);
      const endTok = el ? el.closest(".tok") : startTok;
      const sIdx = tokenIndexMap.get(startTok);
      const eIdx = tokenIndexMap.get(endTok || startTok);

      if (sIdx !== undefined && eIdx !== undefined) {
        const { minIdx, maxIdx } = getClampedRange(sIdx, eIdx);
        applySelection(minIdx, maxIdx);
        lastInteractedTok = allTokens[maxIdx];
      }
    } else {
      // Tap / Single click handler
      handleSingleTap(startTok, e);
    }
  });

  window.addEventListener("pointercancel", () => {
    clearTimeout(touchHoldTimer);
    isPointerDown = false;
    isPhraseDragging = false;
    pointerStartTok = null;
    currentDragTok = null;
    setDragPreview(null, null);
  });

  /**
   * Single tap or click handling (with Shift-click and Phrase mode)
   */
  function handleSingleTap(tok, e) {
    const clickedIdx = tokenIndexMap.get(tok);
    if (clickedIdx === undefined) return;

    // Shift + Click handling
    if (e && e.shiftKey && lastInteractedTok) {
      const lastIdx = tokenIndexMap.get(lastInteractedTok);
      if (lastIdx !== undefined && lastIdx !== clickedIdx) {
        const { minIdx, maxIdx } = getClampedRange(lastIdx, clickedIdx);
        applySelection(minIdx, maxIdx);
        lastInteractedTok = tok;
        return;
      }
    }

    // Phrase mode toggle logic
    if (phraseModeActive) {
      if (!phraseModeFirstTok) {
        phraseModeFirstTok = tok;
        tok.classList.add("selected");
        showAlert("کلمهٔ اول انتخاب شد. اکنون کلمهٔ پایان عبارت را بزنید.");
        return;
      } else {
        const firstIdx = tokenIndexMap.get(phraseModeFirstTok);
        phraseModeFirstTok.classList.remove("selected");
        const { minIdx, maxIdx } = getClampedRange(firstIdx, clickedIdx);
        applySelection(minIdx, maxIdx);
        phraseModeFirstTok = null;
        lastInteractedTok = tok;
        return;
      }
    }

    // Normal single-word toggle
    const existing = findSelectionForToken(tok);
    if (existing) {
      removeSelection(existing.id);
      lastInteractedTok = null;
    } else {
      if (tok.dataset.saved === "1" && tok.dataset.cardStart && tok.dataset.cardEnd) {
        const cStart = parseInt(tok.dataset.cardStart, 10);
        const cEnd = parseInt(tok.dataset.cardEnd, 10);
        const sIdx = allTokens.findIndex((t) => parseInt(t.dataset.start, 10) === cStart);
        const eIdx = allTokens.findIndex((t) => parseInt(t.dataset.end, 10) === cEnd);
        if (sIdx !== -1 && eIdx !== -1) {
          applySelection(sIdx, eIdx);
          lastInteractedTok = allTokens[eIdx];
          return;
        }
      }
      applySelection(clickedIdx, clickedIdx);
      lastInteractedTok = tok;
    }
  }

  // Phrase Mode button
  btnPhraseModeToggle.addEventListener("click", () => {
    phraseModeActive = !phraseModeActive;
    phraseModeFirstTok = null;
    if (phraseModeActive) {
      btnPhraseModeToggle.textContent = "حالت عبارت: روشن (۲ لمس)";
      btnPhraseModeToggle.classList.add("btn-primary");
      showAlert("حالت عبارت فعال شد: روی کلمهٔ اول و سپس کلمهٔ آخر بزنید.");
    } else {
      btnPhraseModeToggle.textContent = "حالت عبارت: خاموش";
      btnPhraseModeToggle.classList.remove("btn-primary");
    }
  });

  // -------------------------------------------------------------
  // Manual Meanings Preview Table & Save API
  // -------------------------------------------------------------

  function populatePreviewTable() {
    previewTbody.innerHTML = "";
    const choices = config.posChoices || [
      { value: "noun", label: "Noun" },
      { value: "verb", label: "Verb" },
      { value: "adjective", label: "Adjective" },
      { value: "adverb", label: "Adverb" },
      { value: "phrase", label: "Phrase" },
      { value: "idiom", label: "Idiom" },
      { value: "phrasal verb", label: "Phrasal Verb" },
    ];

    selections.forEach((sel) => {
      const tr = document.createElement("tr");

      // Word / Phrase with editable Base Form (Lemma)
      const tdWord = document.createElement("td");
      tdWord.style.textAlign = "left";
      tdWord.style.fontFamily = "'Inter', sans-serif";

      const origDiv = document.createElement("div");
      origDiv.style.fontWeight = "700";
      origDiv.style.fontSize = "14px";
      origDiv.style.display = "flex";
      origDiv.style.alignItems = "center";
      origDiv.style.gap = "8px";

      const wordSpan = document.createElement("span");
      wordSpan.textContent = sel.text;
      origDiv.appendChild(wordSpan);

      if (sel.isEditing) {
        const editBadge = document.createElement("span");
        editBadge.className = "brand-badge";
        editBadge.style.fontSize = "11px";
        editBadge.style.padding = "2px 6px";
        editBadge.style.borderColor = "#eab308";
        editBadge.style.color = "#facc15";
        editBadge.style.background = "rgba(234, 179, 8, 0.15)";
        editBadge.textContent = "ویرایش";
        origDiv.appendChild(editBadge);
      }
      tdWord.appendChild(origDiv);

      const isNounOrVerb = sel.pos === "noun" || sel.pos === "verb";

      if (isNounOrVerb) {
        if (!sel.lemma || sel.lemma === sel.text) {
          sel.lemma = lemmatizeEnglishWord(sel.text, sel.pos);
        }
      } else {
        sel.lemma = sel.text;
      }

      const lemmaDiv = document.createElement("div");
      lemmaDiv.style.marginTop = "4px";
      lemmaDiv.style.display = isNounOrVerb ? "flex" : "none";
      lemmaDiv.style.alignItems = "center";
      lemmaDiv.style.gap = "6px";

      const lemmaLbl = document.createElement("span");
      lemmaLbl.style.fontSize = "11px";
      lemmaLbl.style.color = "var(--muted)";
      lemmaLbl.textContent = "شکل ساده:";

      const inputLemma = document.createElement("input");
      inputLemma.type = "text";
      inputLemma.className = "form-input";
      inputLemma.style.padding = "2px 8px";
      inputLemma.style.fontSize = "12px";
      inputLemma.style.width = "110px";
      inputLemma.style.direction = "ltr";
      inputLemma.value = sel.lemma || sel.text;
      inputLemma.addEventListener("input", (e) => {
        sel.lemma = e.target.value.trim();
      });

      lemmaDiv.appendChild(lemmaLbl);
      lemmaDiv.appendChild(inputLemma);
      tdWord.appendChild(lemmaDiv);

      if (sel.example) {
        const exContainer = document.createElement("div");
        exContainer.className = "word-example-tooltip-wrap";
        exContainer.style.position = "relative";
        exContainer.style.display = "inline-flex";
        exContainer.style.alignItems = "center";
        exContainer.style.marginTop = "6px";

        const exBadge = document.createElement("button");
        exBadge.type = "button";
        exBadge.className = "btn-example-tooltip";
        exBadge.innerHTML = "💡 <span style='font-size: 11px;'>مثال جمله‌ای</span>";
        exBadge.title = "برای مشاهده یا بستن مثال جمله‌ای کلیک کنید";

        const exPopup = document.createElement("div");
        exPopup.className = "example-popup-box";
        exPopup.innerHTML = `
          <div style="font-size: 11px; font-weight: 700; color: #818cf8; margin-bottom: 4px; display: flex; justify-content: space-between; align-items: center;">
            <span>✨ مثال جمله‌ای هوش مصنوعی</span>
            <span style="font-size: 10px; opacity: 0.7;">(کلیک برای بستن)</span>
          </div>
          <div style="direction: ltr; text-align: left; font-family: 'Inter', sans-serif; font-size: 12.5px; color: var(--text); line-height: 1.5; font-weight: 500;">
            ${escapeHtml(sel.example)}
          </div>
        `;

        exBadge.addEventListener("click", (e) => {
          e.stopPropagation();
          const isShown = exPopup.classList.contains("show");
          document.querySelectorAll(".example-popup-box.show").forEach((p) => p.classList.remove("show"));
          if (!isShown) {
            exPopup.classList.add("show");
          }
        });

        exBadge.addEventListener("mouseenter", () => {
          exPopup.classList.add("show");
        });

        exContainer.addEventListener("mouseleave", () => {
          exPopup.classList.remove("show");
        });

        exPopup.addEventListener("click", (e) => {
          e.stopPropagation();
          exPopup.classList.remove("show");
        });

        exContainer.appendChild(exBadge);
        exContainer.appendChild(exPopup);
        tdWord.appendChild(exContainer);
      }
      tr.appendChild(tdWord);

      // POS select
      const tdPos = document.createElement("td");
      const selPos = document.createElement("select");
      selPos.className = "form-select";
      choices.forEach((c) => {
        const opt = document.createElement("option");
        opt.value = c.value;
        opt.textContent = c.label;
        if (c.value === sel.pos) opt.selected = true;
        selPos.appendChild(opt);
      });
      selPos.addEventListener("change", (e) => {
        sel.pos = e.target.value;
        const nowNounOrVerb = sel.pos === "noun" || sel.pos === "verb";
        lemmaDiv.style.display = nowNounOrVerb ? "flex" : "none";
        if (nowNounOrVerb) {
          if (!sel.lemma || sel.lemma === sel.text) {
            sel.lemma = lemmatizeEnglishWord(sel.text, sel.pos);
            inputLemma.value = sel.lemma;
          }
        } else {
          sel.lemma = sel.text;
        }
      });
      tdPos.appendChild(selPos);
      tr.appendChild(tdPos);

      // Meaning input
      const tdMeaning = document.createElement("td");
      const inputMeaning = document.createElement("input");
      inputMeaning.type = "text";
      inputMeaning.className = "form-input meaning-placeholder";
      inputMeaning.placeholder = "meaning";
      inputMeaning.dir = "rtl";
      inputMeaning.value = sel.meaning || "";
      inputMeaning.addEventListener("input", (e) => {
        sel.meaning = e.target.value;
      });
      tdMeaning.appendChild(inputMeaning);
      tr.appendChild(tdMeaning);

      // Delete row button (styled with red ✕ icon per user specification)
      const tdActions = document.createElement("td");
      tdActions.style.textAlign = "center";
      const btnDel = document.createElement("button");
      btnDel.type = "button";
      btnDel.className = "btn";
      btnDel.style.padding = "4px 8px";
      btnDel.style.fontSize = "13px";
      btnDel.style.fontWeight = "700";
      btnDel.style.color = "#ef4444";
      btnDel.style.borderColor = "rgba(239, 68, 68, 0.4)";
      btnDel.style.background = "rgba(239, 68, 68, 0.08)";
      btnDel.style.borderRadius = "6px";
      btnDel.style.cursor = "pointer";
      btnDel.style.transition = "all 0.15s ease";
      btnDel.textContent = "✕";
      btnDel.title = "حذف این واژه";
      btnDel.onmouseover = () => {
        btnDel.style.background = "rgba(239, 68, 68, 0.2)";
        btnDel.style.borderColor = "#ef4444";
      };
      btnDel.onmouseout = () => {
        btnDel.style.background = "rgba(239, 68, 68, 0.08)";
        btnDel.style.borderColor = "rgba(239, 68, 68, 0.4)";
      };
      btnDel.addEventListener("click", () => {
        removeSelection(sel.id);
      });
      tdActions.appendChild(btnDel);
      tr.appendChild(tdActions);

      previewTbody.appendChild(tr);
    });
  }

  // AI Analyze Button Handler
  if (btnAiAnalyze) {
    btnAiAnalyze.addEventListener("click", async () => {
      if (selections.length === 0) return;

      btnAiAnalyze.disabled = true;
      btnProceedToEntry.disabled = true;
      if (aiSpinner) aiSpinner.style.display = "inline-block";
      if (aiBtnText) aiBtnText.textContent = "در حال تحلیل...";

      const payload = {
        targets: selections.map((s) => ({ start: s.start, end: s.end })),
        want_example: chkAiExample ? chkAiExample.checked : false,
      };

      const aiBanner = document.getElementById("entry-ai-error-banner");
      if (aiBanner) {
        aiBanner.style.display = "none";
        aiBanner.textContent = "";
      }

      try {
        const res = await fetch(`/api/texts/${config.textId}/analyze/`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": config.csrfToken,
          },
          body: JSON.stringify(payload),
        });

        const data = await res.json();
        if (res.ok && data.success && data.items) {
          data.items.forEach((item) => {
            const match = selections.find((s) => s.start === item.start && s.end === item.end);
            if (match) {
              if (item.pos) match.pos = item.pos;
              if (item.meaning) match.meaning = item.meaning;
              const isNounOrVerb = match.pos === "noun" || match.pos === "verb";
              if (isNounOrVerb) {
                match.lemma = item.lemma || lemmatizeEnglishWord(match.text, match.pos);
              } else {
                match.lemma = match.text;
              }
              if (item.example) match.example = item.example;
            }
          });
          showAlert("معانی و نقش‌های دستوری توسط هوش مصنوعی استخراج شدند.");
          if (aiBanner) aiBanner.style.display = "none";
        } else {
          const detail = data.detail ? ` (${data.detail})` : "";
          const msg = (data.error || "سرویس هوش مصنوعی در دسترس نیست.") + detail;
          showAlert(data.error || "خطا در ارتباط با هوش مصنوعی");
          if (aiBanner) {
            aiBanner.textContent = `⚠️ ${msg}`;
            aiBanner.style.display = "block";
          }
        }
      } catch (err) {
        console.error(err);
        const failMsg = "خطای ارتباط با سرور. لطفاً معانی را به صورت دستی تکمیل کنید.";
        showAlert(failMsg);
        if (aiBanner) {
          aiBanner.textContent = `⚠️ ${failMsg}`;
          aiBanner.style.display = "block";
        }
      } finally {
        btnAiAnalyze.disabled = selections.length === 0;
        btnProceedToEntry.disabled = selections.length === 0;
        if (aiSpinner) aiSpinner.style.display = "none";
        if (aiBtnText) aiBtnText.textContent = "استخراج با AI ✨";

        // Always show entry table so flow is never blocked
        populatePreviewTable();
        entrySection.style.display = "block";
        entrySection.scrollIntoView({ behavior: "smooth" });
      }
    });
  }

  btnProceedToEntry.addEventListener("click", () => {
    if (selections.length === 0) return;
    const aiBanner = document.getElementById("entry-ai-error-banner");
    if (aiBanner) aiBanner.style.display = "none";
    populatePreviewTable();
    entrySection.style.display = "block";
    entrySection.scrollIntoView({ behavior: "smooth" });
  });

  btnBackToSelect.addEventListener("click", () => {
    entrySection.style.display = "none";
    container.scrollIntoView({ behavior: "smooth" });
  });

  btnCancelEntry.addEventListener("click", () => {
    entrySection.style.display = "none";
  });

  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
      const cookies = document.cookie.split(";");
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === name + "=") {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  // Save Cards API call
  async function saveCardsAction(destination) {
    if (selections.length === 0) {
      if (saveStatusText) {
        saveStatusText.style.color = "#ef4444";
        saveStatusText.textContent = "هیچ کلمه‌ای در جدول وجود ندارد.";
      }
      showAlert("حداقل یک کلمه باید انتخاب شده باشد.");
      return;
    }

    if (btnSaveCards) btnSaveCards.disabled = true;
    if (btnSaveAndView) btnSaveAndView.disabled = true;

    if (saveStatusText) {
      saveStatusText.style.color = "#818cf8";
      saveStatusText.textContent = "در حال ذخیره واژگان در سیستم SRS...";
    }

    const payload = {
      cards: selections.map((s) => {
        const isNounOrVerb = s.pos === "noun" || s.pos === "verb";
        return {
          card_id: s.cardId || null,
          start: s.start,
          end: s.end,
          pos: s.pos || "noun",
          meaning: (s.meaning || "").trim(),
          lemma: isNounOrVerb ? (s.lemma || s.text.toLowerCase()) : s.text.toLowerCase(),
          example: s.example || null,
        };
      }),
    };

    const csrf = getCookie("csrftoken") || config.csrfToken;

    try {
      const res = await fetch(`/api/texts/${config.textId}/cards/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrf,
        },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (res.ok && data.success) {
        if (saveStatusText) {
          saveStatusText.style.color = "#10b981";
          saveStatusText.textContent = `✓ ${data.count || selections.length} کلمه با موفقیت ثبت شد! در حال انتقال...`;
        }
        setTimeout(() => {
          if (destination === "review") {
            window.location.href = "/review/";
          } else {
            window.location.href = `/texts/${config.textId}/`;
          }
        }, 500);
      } else {
        const errMsg = data.error || "خطایی در ذخیره کارت‌ها رخ داد.";
        if (saveStatusText) {
          saveStatusText.style.color = "#ef4444";
          saveStatusText.textContent = errMsg;
        }
        showAlert(errMsg);
        if (btnSaveCards) btnSaveCards.disabled = false;
        if (btnSaveAndView) btnSaveAndView.disabled = false;
      }
    } catch (err) {
      console.error(err);
      if (saveStatusText) {
        saveStatusText.style.color = "#ef4444";
        saveStatusText.textContent = "خطای ارتباط با سرور. لطفاً دوباره تلاش کنید.";
      }
      showAlert("خطای ارتباط با سرور. لطفاً دوباره تلاش کنید.");
      if (btnSaveCards) btnSaveCards.disabled = false;
      if (btnSaveAndView) btnSaveAndView.disabled = false;
    }
  }

  if (btnSaveCards) {
    btnSaveCards.addEventListener("click", () => saveCardsAction("review"));
  }
  if (btnSaveAndView) {
    btnSaveAndView.addEventListener("click", () => saveCardsAction("view"));
  }

  // Dismiss open example popups on outside click
  document.addEventListener("click", () => {
    document.querySelectorAll(".example-popup-box.show").forEach((p) => p.classList.remove("show"));
  });

  window.saveCardsAction = saveCardsAction;
})();
