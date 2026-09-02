const $ = (s) => document.querySelector(s);

const state = {
  cases: [],
  selectedCase: null,
  csrf: null,
};

const decisionClass = (d) => {
  if (!d) return "";
  if (d.includes("APPROVE")) return "approve";
  if (d.includes("HOLD")) return "hold";
  if (d.includes("ESCALATE")) return "escalate";
  if (d.includes("DENY")) return "deny";
  return "";
};

const decisionShort = (d) => {
  if (!d) return "UNKNOWN";
  if (d === "APPROVE REFUND") return "APPROVE";
  if (d === "HOLD REFUND") return "HOLD";
  if (d === "ESCALATE TO HUMAN REVIEW") return "REVIEW";
  if (d === "DENY REFUND") return "DENY";
  return d;
};

const escapeHtml = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

const fmtPercent = (value) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return "0%";
  return `${Math.round(n * 100)}%`;
};

const fmtMoney = (value) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return "₹0";
  return `₹${n.toLocaleString("en-IN")}`;
};

const fmtDate = (value) => {
  if (!value) return "Unknown";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString("en-IN");
};

async function api(url, options = {}) {
  const opts = {
    credentials: "same-origin",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  };

  if (state.csrf) {
    opts.headers["X-CSRF-Token"] = state.csrf;
  }

  const response = await fetch(url, opts);

  let data = {};
  try {
    data = await response.json();
  } catch (_) {}

  if (!response.ok) {
    throw new Error(data.error || data.message || `Request failed (${response.status})`);
  }

  return data;
}

function showToast(message, type = "info") {
  let toast = document.querySelector("#toast");

  if (!toast) {
    toast = document.createElement("div");
    toast.id = "toast";
    document.body.appendChild(toast);
  }

  toast.className = `toast ${type}`;
  toast.textContent = message;

  requestAnimationFrame(() => {
    toast.classList.add("show");
  });

  setTimeout(() => {
    toast.classList.remove("show");
  }, 3000);
}

async function loadSession() {
  try {
    const data = await api("/api/session");
    state.csrf = data.csrf || data.csrf_token || null;
  } catch (_) {
    // Session endpoint may not exist in older builds.
  }
}

async function loadCases() {
  const data = await api("/api/cases");

  state.cases = Array.isArray(data)
    ? data
    : data.cases || data.items || [];

  renderCases();
}

function renderCases() {
  const container =
    $("#case-list") ||
    $("#cases-list") ||
    $("#cases");

  if (!container) return;

  if (!state.cases.length) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-title">No cases found</div>
        <div class="empty-subtitle">
          Verified return cases will appear here.
        </div>
      </div>
    `;
    return;
  }

  container.innerHTML = state.cases
    .map((c) => {
      const automatedDecision =
        c.decision ||
        c.automated_decision ||
        "UNKNOWN";

      const finalDecision =
        c.final_decision ||
        "";

      return `
        <button
          class="case-row"
          type="button"
          onclick="openDetail('${escapeHtml(c.return_id)}')"
        >
          <div class="case-main">
            <div class="case-id">
              ${escapeHtml(c.return_id)}
            </div>

            <div class="case-meta">
              ${escapeHtml(c.merchant_id || "Unknown merchant")}
              · ${fmtMoney(c.refund_amount)}
            </div>
          </div>

          <div class="case-risk">
            ${fmtPercent(c.risk_score)}
          </div>

          <div class="case-decision ${decisionClass(
            finalDecision || automatedDecision
          )}">
            ${escapeHtml(
              decisionShort(finalDecision || automatedDecision)
            )}
          </div>
        </button>
      `;
    })
    .join("");
}

function ensureHumanReviewStyles() {
  if (document.querySelector("#human-review-styles")) return;

  const style = document.createElement("style");
  style.id = "human-review-styles";

  style.textContent = `
    .human-review-panel {
      margin: 18px 0 22px;
      padding: 22px;
      border: 1px solid rgba(255,255,255,.09);
      border-radius: 18px;
      background:
        linear-gradient(
          135deg,
          rgba(255,255,255,.055),
          rgba(255,255,255,.025)
        );
    }

    .human-review-header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      margin-bottom: 18px;
    }

    .human-review-eyebrow {
      font-size: 11px;
      font-weight: 800;
      letter-spacing: .12em;
      text-transform: uppercase;
      opacity: .62;
      margin-bottom: 7px;
    }

    .human-review-title {
      font-size: 18px;
      font-weight: 750;
      margin-bottom: 5px;
    }

    .human-review-subtitle {
      font-size: 13px;
      line-height: 1.55;
      opacity: .65;
      max-width: 680px;
    }

    .human-review-badge {
      padding: 7px 10px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 800;
      letter-spacing: .08em;
      white-space: nowrap;
      background: rgba(255,255,255,.07);
    }

    .human-review-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 18px;
    }

    .human-review-stat {
      padding: 13px 14px;
      border-radius: 13px;
      background: rgba(0,0,0,.16);
      border: 1px solid rgba(255,255,255,.06);
    }

    .human-review-stat-label {
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: .08em;
      opacity: .52;
      margin-bottom: 5px;
    }

    .human-review-stat-value {
      font-size: 14px;
      font-weight: 700;
    }

    .human-review-options {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 15px;
    }

    .human-decision-btn {
      border: 1px solid rgba(255,255,255,.10);
      border-radius: 14px;
      padding: 15px 16px;
      cursor: pointer;
      background: rgba(255,255,255,.035);
      color: inherit;
      text-align: left;
      transition:
        transform .15s ease,
        border-color .15s ease,
        background .15s ease;
    }

    .human-decision-btn:hover {
      transform: translateY(-1px);
      background: rgba(255,255,255,.065);
    }

    .human-decision-btn.selected {
      border-color: rgba(255,255,255,.34);
      background: rgba(255,255,255,.10);
    }

    .human-decision-btn.approve.selected {
      border-color: rgba(80,220,145,.65);
    }

    .human-decision-btn.deny.selected {
      border-color: rgba(255,100,100,.65);
    }

    .human-decision-label {
      font-size: 13px;
      font-weight: 800;
      margin-bottom: 4px;
    }

    .human-decision-description {
      font-size: 11px;
      line-height: 1.45;
      opacity: .58;
    }

    .human-review-rationale {
      width: 100%;
      min-height: 92px;
      resize: vertical;
      box-sizing: border-box;
      border-radius: 12px;
      border: 1px solid rgba(255,255,255,.10);
      background: rgba(0,0,0,.18);
      color: inherit;
      padding: 13px;
      outline: none;
      font: inherit;
      font-size: 13px;
    }

    .human-review-rationale:focus {
      border-color: rgba(255,255,255,.28);
    }

    .human-review-footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      margin-top: 12px;
    }

    .human-review-note {
      font-size: 11px;
      opacity: .5;
      line-height: 1.45;
    }

    .finalize-human-decision {
      border: 0;
      border-radius: 11px;
      padding: 11px 17px;
      font-weight: 800;
      cursor: pointer;
      color: white;
      background: #ffffff;
      color: #111;
      transition: opacity .15s ease, transform .15s ease;
    }

    .finalize-human-decision:hover:not(:disabled) {
      transform: translateY(-1px);
    }

    .finalize-human-decision:disabled {
      opacity: .35;
      cursor: not-allowed;
    }

    .human-finalized {
      border-color: rgba(80,220,145,.22);
      background: rgba(80,220,145,.045);
    }

    .human-finalized-decision {
      font-size: 22px;
      font-weight: 850;
      margin: 8px 0;
    }

    .human-finalized-meta {
      font-size: 12px;
      line-height: 1.6;
      opacity: .65;
    }

    .human-finalized-reason {
      margin-top: 14px;
      padding: 12px 14px;
      border-radius: 11px;
      background: rgba(0,0,0,.15);
      font-size: 12px;
      line-height: 1.55;
    }

    @media (max-width: 700px) {
      .human-review-grid,
      .human-review-options {
        grid-template-columns: 1fr;
      }

      .human-review-header,
      .human-review-footer {
        flex-direction: column;
        align-items: stretch;
      }

      .finalize-human-decision {
        width: 100%;
      }
    }
  `;

  document.head.appendChild(style);
}

function humanReviewMarkup(c, a) {
  const humanDecision =
    a.human_decision ||
    c.human_decision ||
    null;

  const automatedDecision =
    a.decision ||
    c.decision ||
    "UNKNOWN";

  /*
   * If a human has already finalized the case,
   * show the recorded final resolution instead
   * of showing the decision buttons again.
   */
  if (humanDecision) {
    return `
      <section class="human-review-panel human-finalized">
        <div class="human-review-header">
          <div>
            <div class="human-review-eyebrow">
              Final Resolution
            </div>

            <div class="human-review-title">
              Human decision recorded
            </div>

            <div class="human-review-subtitle">
              Reclaim Sentinel routed this case for human review.
              The financial outcome below was finalized by the reviewer.
            </div>
          </div>

          <div class="human-review-badge">
            FINALIZED
          </div>
        </div>

        <div class="human-finalized-decision">
          ${escapeHtml(humanDecision.final_decision)}
        </div>

        <div class="human-finalized-meta">
          Reviewer:
          <strong>${escapeHtml(humanDecision.reviewer)}</strong>
          <br>
          Finalized:
          <strong>${escapeHtml(fmtDate(humanDecision.created_at))}</strong>
          <br>
          Automated verdict:
          <strong>${escapeHtml(humanDecision.automated_decision)}</strong>
          <br>
          Automated risk:
          <strong>${fmtPercent(humanDecision.automated_risk_score)}</strong>
        </div>

        <div class="human-finalized-reason">
          <strong>Reviewer rationale</strong><br>
          ${escapeHtml(humanDecision.reason)}
        </div>
      </section>
    `;
  }

  /*
   * Only HOLD and ESCALATE require the human
   * to make the final financial decision.
   */
  if (
    automatedDecision !== "HOLD REFUND" &&
    automatedDecision !== "ESCALATE TO HUMAN REVIEW"
  ) {
    return "";
  }

  return `
    <section class="human-review-panel">
      <div class="human-review-header">
        <div>
          <div class="human-review-eyebrow">
            Human Review Required
          </div>

          <div class="human-review-title">
            Make the final refund decision
          </div>

          <div class="human-review-subtitle">
            Reclaim Sentinel has routed this case to human review.
            Review the automated evidence, then decide whether the
            refund should ultimately be approved or denied.
          </div>
        </div>

        <div class="human-review-badge">
          ${escapeHtml(decisionShort(automatedDecision))}
        </div>
      </div>

      <div class="human-review-grid">
        <div class="human-review-stat">
          <div class="human-review-stat-label">
            Automated verdict
          </div>

          <div class="human-review-stat-value">
            ${escapeHtml(automatedDecision)}
          </div>
        </div>

        <div class="human-review-stat">
          <div class="human-review-stat-label">
            Automated risk
          </div>

          <div class="human-review-stat-value">
            ${fmtPercent(
              a.risk_score ??
              c.risk_score ??
              0
            )}
          </div>
        </div>

        <div class="human-review-stat">
          <div class="human-review-stat-label">
            Refund value
          </div>

          <div class="human-review-stat-value">
            ${fmtMoney(
              a.refund_amount ??
              c.refund_amount ??
              0
            )}
          </div>
        </div>
      </div>

      <div class="human-review-options">
        <button
          type="button"
          class="human-decision-btn approve"
          data-human-decision="APPROVE REFUND"
        >
          <div class="human-decision-label">
            APPROVE REFUND
          </div>

          <div class="human-decision-description">
            Release the refund and close the case.
          </div>
        </button>

        <button
          type="button"
          class="human-decision-btn deny"
          data-human-decision="DENY REFUND"
        >
          <div class="human-decision-label">
            DENY REFUND
          </div>

          <div class="human-decision-description">
            Reject the refund based on the reviewed evidence.
          </div>
        </button>
      </div>

      <textarea
        class="human-review-rationale"
        id="human-review-rationale"
        placeholder="Enter reviewer rationale. Explain why the final refund decision was made..."
      ></textarea>

      <div class="human-review-footer">
        <div class="human-review-note">
          A reviewer rationale is required and will be written
          to the case audit trail.
        </div>

        <button
          type="button"
          class="finalize-human-decision"
          id="finalize-human-decision"
          disabled
        >
          FINALIZE DECISION
        </button>
      </div>
    </section>
  `;
}

async function finalizeHumanDecision(returnId, decision) {
  const rationale =
    $("#human-review-rationale")?.value.trim() || "";

  if (rationale.length < 5) {
    showToast(
      "Please provide a reviewer rationale.",
      "error"
    );
    return;
  }

  if (rationale.length > 500) {
    showToast(
      "Reviewer rationale must be 500 characters or less.",
      "error"
    );
    return;
  }

  const button = $("#finalize-human-decision");

  if (button) {
    button.disabled = true;
    button.textContent = "FINALIZING...";
  }

  try {
    await api(
      `/api/cases/${encodeURIComponent(returnId)}/human-decision`,
      {
        method: "POST",
        body: JSON.stringify({
          decision,
          reason: rationale,
        }),
      }
    );

    showToast(
      `Case finalized: ${decision}`,
      "success"
    );

    await loadCases();
    await openDetail(returnId);
  } catch (error) {
    if (button) {
      button.disabled = false;
      button.textContent = "FINALIZE DECISION";
    }

    showToast(
      error.message || "Unable to finalize decision.",
      "error"
    );
  }
}

async function openDetail(returnId) {
  ensureHumanReviewStyles();

  const container = $("#detail-content");

  if (!container) return;

  container.innerHTML = `
    <div class="loading-state">
      Loading case...
    </div>
  `;

  try {
    const response = await api(
      `/api/cases/${encodeURIComponent(returnId)}`
    );

    const c =
      response.case ||
      response;

    const a =
      response.analysis ||
      response;

    state.selectedCase = c;

    const automatedDecision =
      a.decision ||
      c.decision ||
      "UNKNOWN";

    const finalDecision =
      a.final_decision ||
      c.final_decision ||
      "";

    const humanDecision =
      a.human_decision ||
      c.human_decision ||
      null;

    const riskScore =
      a.risk_score ??
      c.risk_score ??
      0;

    const modelScore =
      a.model_score ??
      c.model_score ??
      0;

    const rulesScore =
      a.rules_score ??
      c.rules_score ??
      0;

    const graphScore =
      a.graph_score ??
      c.graph_score ??
      0;

    const evidence =
      a.evidence ||
      c.evidence ||
      [];

    const failures =
      a.failures ||
      c.failures ||
      [];

    const flags =
      a.flags ||
      c.flags ||
      [];

    const graph =
      a.graph ||
      c.graph ||
      {};

    const audit =
      response.audit ||
      a.audit ||
      c.audit ||
      [];

    const humanMarkup =
      humanReviewMarkup(c, {
        ...a,
        human_decision: humanDecision,
        final_decision: finalDecision,
        decision: automatedDecision,
      });

    container.innerHTML = `
      ${humanMarkup}

      <div class="detail-grid">

        <section class="detail-card verdict-card">
          <div class="detail-label">
            AUTOMATED VERDICT
          </div>

          <div class="verdict-value ${decisionClass(
            automatedDecision
          )}">
            ${escapeHtml(automatedDecision)}
          </div>

          ${
            finalDecision
              ? `
                <div class="detail-label" style="margin-top:14px;">
                  FINAL OUTCOME
                </div>

                <div class="verdict-value ${decisionClass(
                  finalDecision
                )}">
                  ${escapeHtml(finalDecision)}
                </div>
              `
              : ""
          }
        </section>

        <section class="detail-card">
          <div class="detail-label">
            REFUND AMOUNT
          </div>

          <div class="detail-big">
            ${fmtMoney(c.refund_amount)}
          </div>

          <div class="detail-label" style="margin-top:12px;">
            RETURN ID
          </div>

          <div class="detail-value">
            ${escapeHtml(c.return_id)}
          </div>
        </section>

        <section class="detail-card">
          <div class="detail-label">
            RISK SCORE
          </div>

          <div class="detail-big">
            ${fmtPercent(riskScore)}
          </div>

          <div class="risk-breakdown">
            <div>
              <span>ML</span>
              <strong>${fmtPercent(modelScore)}</strong>
            </div>

            <div>
              <span>Rules</span>
              <strong>${fmtPercent(rulesScore)}</strong>
            </div>

            <div>
              <span>Graph</span>
              <strong>${fmtPercent(graphScore)}</strong>
            </div>
          </div>
        </section>

        <section class="detail-card">
          <div class="detail-label">
            MERCHANT
          </div>

          <div class="detail-big">
            ${escapeHtml(c.merchant_id || "Unknown")}
          </div>

          <div class="detail-label" style="margin-top:12px;">
            CUSTOMER
          </div>

          <div class="detail-value">
            ${escapeHtml(c.customer_id || "Unknown")}
          </div>
        </section>

      </div>

      <section class="detail-card evidence-section">
        <div class="section-heading">
          <div>
            <div class="detail-label">
              DETERMINISTIC EVIDENCE CHECKS
            </div>

            <div class="section-title">
              Return integrity signals
            </div>
          </div>
        </div>

        <div class="evidence-list">
          ${
            Array.isArray(evidence) && evidence.length
              ? evidence
                  .map((item) => {
                    const status =
                      item.status ||
                      item.result ||
                      "UNKNOWN";

                    return `
                      <div class="evidence-row">
                        <div>
                          <div class="evidence-name">
                            ${escapeHtml(
                              item.rule ||
                              item.name ||
                              item.code ||
                              "Evidence check"
                            )}
                          </div>

                          <div class="evidence-description">
                            ${escapeHtml(
                              item.description ||
                              item.message ||
                              ""
                            )}
                          </div>
                        </div>

                        <div class="evidence-status">
                          ${escapeHtml(status)}
                        </div>
                      </div>
                    `;
                  })
                  .join("")
              : `
                <div class="empty-state">
                  No evidence details available.
                </div>
              `
          }
        </div>
      </section>

      <section class="detail-card">
        <div class="section-heading">
          <div>
            <div class="detail-label">
              INVESTIGATOR SUMMARY
            </div>

            <div class="section-title">
              Why Sentinel reached this verdict
            </div>
          </div>
        </div>

        <div class="summary-copy">
          ${escapeHtml(
            a.investigator_summary ||
            c.investigator_summary ||
            "No investigator summary available."
          )}
        </div>
      </section>

      <section class="detail-card">
        <div class="section-heading">
          <div>
            <div class="detail-label">
              FAILURE SIGNALS
            </div>

            <div class="section-title">
              Evidence requiring attention
            </div>
          </div>
        </div>

        <div class="signal-list">
          ${
            Array.isArray(failures) && failures.length
              ? failures
                  .map(
                    (item) => `
                      <div class="signal-row failure">
                        ${escapeHtml(
                          typeof item === "string"
                            ? item
                            : item.message ||
                              item.rule ||
                              JSON.stringify(item)
                        )}
                      </div>
                    `
                  )
                  .join("")
              : `
                <div class="signal-row">
                  No hard failures detected.
                </div>
              `
          }

          ${
            Array.isArray(flags) && flags.length
              ? flags
                  .map(
                    (item) => `
                      <div class="signal-row flag">
                        ${escapeHtml(
                          typeof item === "string"
                            ? item
                            : item.message ||
                              item.rule ||
                              JSON.stringify(item)
                        )}
                      </div>
                    `
                  )
                  .join("")
              : ""
          }
        </div>
      </section>

      <section class="detail-card">
        <div class="section-heading">
          <div>
            <div class="detail-label">
              COORDINATED-RETURN CONTEXT
            </div>

            <div class="section-title">
              Linked activity
            </div>
          </div>
        </div>

        <div class="coordination-copy">
          ${
            graph.summary ||
            graph.message ||
            a.coordination_summary ||
            "No coordinated-return pattern detected."
          }
        </div>

        ${
          graph.linked_cases?.length
            ? `
              <div class="linked-case-list">
                ${graph.linked_cases
                  .map(
                    (id) => `
                      <div class="linked-case">
                        ${escapeHtml(id)}
                      </div>
                    `
                  )
                  .join("")}
              </div>
            `
            : ""
        }
      </section>

      <section class="detail-card audit-section">
        <div class="section-heading">
          <div>
            <div class="detail-label">
              AUDIT TRAIL
            </div>

            <div class="section-title">
              Decision lineage
            </div>
          </div>
        </div>

        <div class="audit-list">
          ${
            Array.isArray(audit) && audit.length
              ? audit
                  .map(
                    (event) => `
                      <div class="audit-row">
                        <div class="audit-dot"></div>

                        <div class="audit-content">
                          <div class="audit-event">
                            ${escapeHtml(
                              event.event ||
                              event.type ||
                              "event"
                            )}
                          </div>

                          <div class="audit-time">
                            ${escapeHtml(
                              fmtDate(
                                event.created_at ||
                                event.timestamp
                              )
                            )}
                          </div>
                        </div>
                      </div>
                    `
                  )
                  .join("")
              : `
                <div class="empty-state">
                  No audit events available.
                </div>
              `
          }
        </div>
      </section>
    `;

    /*
     * Human decision interaction
     */
    const decisionButtons =
      container.querySelectorAll(
        "[data-human-decision]"
      );

    const finalizeButton =
      container.querySelector(
        "#finalize-human-decision"
      );

    let selectedDecision = null;

    decisionButtons.forEach((button) => {
      button.addEventListener("click", () => {
        selectedDecision =
          button.dataset.humanDecision;

        decisionButtons.forEach((b) =>
          b.classList.remove("selected")
        );

        button.classList.add("selected");

        if (finalizeButton) {
          finalizeButton.disabled = false;
        }
      });
    });

    if (finalizeButton) {
      finalizeButton.addEventListener("click", () => {
        if (!selectedDecision) {
          showToast(
            "Select a final decision first.",
            "error"
          );
          return;
        }

        finalizeHumanDecision(
          c.return_id,
          selectedDecision
        );
      });
    }

  } catch (error) {
    container.innerHTML = `
      <div class="error-state">
        <div class="error-title">
          Unable to load case
        </div>

        <div class="error-message">
          ${escapeHtml(error.message)}
        </div>

        <button
          type="button"
          onclick="openDetail('${escapeHtml(returnId)}')"
        >
          RETRY
        </button>
      </div>
    `;

    showToast(
      error.message || "Unable to load case.",
      "error"
    );
  }
}

async function initDashboard() {
  try {
    await loadSession();
    await loadCases();
  } catch (error) {
    console.error(error);

    showToast(
      error.message || "Unable to load dashboard.",
      "error"
    );
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initDashboard();
});

/*
 * Expose functions for inline HTML handlers.
 */
window.openDetail = openDetail;
window.loadCases = loadCases;
window.finalizeHumanDecision = finalizeHumanDecision;