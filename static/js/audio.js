/**
 * Nightly Vocab — Audio Pronunciation Player (Step 7)
 * - Plays human audio (preferred accent -> alternate accent).
 * - Falls back to browser SpeechSynthesis (lang: en-GB or en-US, rate 0.9).
 * - Handles browser autoplay policies gracefully.
 * - Supports audio preloading for upcoming cards.
 * - Provides replay() triggered by UI button or 'P' key.
 */
(function (root, factory) {
  if (typeof define === "function" && define.amd) {
    define([], factory);
  } else if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.LexiAudio = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  let currentAudio = null;
  let lastPlayedCard = null;
  const preloadedAudios = new Map();

  /**
   * Plays browser SpeechSynthesis utterance as fallback.
   */
  function playSpeechSynthesis(text, accent) {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) {
      return false;
    }

    try {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = (accent === "uk" || accent === "en-gb") ? "en-GB" : "en-US";
      utterance.rate = 0.9;
      window.speechSynthesis.speak(utterance);
      return true;
    } catch (err) {
      console.warn("SpeechSynthesis error:", err);
      return false;
    }
  }

  /**
   * Preload an audio URL.
   */
  function preload(url) {
    if (!url || typeof Audio === "undefined") return;
    if (preloadedAudios.has(url)) return;

    try {
      const audio = new Audio();
      audio.preload = "auto";
      audio.src = url;
      preloadedAudios.set(url, audio);
      // Limit preloaded cache size
      if (preloadedAudios.size > 20) {
        const firstKey = preloadedAudios.keys().next().value;
        preloadedAudios.delete(firstKey);
      }
    } catch (e) {
      // Ignore preload errors
    }
  }

  /**
   * Attempts to play an audio URL, returns Promise<boolean> (true if played, false if failed).
   */
  function tryPlayUrl(url) {
    return new Promise((resolve) => {
      if (!url) {
        resolve(false);
        return;
      }

      try {
        if (currentAudio) {
          try {
            currentAudio.pause();
            currentAudio.currentTime = 0;
          } catch (e) {
            // Ignore pause errors
          }
        }

        const audio = preloadedAudios.get(url) || new Audio(url);
        currentAudio = audio;

        let resolved = false;
        const timer = setTimeout(() => {
          finish(false);
        }, 700);

        function finish(success) {
          if (!resolved) {
            resolved = true;
            clearTimeout(timer);
            resolve(success);
          }
        }

        audio.onerror = () => finish(false);

        const playPromise = audio.play();
        if (playPromise !== undefined) {
          playPromise
            .then(() => finish(true))
            .catch((err) => {
              // Autoplay restriction or network error
              console.debug("Audio play blocked or failed:", err);
              finish(false);
            });
        } else {
          finish(true);
        }
      } catch (err) {
        resolve(false);
      }
    });
  }

  /**
   * Plays pronunciation for a card or word.
   * Priority: Preferred human audio -> Alternate human audio -> SpeechSynthesis.
   *
   * @param {Object} card - Object containing:
   *   - word: string
   *   - audio_text: string
   *   - accent: 'uk' | 'us' (defaults to 'us')
   *   - audio_url: string | null (preferred)
   *   - audio_url_uk: string | null
   *   - audio_url_us: string | null
   * @param {boolean} isAutoplay - Whether this play is an automatic playback.
   */
  async function playCard(card, isAutoplay = false) {
    if (!card) return;
    lastPlayedCard = card;

    const accent = (card.accent || "us").toLowerCase();
    const prefUrl = accent === "uk"
      ? (card.audio_url_uk || card.audio_url)
      : (card.audio_url_us || card.audio_url);
    const altUrl = accent === "uk"
      ? card.audio_url_us
      : card.audio_url_uk;

    // 1. Try preferred human recording
    if (prefUrl) {
      const ok = await tryPlayUrl(prefUrl);
      if (ok) return;
    }

    // 2. Try alternate human recording
    if (altUrl && altUrl !== prefUrl) {
      const ok = await tryPlayUrl(altUrl);
      if (ok) return;
    }

    // 3. Fallback to SpeechSynthesis
    const textToSpeak = card.word || card.audio_text;
    if (textToSpeak) {
      playSpeechSynthesis(textToSpeak, accent);
    }
  }

  /**
   * Replays the last card.
   */
  function replay() {
    if (lastPlayedCard) {
      playCard(lastPlayedCard, false);
    }
  }

  /**
   * Preloads audio for the next card in queue.
   */
  function preloadNext(nextCard) {
    if (!nextCard) return;
    const accent = (nextCard.accent || "us").toLowerCase();
    const url = accent === "uk"
      ? (nextCard.audio_url_uk || nextCard.audio_url)
      : (nextCard.audio_url_us || nextCard.audio_url);
    if (url) {
      preload(url);
    }
  }

  return {
    playCard,
    replay,
    preload,
    preloadNext,
    playSpeechSynthesis,
    getLastPlayed: () => lastPlayedCard,
  };
});
