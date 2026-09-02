const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const money = (n) => "₹" + Number(n || 0).toLocaleString("en-IN");
const date = (v) => new Date(v).toLocaleDateString("en-IN", {day:"2-digit", month:"short"});
const decisionClass = (d) => d.includes("HOLD") ? "verdict-hold" : d.includes("ESCALATE") ? "verdict-escalate" : "verdict-approve";
const decisionShort = (d) => d.includes("HOLD") ? "HOLD REFUND" : d.includes("ESCALATE") ? "HUMAN REVIEW" : "APPROVE";
const riskClass = (n) => n >= .65 ? "risk-high" : n >= .35 ? "risk-mid" : "risk-low";
let overviewData, casesData;
let csrfToken = null;

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (csrfToken) {
    headers["X-CSRF-Token"] = csrfToken;
  }
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) { showLogin(); throw new Error("Authentication required"); }
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "Request failed");
  return body;
}
function showLogin(){ $("#login-screen").classList.remove("hidden"); $("#app-shell").classList.add("hidden"); }
function showApp(){ $("#login-screen").classList.add("hidden"); $("#app-shell").classList.remove("hidden"); }
function toast(message){ const el=$("#toast"); el.textContent=message; el.classList.add("show"); setTimeout(()=>el.classList.remove("show"),2800); }
function caseRow(c, compact=false) {
  return `<tr data-case="${c.return_id}"><td><div class="case-cell"><strong>${c.return_id}</strong><small>${c.customer_id}</small></div></td><td>${c.merchant_id}</td><td>${c.return_reason}</td><td class="amount">${money(c.refund_amount)}</td><td class="risk-cell ${riskClass(c.risk_score)}">${c.risk_percent}%</td><td><span class="verdict ${decisionClass(c.decision)}">${decisionShort(c.decision)}</span></td><td>${date(c.return_request_timestamp)}</td><td>→</td></tr>`;
}
function bindCaseRows(){ $$("tr[data-case]").forEach(row=>row.addEventListener("click",()=>openDetail(row.dataset.case))); }
async function loadOverview(){
  overviewData = await api("/api/overview");
  $("#metric-cases").textContent = overviewData.total_cases.toLocaleString("en-IN");
  $("#metric-value").textContent = money(overviewData.protected_value);
  $("#metric-review").textContent = overviewData.pending_review.toLocaleString("en-IN");
  $("#nav-case-count").textContent = (overviewData.total_cases/1000).toFixed(1)+"K";
  const d=overviewData.decisions, total=overviewData.reviewed_cases;
  const approve = d["APPROVE REFUND"] || 0;
  const hold = d["HOLD REFUND"] || 0;
  const escalate = d["ESCALATE TO HUMAN REVIEW"] || 0;
  
  $("#donut-total").textContent = total.toLocaleString("en-IN");
  $("#legend-approve").textContent = approve.toLocaleString("en-IN");
  $("#legend-hold").textContent = hold.toLocaleString("en-IN");
  $("#legend-escalate").textContent = escalate.toLocaleString("en-IN");
  
  if (total > 0) {
    const holdPct = (hold / total) * 100;
    const escPct = holdPct + (escalate / total) * 100;
    $(".donut").style.background = `conic-gradient(var(--coral) 0 ${holdPct}%, var(--yellow) ${holdPct}% ${escPct}%, var(--blue) ${escPct}% 100%)`;
  } else {
    $(".donut").style.background = `conic-gradient(#e5e9ef 0 100%)`;
  }
  
  $("#recent-cases").innerHTML = overviewData.latest_cases.map(c=>caseRow(c,true)).join("");
  bindCaseRows();
}
async function loadCases(){
  const risk=$("#filter-risk").value, reason=$("#filter-reason").value;
  const data=await api(`/api/cases?risk=${encodeURIComponent(risk)}&reason=${encodeURIComponent(reason)}`);
  casesData=data.cases;
  $("#case-count").textContent=`${data.count.toLocaleString("en-IN")} cases`;
  if ($("#filter-reason").options.length===1) data.reasons.forEach(r=>$("#filter-reason").insertAdjacentHTML("beforeend",`<option>${r}</option>`));
  renderCases(casesData);
}
function renderCases(list){
  const search=($("#case-search").value||"").toLowerCase();
  const filtered=list.filter(c=>[c.return_id,c.merchant_id,c.customer_id].some(v=>v.toLowerCase().includes(search)));
  $("#cases-table").innerHTML=filtered.map(c=>caseRow(c)).join("") || `<tr><td colspan="8" class="empty-state">No cases match these filters.</td></tr>`;
  bindCaseRows();
}
function humanReviewMarkup(c,a){
  if (a.human_decision && a.human_decision.final_decision) {
    return `<article class="panel human-review-panel"><h3 class="section-title">Human review decision</h3><div class="recommend"><strong>FINAL: ${a.human_decision.final_decision}</strong><br><small>Reviewer: ${a.human_decision.reviewer} · ${new Date(a.human_decision.created_at).toLocaleString("en-IN")}</small><br><br>${a.human_decision.reason}</div></article>`;
  }

  if (!["HOLD REFUND","ESCALATE TO HUMAN REVIEW"].includes(a.decision)) return "";

  return `<article class="panel human-review-panel">
    <h3 class="section-title">Human review</h3>
    <div class="recommend">
      <strong>Automated decision: ${a.decision}</strong>
      <br><small>${a.decision_reason}</small>
    </div>
    <div style="display:flex;gap:10px;margin:18px 0">
      <button type="button" class="human-decision-btn" data-decision="APPROVE REFUND">APPROVE REFUND</button>
      <button type="button" class="human-decision-btn" data-decision="DENY REFUND">DENY REFUND</button>
    </div>
    <textarea id="human-review-reason" rows="4" placeholder="Reviewer note / reason (required, 5-500 characters)" style="width:100%;box-sizing:border-box;padding:12px;border:1px solid #d9dee7;border-radius:8px;resize:vertical"></textarea>
    <button type="button" id="finalize-human-decision" disabled style="margin-top:12px">FINALIZE DECISION</button>
  </article>`;
}

async function finalizeHumanDecision(id){
  const selected=$(".human-decision-btn.selected");
  const reason=$("#human-review-reason")?.value.trim();

  if(!selected){
    toast("Select APPROVE or DENY first");
    return;
  }

  if(!reason || reason.length<5){
    toast("Reviewer note must be at least 5 characters");
    return;
  }

  const btn=$("#finalize-human-decision");
  btn.disabled=true;

  try{
    await api(`/api/cases/${id}/human-decision`,{
      method:"POST",
      body:JSON.stringify({
        decision:selected.dataset.decision,
        reason
      })
    });

    toast(`Human decision finalized: ${selected.dataset.decision}`);
    await openDetail(id);
  }catch(err){
    toast(err.message || "Unable to finalize decision");
    btn.disabled=false;
  }
}
async function openDetail(id){
  const data=await api(`/api/cases/${id}`);
  const c=data.case, a=data.analysis;
  navigate("detail");
  $("#detail-eyebrow").textContent=`CASE DETAILS / ${c.return_id}`;
  $("#detail-title").innerHTML=`${c.return_id} <em>verification.</em>`;
  $("#detail-subhead").textContent=`${c.order_id} · ${c.merchant_id} · Requested ${date(c.return_request_timestamp)}`;
  const displayedDecision=a.final_decision||a.decision;
  $("#detail-verdict").innerHTML=`<span class="verdict ${decisionClass(displayedDecision)}">${displayedDecision}</span>`;
  const rules=a.triggered_rules.map(r=>`<div class="rule-row"><span class="rule-id">${r.rule_id}</span><span class="rule-result ${r.result}">${r.result}</span><span class="rule-evidence">${r.evidence}</span></div>`).join("");
  const evidence=a.evidence_summary.map(e=>`<li>${e}</li>`).join("");
  const timeline=a.audit_trail.map(x=>`<div class="timeline-item"><strong>${x.event_type.replaceAll("_"," ")}</strong><small>${new Date(x.created_at).toLocaleString("en-IN")}</small><span>${x.detail}</span></div>`).join("");
  $("#detail-content").innerHTML=`<div class="detail-grid"><div class="detail-main"><article class="panel"><div class="case-identity"><div><div class="case-big">${c.return_id}</div><small>${c.customer_id} · ${c.product_id}</small></div><div class="identity-badge"><span>REFUND VALUE</span><strong>${money(c.refund_amount)}</strong></div></div><div class="detail-facts"><div><span>RETURN REASON</span><strong>${c.return_reason}</strong></div><div><span>ORIGINAL SKU</span><strong>${c.original_sku}</strong></div><div><span>RETURNED SKU</span><strong>${c.returned_sku}</strong></div><div><span>WAREHOUSE</span><strong>${c.warehouse_scan_result.replaceAll("_"," ")}</strong></div></div></article><article class="panel"><h3 class="section-title">Deterministic evidence checks</h3>${rules}</article><article class="panel"><h3 class="section-title">Investigator summary</h3><div class="recommend"><strong>${a.investigator.summary}</strong>${a.investigator.why}</div><ul class="evidence-list">${evidence}</ul><div class="recommend"><strong>Recommended human-review questions</strong>${a.investigator.review_questions.join("<br>")}</div></article></div><div class="detail-side"><article class="panel"><div class="risk-card"><div class="risk-ring" style="--risk:${a.risk_percent}%"><span>${a.risk_percent}%</span></div><div class="risk-copy"><strong>${a.decision}</strong><small>${a.decision_reason}</small></div></div><div class="score-bars"><div class="score-bar"><span>ML model</span><div class="bar-track"><i class="model" style="width:${(a.model_score||0)*100}%"></i></div><b>${a.model_score===null?"—":Math.round(a.model_score*100)+"%"}</b></div><div class="score-bar"><span>Rule evidence</span><div class="bar-track"><i style="width:${a.rule_score*100}%"></i></div><b>${Math.round(a.rule_score*100)}%</b></div><div class="score-bar"><span>Graph signal</span><div class="bar-track"><i class="pattern" style="width:${a.pattern_score*100}%"></i></div><b>${Math.round(a.pattern_score*100)}%</b></div></div></article><article class="panel"><h3 class="section-title">Coordinated-return context</h3><div class="recommend"><strong>${a.pattern.pattern_id}</strong>${a.pattern.supporting_evidence}<br><br><small>Connected: ${a.pattern.connected_entities.join(" · ")}</small></div></article><article class="panel"><h3 class="section-title">Audit trail</h3><div class="timeline">${timeline}</div></article></div></div>`;
  const reviewMarkup=humanReviewMarkup(c,a);
  if(reviewMarkup){
    $("#detail-content").insertAdjacentHTML("beforeend",reviewMarkup);

    $$(".human-decision-btn").forEach(btn=>{
      btn.onclick=()=>{
        $$(".human-decision-btn").forEach(b=>b.classList.remove("selected"));
        btn.classList.add("selected");
        $("#finalize-human-decision").disabled=false;
      };
    });

    $("#finalize-human-decision").onclick=()=>finalizeHumanDecision(c.return_id);
  }
}
async function loadPatterns(){ const d=await api("/api/patterns"); $("#graph-nodes").textContent=d.graph_nodes.toLocaleString("en-IN"); $("#linked-cases").textContent=d.linked_cases.toLocaleString("en-IN"); $("#active-clusters").textContent=d.patterns.length.toString().padStart(2,"0"); $("#patterns-list").innerHTML=d.patterns.map(p=>`<div class="pattern-row"><strong>${p.pattern_id}</strong><p>${p.supporting_evidence}<br><small>${p.connected_entities.join(" · ")}</small></p><span class="confidence">${Math.round(p.confidence*100)}% <small>confidence</small></span><button class="text-link" data-open-case="${p.case_id}">Inspect →</button></div>`).join("") || `<p class="subhead">No coordinated patterns met the evidence threshold.</p>`; $$("[data-open-case]").forEach(b=>b.onclick=()=>openDetail(b.dataset.openCase)); }
async function loadSpikes(){ const d=await api("/api/spikes"); $("#spikes-table").innerHTML=d.spikes.map(s=>`<tr><td><strong>${s.affected_merchant}</strong></td><td>${s.time_window}</td><td>${s.baseline}%</td><td>${s.current_rate}%</td><td class="spike-deviation">${s.deviation}σ</td><td><span class="severity ${s.severity==="high"?"high":"medium"}">${s.severity.toUpperCase()}</span></td><td><button class="text-link" data-open-case="${s.case_id}">Inspect →</button></td></tr>`).join(""); $$("[data-open-case]").forEach(b=>b.onclick=()=>openDetail(b.dataset.openCase)); }
async function loadEvaluation(){ const d=await api("/api/evaluation"); $("#eval-precision").textContent=(d.precision*100).toFixed(1)+"%"; $("#eval-recall").textContent=(d.recall*100).toFixed(1)+"%"; $("#eval-f1").textContent=(d.f1*100).toFixed(1)+"%"; $("#eval-prauc").textContent=d.pr_auc.toFixed(3); const m=d.confusion_matrix; $("#cm-tn").textContent=m[0][0].toLocaleString(); $("#cm-fp").textContent=m[0][1].toLocaleString(); $("#cm-fn").textContent=m[1][0].toLocaleString(); $("#cm-tp").textContent=m[1][1].toLocaleString(); $("#eval-fp").textContent=d.false_positives.toLocaleString(); $("#eval-fn").textContent=d.false_negatives.toLocaleString(); $("#eval-cost").textContent=money(d.false_positive_cost_per_case); $("#eval-prevented").textContent=money(d.fraudulent_refunds_prevented); $("#eval-held").textContent=money(d.legitimate_value_held); $("#eval-net").textContent=money(d.fraudulent_refunds_prevented-d.legitimate_value_held); $("#split-note").textContent=`${d.split} Dataset: ${d.dataset_size.toLocaleString()} cases · train ${d.train_size.toLocaleString()} · validation ${d.validation_size.toLocaleString()} · test ${d.test_size.toLocaleString()} · ROC-AUC ${d.roc_auc}`; $("#threshold-table").innerHTML=d.thresholds.map(x=>`<tr class="${x.threshold===.5?"current":""}"><td><strong>${x.threshold.toFixed(2)}</strong></td><td>${(x.precision*100).toFixed(1)}%</td><td>${(x.recall*100).toFixed(1)}%</td><td>${(x.f1*100).toFixed(1)}%</td><td>${x.false_positives}</td><td>${x.false_negatives}</td></tr>`).join(""); }
async function loadAudit(){ const d=await api("/api/audit"); $("#audit-list").innerHTML=d.events.map(x=>`<div class="audit-item"><strong>${x.event_type.replaceAll("_"," ").toUpperCase()}</strong><span class="audit-case">${x.return_id}</span><span>${x.detail}</span><time>${new Date(x.created_at).toLocaleString("en-IN")}</time></div>`).join("") || `<p class="subhead">No case has been opened yet. Open a case to create its immutable verification trail.</p>`; }
function navigate(page){ $$(".page").forEach(p=>p.classList.remove("active-page")); $(`#page-${page}`).classList.add("active-page"); $$(".nav-item").forEach(n=>n.classList.toggle("active",n.dataset.page===page)); $("#crumb-current").textContent=page.replaceAll("-"," ").toUpperCase(); window.scrollTo(0,0); if(page==="cases")loadCases(); if(page==="patterns")loadPatterns(); if(page==="spikes")loadSpikes(); if(page==="evaluation")loadEvaluation(); if(page==="audit")loadAudit(); }
async function boot(){ const s=await fetch("/api/session").then(r=>r.json()); if(!s.authenticated){csrfToken=null;showLogin();return} if(s.csrf_token)csrfToken=s.csrf_token; showApp(); await loadOverview(); }
$("#login-form").addEventListener("submit",async e=>{e.preventDefault(); const form=new FormData(e.target); try{const res=await api("/api/login",{method:"POST",body:JSON.stringify(Object.fromEntries(form))}); if(res.csrf_token)csrfToken=res.csrf_token; showApp(); await loadOverview();}catch(err){$("#login-error").textContent=err.message}});
$("#logout-btn").onclick=async()=>{try{await api("/api/logout",{method:"POST"});}catch(e){} csrfToken=null; showLogin();};
$$(".nav-item").forEach(b=>b.onclick=()=>navigate(b.dataset.page));
$$("[data-page-jump]").forEach(b=>b.onclick=()=>navigate(b.dataset.pageJump));
$("#filter-risk").onchange=loadCases; $("#filter-reason").onchange=loadCases; $("#case-search").oninput=()=>renderCases(casesData||[]);
$("#refresh-audit").onclick=loadAudit;

function openVerifyModal(){
  const modal=$("#verify-modal-backdrop");
  if(modal) modal.classList.remove("hidden");
  const err=$("#verify-error");
  if(err){ err.classList.add("hidden"); err.textContent=""; }
}
function closeVerifyModal(){
  const modal=$("#verify-modal-backdrop");
  if(modal) modal.classList.add("hidden");
}

const DEMO_SCENARIOS = {

  legitimate: {
    order_id: "ORD-DEMO-CLEAN-001",
    merchant_id: "M-003",
    customer_id: "C-DEMO-CLEAN-001",

    original_sku: "P-0042-A",
    returned_sku: "P-0042-A",
    refund_amount: 1499,

    original_package_weight: 0.850,
    returned_package_weight: 0.840,

    serial_number_match: "match",
    product_condition: "sealed",

    warehouse_scan_result: "verified",
    return_reason: "changed mind",

    courier_status: "received",
    customer_return_count: 0,
    previous_similar_claims: 0,

    device_id: "DV-DEMO-CLEAN-001",
    shipping_address_hash: "SA-DEMO-CLEAN-001",
    payment_instrument_hash: "PI-DEMO-CLEAN-001"
  },

  sku_mismatch: {
    order_id: "ORD-912044",
    merchant_id: "M-008",
    customer_id: "C-0912",

    original_sku: "P-0112-A",
    returned_sku: "P-0489-B",
    refund_amount: 38999,

    original_package_weight: 3.500,
    returned_package_weight: 0.820,

    serial_number_match: "mismatch",
    product_condition: "partial",

    warehouse_scan_result: "manual_review",
    return_reason: "damaged in transit",

    courier_status: "received",
    customer_return_count: 5,
    previous_similar_claims: 3,

    device_id: "DV-DEMO-SKU-001",
    shipping_address_hash: "SA-DEMO-SKU-001",
    payment_instrument_hash: "PI-DEMO-SKU-001"
  },

  suspicious_history: {
    order_id: "ORD-671092",
    merchant_id: "M-014",
    customer_id: "C-0012",

    original_sku: "P-0095-A",
    returned_sku: "P-0095-A",
    refund_amount: 45000,

    original_package_weight: 1.200,
    returned_package_weight: 1.180,

    serial_number_match: "match",
    product_condition: "opened",

    warehouse_scan_result: "manual_review",
    return_reason: "missing parts",

    courier_status: "received",
    customer_return_count: 9,
    previous_similar_claims: 5,

    device_id: "DV-DEMO-HISTORY-001",
    shipping_address_hash: "SA-DEMO-HISTORY-001",
    payment_instrument_hash: "PI-DEMO-HISTORY-001"
  },

  coordinated_abuse: {
    order_id: "ORD-512099",
    merchant_id: "M-001",
    customer_id: "C-0005",

    original_sku: "P-0010-A",
    returned_sku: "P-0010-A",
    refund_amount: 29999,

    original_package_weight: 1.500,
    returned_package_weight: 1.480,

    serial_number_match: "match",
    product_condition: "opened",

    warehouse_scan_result: "manual_review",
    return_reason: "not as described",

    courier_status: "received",
    customer_return_count: 6,
    previous_similar_claims: 4,

    // Keep this shared identifier intentional for the coordination demo.
    device_id: "DV-00010",
    shipping_address_hash: "SA-DEMO-COORD-001",
    payment_instrument_hash: "PI-DEMO-COORD-001"
  },

  dependency_failure: {
    order_id: "ORD-301928",
    merchant_id: "M-021",
    customer_id: "C-1102",

    original_sku: "P-0310-A",
    returned_sku: "P-0310-A",
    refund_amount: 18500,

    original_package_weight: 2.000,
    returned_package_weight: 1.990,

    serial_number_match: "match",
    product_condition: "opened",

    warehouse_scan_result: "unverified",
    return_reason: "changed mind",

    courier_status: "received_before_pickup_scan",
    customer_return_count: 1,
    previous_similar_claims: 0,

    device_id: "DV-DEMO-FAIL-001",
    shipping_address_hash: "SA-DEMO-FAIL-001",
    payment_instrument_hash: "PI-DEMO-FAIL-001"
  }

};

$("#demo-scenario-select").onchange = (e) => {
  const val = e.target.value;

  if (!val || !DEMO_SCENARIOS[val]) return;

  const data = DEMO_SCENARIOS[val];
  const form = $("#verify-return-form");

  // Clear all scenario-controlled fields first.
  Object.keys(data).forEach((key) => {
    if (form.elements[key]) {
      form.elements[key].value = "";
    }
  });

  // Load the selected scenario.
  Object.entries(data).forEach(([key, value]) => {
    if (form.elements[key]) {
      form.elements[key].value = value;
    }
  });

  toast(`Loaded Scenario: ${val.toUpperCase()}`);
};

$("#new-case-btn").onclick=openVerifyModal;
$("#close-verify-modal").onclick=closeVerifyModal;
$("#cancel-verify-btn").onclick=closeVerifyModal;

$("#verify-return-form").onsubmit=async(e)=>{
  e.preventDefault();
  const form=e.target;
  const errDiv=$("#verify-error");
  errDiv.classList.add("hidden");
  errDiv.textContent="";
  const payload=Object.fromEntries(new FormData(form));
  try{
    const res=await api("/api/verify",{
      method:"POST",
      body:JSON.stringify(payload)
    });
    closeVerifyModal();
    toast(`Return Verified: ${res.decision}`);
    await openDetail(res.return_id);
  }catch(err){
    errDiv.textContent=err.message||"Verification failed.";
    errDiv.classList.remove("hidden");
  }
};

$("#export-btn").onclick=()=>{const csv=["return_id,merchant_id,refund_amount,risk_score,decision",...(casesData||[]).map(c=>[c.return_id,c.merchant_id,c.refund_amount,c.risk_score,c.decision].join(","))].join("\n");const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([csv],{type:"text/csv"}));a.download="reclaim-sentinel-cases.csv";a.click();toast("Case view exported");};
boot().catch(err=>console.error(err));