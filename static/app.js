const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const money = (n) => "₹" + Number(n || 0).toLocaleString("en-IN");
const date = (v) => new Date(v).toLocaleDateString("en-IN", {day:"2-digit", month:"short"});
const decisionClass = (d) => d.includes("HOLD") ? "verdict-hold" : d.includes("ESCALATE") ? "verdict-escalate" : "verdict-approve";
const decisionShort = (d) => d.includes("HOLD") ? "HOLD REFUND" : d.includes("ESCALATE") ? "HUMAN REVIEW" : "APPROVE";
const riskClass = (n) => n >= .65 ? "risk-high" : n >= .35 ? "risk-mid" : "risk-low";
let overviewData, casesData;

async function api(path, options) {
  const response = await fetch(path, {headers: {"Content-Type":"application/json"}, ...options});
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
  $("#donut-total").textContent = total.toLocaleString("en-IN");
  $("#legend-approve").textContent = (d["APPROVE REFUND"]||0).toLocaleString("en-IN");
  $("#legend-hold").textContent = (d["HOLD REFUND"]||0).toLocaleString("en-IN");
  $("#legend-escalate").textContent = (d["ESCALATE TO HUMAN REVIEW"]||0).toLocaleString("en-IN");
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
async function openDetail(id){
  const data=await api(`/api/cases/${id}`);
  const c=data.case, a=data.analysis;
  navigate("detail");
  $("#detail-eyebrow").textContent=`CASE DETAILS / ${c.return_id}`;
  $("#detail-title").innerHTML=`${c.return_id} <em>verification.</em>`;
  $("#detail-subhead").textContent=`${c.order_id} · ${c.merchant_id} · Requested ${date(c.return_request_timestamp)}`;
  $("#detail-verdict").innerHTML=`<span class="verdict ${decisionClass(a.decision)}">${a.decision}</span>`;
  const rules=a.triggered_rules.map(r=>`<div class="rule-row"><span class="rule-id">${r.rule_id}</span><span class="rule-result ${r.result}">${r.result}</span><span class="rule-evidence">${r.evidence}</span></div>`).join("");
  const evidence=a.evidence_summary.map(e=>`<li>${e}</li>`).join("");
  const timeline=a.audit_trail.map(x=>`<div class="timeline-item"><strong>${x.event_type.replaceAll("_"," ")}</strong><small>${new Date(x.created_at).toLocaleString("en-IN")}</small><span>${x.detail}</span></div>`).join("");
  $("#detail-content").innerHTML=`<div class="detail-grid"><div class="detail-main"><article class="panel"><div class="case-identity"><div><div class="case-big">${c.return_id}</div><small>${c.customer_id} · ${c.product_id}</small></div><div class="identity-badge"><span>REFUND VALUE</span><strong>${money(c.refund_amount)}</strong></div></div><div class="detail-facts"><div><span>RETURN REASON</span><strong>${c.return_reason}</strong></div><div><span>ORIGINAL SKU</span><strong>${c.original_sku}</strong></div><div><span>RETURNED SKU</span><strong>${c.returned_sku}</strong></div><div><span>WAREHOUSE</span><strong>${c.warehouse_scan_result.replaceAll("_"," ")}</strong></div></div></article><article class="panel"><h3 class="section-title">Deterministic evidence checks</h3>${rules}</article><article class="panel"><h3 class="section-title">Investigator summary</h3><div class="recommend"><strong>${a.investigator.summary}</strong>${a.investigator.why}</div><ul class="evidence-list">${evidence}</ul><div class="recommend"><strong>Recommended human-review questions</strong>${a.investigator.review_questions.join("<br>")}</div></article></div><div class="detail-side"><article class="panel"><div class="risk-card"><div class="risk-ring" style="--risk:${a.risk_percent}%"><span>${a.risk_percent}%</span></div><div class="risk-copy"><strong>${a.decision}</strong><small>${a.decision_reason}</small></div></div><div class="score-bars"><div class="score-bar"><span>ML model</span><div class="bar-track"><i class="model" style="width:${(a.model_score||0)*100}%"></i></div><b>${a.model_score===null?"—":Math.round(a.model_score*100)+"%"}</b></div><div class="score-bar"><span>Rule evidence</span><div class="bar-track"><i style="width:${a.rule_score*100}%"></i></div><b>${Math.round(a.rule_score*100)}%</b></div><div class="score-bar"><span>Graph signal</span><div class="bar-track"><i class="pattern" style="width:${a.pattern_score*100}%"></i></div><b>${Math.round(a.pattern_score*100)}%</b></div></div></article><article class="panel"><h3 class="section-title">Coordinated-return context</h3><div class="recommend"><strong>${a.pattern.pattern_id}</strong>${a.pattern.supporting_evidence}<br><br><small>Connected: ${a.pattern.connected_entities.join(" · ")}</small></div></article><article class="panel"><h3 class="section-title">Audit trail</h3><div class="timeline">${timeline}</div></article></div></div>`;
}
async function loadPatterns(){ const d=await api("/api/patterns"); $("#graph-nodes").textContent=d.graph_nodes.toLocaleString("en-IN"); $("#linked-cases").textContent=d.linked_cases.toLocaleString("en-IN"); $("#active-clusters").textContent=d.patterns.length.toString().padStart(2,"0"); $("#patterns-list").innerHTML=d.patterns.map(p=>`<div class="pattern-row"><strong>${p.pattern_id}</strong><p>${p.supporting_evidence}<br><small>${p.connected_entities.join(" · ")}</small></p><span class="confidence">${Math.round(p.confidence*100)}% <small>confidence</small></span><button class="text-link" data-open-case="${p.case_id}">Inspect →</button></div>`).join("") || `<p class="subhead">No coordinated patterns met the evidence threshold.</p>`; $$("[data-open-case]").forEach(b=>b.onclick=()=>openDetail(b.dataset.openCase)); }
async function loadSpikes(){ const d=await api("/api/spikes"); $("#spikes-table").innerHTML=d.spikes.map(s=>`<tr><td><strong>${s.affected_merchant}</strong></td><td>${s.time_window}</td><td>${s.baseline}%</td><td>${s.current_rate}%</td><td class="spike-deviation">${s.deviation}σ</td><td><span class="severity ${s.severity==="high"?"high":"medium"}">${s.severity.toUpperCase()}</span></td><td><button class="text-link" data-open-case="${s.case_id}">Inspect →</button></td></tr>`).join(""); $$("[data-open-case]").forEach(b=>b.onclick=()=>openDetail(b.dataset.openCase)); }
async function loadEvaluation(){ const d=await api("/api/evaluation"); $("#eval-precision").textContent=(d.precision*100).toFixed(1)+"%"; $("#eval-recall").textContent=(d.recall*100).toFixed(1)+"%"; $("#eval-f1").textContent=(d.f1*100).toFixed(1)+"%"; $("#eval-prauc").textContent=d.pr_auc.toFixed(3); const m=d.confusion_matrix; $("#cm-tn").textContent=m[0][0].toLocaleString(); $("#cm-fp").textContent=m[0][1].toLocaleString(); $("#cm-fn").textContent=m[1][0].toLocaleString(); $("#cm-tp").textContent=m[1][1].toLocaleString(); $("#eval-fp").textContent=d.false_positives.toLocaleString(); $("#eval-fn").textContent=d.false_negatives.toLocaleString(); $("#eval-cost").textContent=money(d.false_positive_cost_per_case); $("#eval-prevented").textContent=money(d.fraudulent_refunds_prevented); $("#eval-held").textContent=money(d.legitimate_value_held); $("#eval-net").textContent=money(d.fraudulent_refunds_prevented-d.legitimate_value_held); $("#split-note").textContent=`${d.split} Dataset: ${d.dataset_size.toLocaleString()} cases · train ${d.train_size.toLocaleString()} · validation ${d.validation_size.toLocaleString()} · test ${d.test_size.toLocaleString()} · ROC-AUC ${d.roc_auc}`; $("#threshold-table").innerHTML=d.thresholds.map(x=>`<tr class="${x.threshold===.5?"current":""}"><td><strong>${x.threshold.toFixed(2)}</strong></td><td>${(x.precision*100).toFixed(1)}%</td><td>${(x.recall*100).toFixed(1)}%</td><td>${(x.f1*100).toFixed(1)}%</td><td>${x.false_positives}</td><td>${x.false_negatives}</td></tr>`).join(""); }
async function loadAudit(){ const d=await api("/api/audit"); $("#audit-list").innerHTML=d.events.map(x=>`<div class="audit-item"><strong>${x.event_type.replaceAll("_"," ").toUpperCase()}</strong><span class="audit-case">${x.return_id}</span><span>${x.detail}</span><time>${new Date(x.created_at).toLocaleString("en-IN")}</time></div>`).join("") || `<p class="subhead">No case has been opened yet. Open a case to create its immutable verification trail.</p>`; }
function navigate(page){ $$(".page").forEach(p=>p.classList.remove("active-page")); $(`#page-${page}`).classList.add("active-page"); $$(".nav-item").forEach(n=>n.classList.toggle("active",n.dataset.page===page)); $("#crumb-current").textContent=page.replaceAll("-"," ").toUpperCase(); window.scrollTo(0,0); if(page==="cases")loadCases(); if(page==="patterns")loadPatterns(); if(page==="spikes")loadSpikes(); if(page==="evaluation")loadEvaluation(); if(page==="audit")loadAudit(); }
async function boot(){ const s=await fetch("/api/session").then(r=>r.json()); if(!s.authenticated){showLogin();return} showApp(); await loadOverview(); }
$("#login-form").addEventListener("submit",async e=>{e.preventDefault(); const form=new FormData(e.target); try{await api("/api/login",{method:"POST",body:JSON.stringify(Object.fromEntries(form))}); showApp(); await loadOverview();}catch(err){$("#login-error").textContent=err.message}});
$("#logout-btn").onclick=async()=>{await api("/api/logout",{method:"POST"});showLogin()};
$$(".nav-item").forEach(b=>b.onclick=()=>navigate(b.dataset.page));
$$("[data-page-jump]").forEach(b=>b.onclick=()=>navigate(b.dataset.pageJump));
$("#filter-risk").onchange=loadCases; $("#filter-reason").onchange=loadCases; $("#case-search").oninput=()=>renderCases(casesData||[]);
$("#refresh-audit").onclick=loadAudit;
$("#new-case-btn").onclick=()=>{const c=(overviewData&&overviewData.latest_cases||[])[0]; if(c) openDetail(c.return_id); else toast("No queued cases available");};
$("#export-btn").onclick=()=>{const csv=["return_id,merchant_id,refund_amount,risk_score,decision",...(casesData||[]).map(c=>[c.return_id,c.merchant_id,c.refund_amount,c.risk_score,c.decision].join(","))].join("\\n");const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([csv],{type:"text/csv"}));a.download="reclaim-sentinel-cases.csv";a.click();toast("Case view exported");};
boot().catch(err=>console.error(err));