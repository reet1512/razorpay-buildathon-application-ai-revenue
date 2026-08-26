(function () {
  var card = document.querySelector("[data-rag-card]");
  if (!card) return;

  var labelEl = document.getElementById("rag-label");
  var corpusEl = document.getElementById("rag-corpus");
  var episodesEl = document.getElementById("rag-episodes");
  var latencyEl = document.getElementById("rag-latency");
  var badgeEl = document.getElementById("rag-badge");
  var POLL_MS = 15000;
  var timer = null;
  var inFlight = false;

  function badgeHtml(online) {
    return online
      ? '<span class="p-badge p-badge--success">Live</span>'
      : '<span class="p-badge p-badge--muted">Offline</span>';
  }

  function apply(data) {
    if (!data || typeof data !== "object") return;
    var online = !!data.rag_online;
    var active = !!data.rag_enabled;
    card.classList.toggle("is-hot", online);
    if (labelEl) labelEl.textContent = data.rag_label || (online ? "RAG ONLINE" : "RAG UNAVAILABLE");
    if (corpusEl) {
      var corpus = data.corpus_completed;
      corpusEl.textContent = corpus != null && corpus > 0 ? String(corpus) : "—";
    }
    if (episodesEl) {
      episodesEl.textContent = active && data.similar_cases != null ? String(data.similar_cases) : "—";
    }
    if (latencyEl) {
      latencyEl.textContent = active && data.retrieval_latency_label
        ? data.retrieval_latency_label
        : "—";
    }
    if (badgeEl) badgeEl.innerHTML = badgeHtml(online);
  }

  function refresh() {
    if (inFlight || document.hidden) return;
    inFlight = true;
    fetch("/ui/rag-status?force=1", { headers: { Accept: "application/json" } })
      .then(function (r) {
        if (!r.ok) throw new Error("rag_status_" + r.status);
        return r.json();
      })
      .then(apply)
      .catch(function () {
        apply({
          rag_online: false,
          rag_enabled: false,
          rag_label: "RAG UNAVAILABLE",
          similar_cases: 0,
          retrieval_latency_label: null,
        });
      })
      .finally(function () {
        inFlight = false;
      });
  }

  function start() {
    refresh();
    if (timer) clearInterval(timer);
    timer = setInterval(refresh, POLL_MS);
  }

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) refresh();
  });

  start();
})();
