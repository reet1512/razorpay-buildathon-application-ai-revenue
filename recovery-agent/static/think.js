(function () {
  var src = document.querySelector("script[data-live]");
  var live = src ? src.getAttribute("data-live") : "0";
  var mode = src ? src.getAttribute("data-mode") || (live === "1" ? "live" : "sim") : "sim";
  var btn = document.getElementById("think-run");
  var resultBox = document.getElementById("win-money");
  var verbEl = document.getElementById("think-verb");
  var whyEl = document.getElementById("think-why");
  var caseEl = document.getElementById("think-case");
  var statusBadge = document.getElementById("think-status-badge");
  var ragBox = document.getElementById("rag-chunks");
  var agentBox = document.getElementById("agent-reasoning");
  var safetyList = document.getElementById("safety-list");
  var es = null;
  var finished = false;
  var chunkCount = 0;
  var gatePassed = 0;
  var gateTotal = 0;
  var lastSource = null;

  var FAIL_LABELS = {
    insufficient_funds: "Insufficient funds",
    issuer_transient: "Issuer transient",
    gateway_timeout: "Gateway timeout",
    card_expired: "Card expired",
    token_invalid: "Token invalid",
    mandate_revoked: "Mandate revoked",
    do_not_honour: "Do not honour",
    risk_fraud: "Risk / fraud",
  };

  var VERB_LABELS = {
    schedule_retry: "Schedule retry",
    send_payment_link: "Send payment link",
    request_mandate_update: "Request mandate update",
    escalate_human: "Escalate to human",
  };

  var STATE_META = {
    waiting: { label: "Waiting", icon: "" },
    running: { label: "Running", icon: "●" },
    success: { label: "Success", icon: "✓" },
    failed: { label: "Failed", icon: "✕" },
    "rules-fallback": { label: "Rules fallback", icon: "⚠" },
  };

  function $(id) {
    return document.getElementById(id);
  }

  function setText(id, text) {
    var el = $(id);
    if (el) el.textContent = text;
  }

  function money(n) {
    if (n == null || n === "") return "—";
    var v = Number(n);
    if (isNaN(v)) return String(n);
    return "₹" + v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function clearPanel(el, placeholder) {
    if (!el) return;
    el.innerHTML = "";
    if (placeholder) {
      var p = document.createElement("p");
      p.className = "p-text-muted p-mb-0 j-window-empty";
      p.textContent = placeholder;
      el.appendChild(p);
    }
  }

  function applySourceBadge(el, source, fallbackReason) {
    if (!el) return;
    el.classList.remove("p-badge--muted", "p-badge--info", "p-badge--ai", "p-badge--fallback", "p-badge--success");
    if (source === "llm") {
      el.textContent = "AI proposed";
      el.className = "p-badge p-badge--ai j-source-badge";
      el.title = "Genuine LLM proposal";
    } else if (source === "rules_fallback") {
      el.textContent = "Rules fallback — AI unreachable";
      el.className = "p-badge p-badge--fallback j-source-badge";
      el.title = fallbackReason || "Taxonomy rules substituted for the LLM";
    } else {
      el.textContent = "Awaiting proposal";
      el.className = "p-badge p-badge--muted j-source-badge";
      el.title = "";
    }
  }

  function applySourceBanner(source, fallbackReason) {
    var banner = $("agent-source-banner");
    if (!banner) return;
    if (source === "llm") {
      banner.hidden = false;
      banner.className = "j-source-banner j-source-banner--ai";
      banner.textContent = "AI proposed — this action came from the LLM";
    } else if (source === "rules_fallback") {
      banner.hidden = false;
      banner.className = "j-source-banner j-source-banner--fallback";
      banner.textContent =
        "Rules fallback — AI unreachable" +
        (fallbackReason ? " · " + fallbackReason : "");
    } else {
      banner.hidden = true;
      banner.textContent = "";
      banner.className = "j-source-banner";
    }
  }

  function resetWindows() {
    chunkCount = 0;
    gatePassed = 0;
    gateTotal = 0;
    lastSource = null;
    clearPanel(ragBox, "Waiting for Inherent retrieval…");
    clearPanel(agentBox, "Waiting for diagnose + propose…");
    if (safetyList) {
      safetyList.innerHTML = "";
      var li = document.createElement("li");
      li.className = "p-text-muted";
      li.textContent = "Gates run after the agent proposes an action.";
      safetyList.appendChild(li);
    }
    setText("rag-count-badge", "0 chunks");
    setText("safety-count-badge", "0 / 0");
    var badge = $("rag-count-badge");
    if (badge) badge.className = "p-badge p-badge--muted";
    applySourceBadge($("agent-source-badge"), null);
    applySourceBanner(null);
    var row = $("think-source-row");
    if (row) row.hidden = true;
    if (resultBox) resultBox.hidden = true;
  }

  function resetSteps() {
    document.querySelectorAll("#think-timeline .p-tl-step").forEach(function (el) {
      setStepState(el, "waiting", "Idle");
    });
  }

  function mapStatus(status, key, detail) {
    var d = (detail || "").toLowerCase();
    if (status === "running") return "running";
    if (status === "blocked") return "failed";
    if (status === "done") {
      if (key === "agent" && (d.indexOf("rules_fallback") >= 0 || d.indexOf("rules fallback") >= 0)) {
        return "rules-fallback";
      }
      return "success";
    }
    return "waiting";
  }

  function setStepState(el, state, detail) {
    if (!el) return;
    var meta = STATE_META[state] || STATE_META.waiting;
    el.className = "p-tl-step is-" + state;
    var chip = el.querySelector(".p-tl-state");
    if (chip) {
      chip.textContent = meta.label;
      chip.setAttribute("data-state", state);
    }
    var sum = el.querySelector(".p-tl-summary");
    var det = el.querySelector(".p-tl-detail");
    if (sum) {
      sum.textContent = detail || meta.label;
      sum.className =
        "p-tl-summary" + (state === "waiting" ? " p-text-muted" : "");
    }
    if (det) {
      if (detail && detail !== meta.label && state !== "waiting") {
        det.hidden = false;
        det.textContent = detail;
      } else {
        det.hidden = true;
        det.textContent = "";
      }
    }
    var num = el.querySelector(".p-tl-dot__num");
    var icon = el.querySelector(".p-tl-dot__icon");
    if (num && icon) {
      if (meta.icon && state !== "waiting" && state !== "running") {
        num.hidden = true;
        icon.hidden = false;
        icon.textContent = meta.icon;
      } else {
        num.hidden = false;
        icon.hidden = true;
        icon.textContent = "";
      }
    }
  }

  function setStep(key, status, detail) {
    var el = document.querySelector('#think-timeline [data-step="' + key + '"]');
    if (!el) return;
    var state = mapStatus(status, key, detail);
    if (key === "agent" && lastSource === "rules_fallback" && status === "done") {
      state = "rules-fallback";
    }
    setStepState(el, state, detail);
  }

  function onRagMeta(data) {
    var empty = ragBox && ragBox.querySelector(".j-window-empty");
    if (empty) empty.remove();
    var n = data.similar_cases != null ? data.similar_cases : data.chunk_count || 0;
    var badge = $("rag-count-badge");
    if (badge) {
      badge.textContent = n + " episodes";
      badge.className = "p-badge " + (n > 0 ? "p-badge--success" : "p-badge--muted");
    }
    if (ragBox && data.status_label && n === 0) {
      var p = document.createElement("p");
      p.className = "p-text-muted";
      p.textContent = data.status_label + (data.query ? " · " + data.query : "");
      ragBox.appendChild(p);
    }
  }

  function onRagChunk(data) {
    if (!ragBox) return;
    var empty = ragBox.querySelector(".j-window-empty");
    if (empty) empty.remove();
    chunkCount += 1;
    setText("rag-count-badge", chunkCount + " chunks");
    var badge = $("rag-count-badge");
    if (badge) badge.className = "p-badge p-badge--success";

    var row = document.createElement("article");
    row.className = "j-chunk";
    var score =
      data.score != null && data.score !== ""
        ? Number(data.score).toFixed(2)
        : "—";
    var title = data.document_name || "episode";
    var meta = [];
    if (data.failure_reason) meta.push(String(data.failure_reason).replace(/_/g, " "));
    if (data.action) meta.push(String(data.action).replace(/_/g, " "));
    if (data.outcome) meta.push(String(data.outcome));
    row.innerHTML =
      '<div class="j-chunk-top"><strong>' +
      escapeHtml(title) +
      '</strong><span class="j-chunk-score">' +
      score +
      "</span></div>" +
      (meta.length ? '<p class="j-chunk-meta">' + escapeHtml(meta.join(" · ")) + "</p>" : "");
    ragBox.appendChild(row);
    ragBox.scrollTop = ragBox.scrollHeight;
  }

  function onReasoning(data) {
    if (!agentBox) return;
    agentBox.innerHTML = "";
    var source = data.source || (data.used_llm ? "llm" : "rules_fallback");
    lastSource = source;
    applySourceBadge($("agent-source-badge"), source, data.fallback_reason);
    applySourceBanner(source, data.fallback_reason);

    if (data.summary) {
      var s = document.createElement("p");
      s.className = "j-reason-summary";
      s.textContent = data.summary;
      agentBox.appendChild(s);
    }
    if (data.rationale) {
      var r = document.createElement("p");
      r.className = "j-reason-body";
      r.textContent = data.rationale;
      agentBox.appendChild(r);
    }
    var meta = document.createElement("p");
    meta.className = "p-text-muted";
    var conf =
      data.confidence != null ? Math.round(Number(data.confidence) * 100) + "%" : "—";
    meta.textContent =
      (data.likely_class || "").replace(/_/g, " ") +
      " · " +
      (VERB_LABELS[data.verb] || data.verb || "") +
      " · confidence " +
      conf;
    agentBox.appendChild(meta);
    agentBox.scrollTop = agentBox.scrollHeight;

    var agentStep = document.querySelector('#think-timeline [data-step="agent"]');
    if (agentStep && agentStep.classList.contains("is-success")) {
      setStepState(
        agentStep,
        source === "rules_fallback" ? "rules-fallback" : "success",
        agentStep.querySelector(".p-tl-summary")
          ? agentStep.querySelector(".p-tl-summary").textContent
          : undefined
      );
    }
  }

  function onGate(data) {
    if (!safetyList) return;
    if (gateTotal === 0) safetyList.innerHTML = "";
    gateTotal += 1;
    if (data.passed) gatePassed += 1;
    setText("safety-count-badge", gatePassed + " / " + gateTotal);
    var sb = $("safety-count-badge");
    if (sb) {
      sb.className =
        "p-badge " +
        (gatePassed === gateTotal ? "p-badge--success" : data.passed ? "p-badge--info" : "p-badge--danger");
    }
    var li = document.createElement("li");
    li.className = data.passed ? "is-pass" : "is-block";
    li.innerHTML =
      "<span>" +
      (data.passed ? "✓" : "✕") +
      "</span> " +
      escapeHtml(data.label || data.gate || "gate") +
      (data.reason_code
        ? ' <span class="j-gate-code">' + escapeHtml(data.reason_code) + "</span>"
        : "");
    safetyList.appendChild(li);
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fillResult(r) {
    var verb = r.verb || "done";
    var verbLabel = VERB_LABELS[verb] || verb.replace(/_/g, " ");
    if (verb === "schedule_retry" && r.day_offset != null && Number(r.day_offset) > 0) {
      verbLabel = "Retry after " + r.day_offset + " day(s)";
    }
    if (verbEl) verbEl.textContent = verbLabel;
    if (whyEl) whyEl.textContent = r.rationale || r.summary || "";

    var source = r.source || (r.used_llm ? "llm" : "rules_fallback");
    lastSource = source;
    applySourceBadge($("agent-source-badge"), source, r.fallback_reason);
    applySourceBanner(source, r.fallback_reason);

    var sourceRow = $("think-source-row");
    var sourceBadge = $("think-source-badge");
    if (sourceRow && sourceBadge) {
      sourceRow.hidden = false;
      applySourceBadge(sourceBadge, source, r.fallback_reason);
    }

    setText("think-case-id", r.case_id || "—");
    setText("think-at-risk", money(r.amount_inr != null ? r.amount_inr : r.at_risk_inr));
    setText(
      "think-failure",
      FAIL_LABELS[r.failure_reason] || FAIL_LABELS[r.failure_class] || r.failure_class || r.failure_reason || "—"
    );
    setText(
      "think-confidence",
      r.confidence_pct != null
        ? r.confidence_pct + "%"
        : r.confidence != null
          ? Math.round(Number(r.confidence) * 100) + "%"
          : "—"
    );
    setText("think-recovery", r.recovery_label || money(r.recovered_inr) || "—");
    setText("think-model", source === "llm" ? "llm" : "rules_fallback");

    var plinkRow = $("think-plink-row");
    var plinkDt = plinkRow ? plinkRow.querySelector("dt") : null;
    if (r.external_id) {
      setText("think-plink", r.external_id);
      if (plinkRow) plinkRow.hidden = false;
      if (plinkDt) {
        plinkDt.textContent = r.demo_link_not_gated
          ? "Demo Payment Link (not gated)"
          : "Payment Link";
      }
    } else if (plinkRow) {
      plinkRow.hidden = true;
    }

    if (statusBadge) {
      statusBadge.className = "p-badge";
      if (r.blocked_by) {
        statusBadge.classList.add("p-badge--danger");
        statusBadge.textContent = "Blocked";
      } else if (r.live && r.external_id) {
        statusBadge.classList.add("p-badge--warning");
        statusBadge.textContent = "Link live";
      } else if (r.executed) {
        statusBadge.classList.add("p-badge--success");
        statusBadge.textContent = "Executed";
      } else {
        statusBadge.classList.add("p-badge--info");
        statusBadge.textContent = "Proposed";
      }
    }

    if (r.safety_checks && r.safety_checks.length && gateTotal === 0) {
      r.safety_checks.forEach(function (c) {
        onGate({
          gate: c.gate,
          label: c.label,
          passed: c.passed || c.status === "passed",
          reason_code: c.reason_code,
        });
      });
    }

    if (caseEl && r.case_id) {
      caseEl.href = "/ui/cases/" + r.case_id;
      caseEl.hidden = false;
    }
    if (resultBox) resultBox.hidden = false;

    var agentStep = document.querySelector('#think-timeline [data-step="agent"]');
    if (agentStep && (agentStep.classList.contains("is-success") || agentStep.classList.contains("is-rules-fallback"))) {
      var sumEl = agentStep.querySelector(".p-tl-summary");
      setStepState(
        agentStep,
        source === "rules_fallback" ? "rules-fallback" : "success",
        sumEl ? sumEl.textContent : undefined
      );
    }
  }

  function stop() {
    if (es) {
      es.close();
      es = null;
    }
    if (btn) btn.disabled = false;
  }

  function run() {
    var sel = document.getElementById("demo-reason");
    var reason = sel ? sel.value : "insufficient_funds";
    resetSteps();
    resetWindows();
    if (btn) btn.disabled = true;
    finished = false;
    var url =
      "/ui/demo/think?raw_error_reason=" +
      encodeURIComponent(reason) +
      "&amount_paise=49900&live=" +
      encodeURIComponent(live);
    es = new EventSource(url);

    es.addEventListener("step", function (ev) {
      var data = {};
      try {
        data = JSON.parse(ev.data);
      } catch (e) {
        return;
      }
      setStep(data.key, data.status, data.detail);
      if (data.key === "agent" && data.status === "running") {
        var ab = $("agent-source-badge");
        if (ab) {
          ab.textContent = "Thinking…";
          ab.className = "p-badge p-badge--info j-source-badge";
        }
        applySourceBanner(null);
        if (agentBox) {
          clearPanel(agentBox, "Diagnosing failure and proposing an action…");
        }
      }
      if (data.key === "memory" && data.status === "running" && ragBox) {
        clearPanel(ragBox, "Searching Inherent for similar recoveries…");
      }
    });

    es.addEventListener("rag_meta", function (ev) {
      try {
        onRagMeta(JSON.parse(ev.data));
      } catch (e) {}
    });
    es.addEventListener("rag_chunk", function (ev) {
      try {
        onRagChunk(JSON.parse(ev.data));
      } catch (e) {}
    });
    es.addEventListener("reasoning", function (ev) {
      try {
        onReasoning(JSON.parse(ev.data));
      } catch (e) {}
    });
    es.addEventListener("gate", function (ev) {
      try {
        onGate(JSON.parse(ev.data));
      } catch (e) {}
    });

    es.addEventListener("done", function (ev) {
      finished = true;
      var data = {};
      try {
        data = JSON.parse(ev.data);
      } catch (e) {
        stop();
        return;
      }
      fillResult(data.result || {});
      stop();
    });
    es.addEventListener("fail", function (ev) {
      var msg = "Pipeline failed";
      if (ev.data) {
        try {
          msg = JSON.parse(ev.data).message || msg;
        } catch (e) {}
      }
      setStep("agent", "blocked", msg);
      if (agentBox) {
        agentBox.innerHTML = "";
        var p = document.createElement("p");
        p.className = "p-text-muted";
        p.style.color = "var(--p-danger)";
        p.textContent = msg;
        agentBox.appendChild(p);
      }
      stop();
    });
    es.onerror = function () {
      if (!finished && agentBox) {
        var p = document.createElement("p");
        p.className = "p-text-muted";
        p.textContent = "Connection lost";
        agentBox.appendChild(p);
      }
      stop();
    };
  }

  if (btn) btn.addEventListener("click", run);
})();
