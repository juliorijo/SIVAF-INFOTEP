const API_BASE = (
  new URLSearchParams(window.location.search).get("api")
  || (["localhost", "127.0.0.1"].includes(window.location.hostname)
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : window.location.origin)
).replace(/\/$/, "");
const PAGE_SIZE = 8;
const ACTION_PAGE_SIZE = 25;
const state = {
  jobs: [], summary: {}, selectedJob: null, page: 0, pendingOnly: false,
  evidenceObjectUrl: null, previewObjectUrl: null, previewPage: 1, previewPageCount: 0,
  user: null, actions: { items: [], total: 0, latest_import: null }, actionPage: 0,
  access: { users: [], permissions: [], teams: [] },
};
let refreshTimer = null;
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[character]));
const statusInfo = {
  QUEUED: ["Recibido", "status-queued"],
  PROCESSING: ["En proceso", "status-processing"],
  COMPLETED: ["Procesamiento finalizado", "status-complete"],
  REQUIRES_REVIEW: ["Revisión requerida", "status-review"],
  FAILED: ["Error", "status-failed"],
};
const finalStatusLabels = {
  APROBADA: "Aprobada",
  DEVUELTA: "Devuelta",
  MODIFICACION: "Modificación",
  OTRO: "Otro",
};
const roleLabels = {
  admin: "Administración",
  supervisor: "Supervisor",
  analyst: "Analista",
  dba: "DBA",
};

function toast(message) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("show");
  window.setTimeout(() => element.classList.remove("show"), 3500);
}

function showLogin(message = "") {
  if (refreshTimer) {
    window.clearInterval(refreshTimer);
    refreshTimer = null;
  }
  $("#auth-screen").hidden = false;
  $(".app-shell").hidden = true;
  $("#login-error").textContent = message;
  $("#login-password").value = "";
}

function showDashboard(user) {
  state.user = user;
  $("#auth-screen").hidden = true;
  $(".app-shell").hidden = false;
  $("#user-name").textContent = user.username;
  $("#user-avatar").textContent = user.username.slice(0, 2).toUpperCase();
  $("#user-role").textContent = roleLabels[user.role] || user.role;
  $("#reviewer-info").textContent = `La revisión se registrará a nombre de ${user.username}.`;
  $("#action-import-controls").hidden = user.role !== "admin";
  const canAccessControl = ["admin", "supervisor", "dba"].includes(user.role);
  $("#access-navigation").hidden = !canAccessControl;
  if (!canAccessControl && window.location.hash === "#access") {
    window.location.hash = "#dashboard";
  }
  if (refreshTimer) window.clearInterval(refreshTimer);
  refreshTimer = window.setInterval(loadJobs, 30000);
  renderRoute();
}

function setConnection(online) {
  const status = $("#api-status");
  status.classList.toggle("online", online);
  status.classList.toggle("offline", !online);
  status.innerHTML = `<i></i>${online ? "API conectada" : "API no disponible"}`;
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, { credentials: "include", ...options });
  if (response.status === 401 && path !== "/api/v1/auth/login") {
    showLogin("La sesión venció o ya no es válida. Inicia sesión nuevamente.");
  }
  if (!response.ok) {
    let detail = `Error HTTP ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {}
    throw new Error(detail);
  }
  if (response.status === 204) return null;
  return response.json();
}

function displayName(job) {
  const path = job.source_pdf_name || job.source_pdf_path || "";
  const fileName = path.split(/[\\/]/).pop() || "Documento PDF";
  const storagePrefix = `${job.id}_`;
  return fileName.startsWith(storagePrefix) ? fileName.slice(storagePrefix.length) : fileName;
}

function getCode(job) {
  return job.metadata?.action_code || "Código de acción pendiente";
}

function getFilteredJobs() {
  const availableJobs = state.jobs.filter((job) => job.evidence_available !== false);
  const query = $("#search-input").value.trim().toLocaleLowerCase();
  const selectedStatus = $("#status-filter").value;
  return availableJobs.filter((job) => {
    const searchable = `${displayName(job)} ${getCode(job)}`.toLocaleLowerCase();
    const pendingReview = !state.pendingOnly || (job.status === "REQUIRES_REVIEW" && !job.human_review);
    return pendingReview && (!query || searchable.includes(query)) && (!selectedStatus || job.status === selectedStatus);
  });
}

function renderJobs() {
  const filtered = getFilteredJobs();
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  state.page = Math.min(state.page, pageCount - 1);
  const pageJobs = filtered.slice(state.page * PAGE_SIZE, (state.page + 1) * PAGE_SIZE);
  const body = $("#jobs-list");
  if (!filtered.length) {
    const availableCount = state.jobs.filter((job) => job.evidence_available !== false).length;
    const message = availableCount
      ? "No hay resultados con estos filtros."
      : state.jobs.length
        ? "No hay PDF disponibles en el almacenamiento de evidencia. Los registros antiguos o con rutas fuera del almacenamiento se omiten."
        : "Aún no hay documentos. Carga un PDF para comenzar.";
    body.innerHTML = `<tr><td colspan="5" class="empty-state">${message}</td></tr>`;
  } else {
    body.innerHTML = pageJobs.map((job) => {
      const [label, statusClass] = statusInfo[job.status] || ["Estado desconocido", "status-queued"];
      const date = job.queued_at ? new Date(job.queued_at).toLocaleDateString("es-DO", { day: "2-digit", month: "short", year: "numeric" }) : "—";
      const reviewLabel = job.human_review
        ? `<span class="review-mark">Revisado${job.human_review.final_status ? ` · ${escapeHtml(finalStatusLabels[job.human_review.final_status] || job.human_review.final_status)}` : ""}</span>`
        : "";
      return `<tr>
        <td><div class="file-cell"><span class="pdf-icon">PDF</span><span><span class="file-name">${escapeHtml(displayName(job))}</span><span class="file-code">${escapeHtml(getCode(job))}</span></span></div></td>
        <td>${escapeHtml(date)}</td><td>${Number.isInteger(job.metadata?.page_count) ? job.metadata.page_count : "—"}</td>
        <td><span class="status-pill ${statusClass}">${label}</span>${reviewLabel}</td>
        <td><button class="row-menu" data-job="${escapeHtml(job.id)}" aria-label="Ver detalle">···</button></td>
      </tr>`;
    }).join("");
  }
  const start = filtered.length ? state.page * PAGE_SIZE + 1 : 0;
  const hiddenCount = state.jobs.length - state.jobs.filter((job) => job.evidence_available !== false).length;
  $("#jobs-count").textContent = `Mostrando ${start}–${Math.min((state.page + 1) * PAGE_SIZE, filtered.length)} de ${filtered.length} registros${hiddenCount ? ` · ${hiddenCount} sin evidencia` : ""}`;
  $("#page-previous").disabled = state.page === 0;
  $("#page-next").disabled = state.page >= pageCount - 1;
  body.querySelectorAll("[data-job]").forEach((button) => button.addEventListener("click", () => openJob(button.dataset.job)));

  const visibleJobs = state.jobs.filter((job) => job.evidence_available !== false);
  const review = state.summary.in_review ?? visibleJobs.filter((job) => job.status === "REQUIRES_REVIEW" && !job.human_review).length;
  $("#stat-total").textContent = state.summary.total ?? visibleJobs.length;
  $("#stat-pending").textContent = state.summary.pending ?? visibleJobs.filter((job) => job.status === "PROCESSING" || job.status === "QUEUED").length;
  $("#stat-review").textContent = review;
  $("#stat-incidents").textContent = state.summary.incidents ?? 0;
  $("#stat-unverifiable").textContent = state.summary.not_verifiable ?? 0;
  $("#stat-complete").textContent = state.summary.processed ?? visibleJobs.filter((job) => job.status === "COMPLETED").length;
  $("#review-count").textContent = review;
  $("#review-title").textContent = review ? `${review} expediente${review === 1 ? "" : "s"} pendiente${review === 1 ? "" : "s"}` : "Todo al día";
  $("#review-description").textContent = review
    ? "Hay PDF esperando revisión humana. Los datos de identidad aún no están validados por OCR."
    : "Cuando un PDF requiera revisión, aparecerá aquí.";
  const recent = visibleJobs.slice(0, 4);
  $("#activity-list").innerHTML = recent.length ? recent.map((job) => {
    const actor = job.human_review?.reviewer ? ` · ${escapeHtml(job.human_review.reviewer)}` : "";
    const detail = job.human_review?.final_status ? ` · ${escapeHtml(finalStatusLabels[job.human_review.final_status] || job.human_review.final_status)}` : "";
    return `<div class="activity-item"><span class="activity-dot"></span><span><strong>${escapeHtml(displayName(job))}</strong><small>${escapeHtml(job.human_review ? "Revisión guardada" : statusInfo[job.status]?.[0] || job.status)}${actor}${detail}</small></span></div>`;
  }).join("") : `<p class="muted">La actividad aparecerá al cargar documentos.</p>`;
}

async function loadJobs() {
  try {
    [state.jobs, state.summary] = await Promise.all([
      api("/api/v1/jobs"),
      api("/api/v1/dashboard/summary"),
    ]);
    setConnection(true);
    renderJobs();
  } catch {
    setConnection(false);
    $("#jobs-list").innerHTML = `<tr><td colspan="5" class="empty-state">No se pudieron cargar los expedientes. Comprueba que la API esté iniciada.</td></tr>`;
    $("#jobs-count").textContent = "Sin conexión con la API";
  }
}

function renderRoute() {
  const routes = {
    "#actions": ["actions-view", "Acciones formativas"],
    "#reviews": ["reviews-view", "Revisión pendiente"],
    "#access": ["access-view", "Usuarios y permisos"],
  };
  const [viewId, title] = routes[window.location.hash] || ["dashboard-view", "Panel general"];
  document.querySelectorAll(".route-view").forEach((view) => { view.hidden = view.id !== viewId; });
  document.querySelectorAll(".nav-link").forEach((link) => {
    link.classList.toggle("active", link.hash === (routes[window.location.hash] ? window.location.hash : "#dashboard"));
  });
  $(".breadcrumbs strong").textContent = title;
  state.pendingOnly = viewId === "reviews-view";
  if (state.pendingOnly) {
    state.page = 0;
    $("#search-input").value = "";
    $("#status-filter").value = "REQUIRES_REVIEW";
    renderJobs();
  }
  if (viewId === "actions-view") void loadActions();
  if (viewId === "access-view") void loadAccessControlData();
}

function renderActions() {
  const { items, total, latest_import: latestImport } = state.actions;
  const pages = Math.max(1, Math.ceil(total / ACTION_PAGE_SIZE));
  state.actionPage = Math.min(state.actionPage, pages - 1);
  const header = $("#actions-columns");
  const body = $("#actions-list");
  header.innerHTML = "<tr><th>CÓDIGO</th><th>ACCIÓN FORMATIVA</th><th>FECHA DE INICIO</th><th>ESTADO</th><th>DETALLES DEL REGISTRO</th></tr>";
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="5" class="empty-state">${total ? "No se encontraron acciones con esa búsqueda." : "Todavía no hay acciones cargadas. Un administrador puede importar el Excel de inicios de Drive."}</td></tr>`;
  } else {
    body.innerHTML = items.map((action) => {
      const fields = Object.entries(action.fields || {}).filter(([, value]) => value !== null && value !== "");
      const details = fields.length
        ? `<details class="action-details"><summary>Ver ${fields.length} campo${fields.length === 1 ? "" : "s"}</summary><dl>${fields.map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`).join("")}</dl></details>`
        : "—";
      return `<tr>
        <td>${escapeHtml(action.action_code)}</td>
        <td>${escapeHtml(action.name || "—")}</td>
        <td>${escapeHtml(action.start_date || "—")}</td>
        <td>${escapeHtml(action.status || "—")}</td>
        <td>${details}</td>
      </tr>`;
    }).join("");
  }
  const start = total ? state.actionPage * ACTION_PAGE_SIZE + 1 : 0;
  $("#actions-count").textContent = `Mostrando ${start}–${Math.min((state.actionPage + 1) * ACTION_PAGE_SIZE, total)} de ${total} acciones`;
  $("#action-total").textContent = `${total} registro${total === 1 ? "" : "s"} en la base de acciones formativas`;
  $("#actions-previous").disabled = state.actionPage === 0;
  $("#actions-next").disabled = state.actionPage >= pages - 1;
  $("#action-import-status").textContent = latestImport
    ? `Última actualización: ${latestImport.filename} · ${new Date(latestImport.imported_at).toLocaleString("es-DO")} por ${latestImport.imported_by}. ${latestImport.inserted_rows} nuevas y ${latestImport.updated_rows} actualizadas; los registros ausentes del Excel se conservan.`
    : "Las cargas nuevas actualizan las acciones por su código y conservan las que no aparezcan en el archivo. Solo administración puede importar o modificar estos registros.";
}

async function loadActions() {
  const query = $("#action-search").value.trim();
  const params = new URLSearchParams({
    q: query,
    limit: String(ACTION_PAGE_SIZE),
    offset: String(state.actionPage * ACTION_PAGE_SIZE),
  });
  try {
    state.actions = await api(`/api/v1/formative-actions?${params.toString()}`);
    renderActions();
  } catch (error) {
    $("#actions-list").innerHTML = `<tr><td colspan="5" class="empty-state">No se pudo cargar el catálogo: ${escapeHtml(error.message)}</td></tr>`;
    $("#action-total").textContent = "Error al cargar los registros";
  }
}

function renderAccessControlData() {
  const users = state.access.users || [];
  const permissions = state.access.permissions || [];
  const teams = state.access.teams || [];

  const usersBody = $("#access-users-list");
  if (!users.length) {
    usersBody.innerHTML = `<tr><td colspan="4" class="empty-state">No hay usuarios disponibles para este rol.</td></tr>`;
  } else {
    usersBody.innerHTML = users.map((user) => `<tr>
      <td>${escapeHtml(user.username)}</td>
      <td>${escapeHtml(roleLabels[user.role] || user.role)}</td>
      <td>${escapeHtml(user.department || "—")}</td>
      <td>${escapeHtml(user.status || (user.is_active ? "active" : "inactive"))}</td>
    </tr>`).join("");
  }

  $("#access-summary").textContent = `${users.length} usuario${users.length === 1 ? "" : "s"} visible${users.length === 1 ? "" : "s"} para tu rol`;
  $("#permissions-total").textContent = `${permissions.length} permiso${permissions.length === 1 ? "" : "s"} configurado${permissions.length === 1 ? "" : "s"}`;
  $("#teams-total").textContent = `${teams.length} equipo${teams.length === 1 ? "" : "s"} visible${teams.length === 1 ? "" : "s"}`;

  $("#permissions-preview").innerHTML = permissions.length
    ? permissions.slice(0, 12).map((permission) => `<div class="activity-item"><span class="activity-dot"></span><span><strong>${escapeHtml(permission.display_name || permission.name)}</strong><small>${escapeHtml(permission.action || "")}${permission.resource_type ? ` · ${escapeHtml(permission.resource_type)}` : ""}</small></span></div>`).join("")
    : `<p class="muted">No hay permisos para mostrar.</p>`;

  $("#teams-preview").innerHTML = teams.length
    ? teams.map((team) => `<div class="activity-item"><span class="activity-dot"></span><span><strong>${escapeHtml(team.name)}</strong><small>${escapeHtml(team.description || "Sin descripción")}</small></span></div>`).join("")
    : `<p class="muted">No hay equipos para mostrar.</p>`;
}

async function loadAccessControlData() {
  $("#access-note").textContent = "Vista de administración de acceso por roles.";
  try {
    const [users, permissions, teams] = await Promise.all([
      api("/api/v1/users"),
      api("/api/v1/permissions"),
      api("/api/v1/teams"),
    ]);
    state.access = { users, permissions, teams };
    renderAccessControlData();
  } catch (error) {
    state.access = { users: [], permissions: [], teams: [] };
    renderAccessControlData();
    $("#access-note").textContent = `No tienes permiso para ver todos los datos de acceso: ${error.message}`;
  }
}

async function importActions(file) {
  if (!file) return;
  if (!/\.(xlsx|csv)$/i.test(file.name)) {
    toast("Selecciona un archivo .xlsx o .csv exportado desde Drive.");
    return;
  }
  const button = $("#action-import-controls label");
  const form = new FormData();
  form.append("file", file);
  button.setAttribute("aria-disabled", "true");
  button.textContent = "Importando…";
  try {
    const result = await api("/api/v1/formative-actions/import", { method: "POST", body: form });
    state.actionPage = 0;
    $("#action-search").value = "";
    await loadActions();
    toast(`Importación terminada: ${result.inserted_rows} nuevas y ${result.updated_rows} actualizadas.`);
  } catch (error) {
    toast(`No se pudo importar el Excel: ${error.message}`);
  } finally {
    button.removeAttribute("aria-disabled");
    button.innerHTML = "<span>↑</span> Importar / actualizar Excel";
    $("#action-file-input").value = "";
  }
}

async function uploadPdf(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".pdf")) {
    toast("Selecciona un archivo PDF.");
    return;
  }
  const form = new FormData();
  form.append("file", file);
  form.append("metadata", "{}");
  const uploadButton = $("#upload-trigger");
  uploadButton.disabled = true;
  uploadButton.innerHTML = "<span>…</span> Cargando PDF";
  try {
    const job = await api("/api/v1/jobs/upload", { method: "POST", body: form });
    state.jobs.unshift(job);
    state.page = 0;
    renderJobs();
    toast("PDF guardado. El original se conserva como evidencia.");
    await loadJobs();
    await openJob(job.id);
  } catch (error) {
    toast(`No se pudo cargar el PDF: ${error.message}`);
  } finally {
    uploadButton.disabled = false;
    uploadButton.innerHTML = "<span>＋</span> Cargar documento PDF";
    $("#pdf-input").value = "";
  }
}

function renderResults(results) {
  const container = $("#detail-results");
  if (!results.length) {
    container.innerHTML = `<p class="muted">Todavía no se han generado resultados.</p>`;
    return;
  }
  container.innerHTML = results.map((result) => {
    const outcome = result.outcome || "NO_VERIFICABLE";
    const severity = outcome === "INCIDENCIA" ? "result-error"
      : outcome === "REVISION" || outcome === "REVISIÓN" ? "result-warning"
        : outcome === "CORRECTO" ? "result-ok" : "result-neutral";
    return `<article class="result-card ${severity}">
      <div><strong>${escapeHtml(outcome.replaceAll("_", " "))}</strong><small>${escapeHtml(result.reason_code || "SIN_CODIGO")}</small></div>
      <p>${escapeHtml(result.message)}</p>
      ${result.evidence_ref ? `<small>Referencia: ${escapeHtml(result.evidence_ref)}</small>` : ""}
    </article>`;
  }).join("");
}

function renderAudit(events) {
  const container = $("#audit-list");
  if (!events.length) {
    container.innerHTML = `<p class="muted">Sin actividad registrada.</p>`;
    return;
  }
  container.innerHTML = events.map((event) => `<div class="audit-entry">
    <strong>${event.action === "HUMAN_REVIEW_INVALIDATED_BY_REPROCESS"
      ? `La revisión anterior quedó pendiente tras un nuevo procesamiento · ${escapeHtml(event.actor)}`
      : event.action === "CEDULA_VERIFICATIONS_INVALIDATED_BY_REPROCESS"
        ? `${escapeHtml(event.details?.invalidated_count || 0)} cotejos de cédula invalidados tras reprocesar · ${escapeHtml(event.actor)}`
        : event.action === "CEDULA_MANUAL_VERIFICATION_RECORDED"
          ? `${escapeHtml(event.actor)} cotejó ${escapeHtml(event.details?.participant_reference)} · ${escapeHtml(event.details?.outcome)}`
          : `${escapeHtml(event.actor)} guardó una revisión`}</strong>
    <small>${escapeHtml(new Date(event.created_at).toLocaleString("es-DO"))}</small>
    ${event.details?.final_status ? `<span>Estado final: ${escapeHtml(finalStatusLabels[event.details.final_status] || event.details.final_status)}</span>` : ""}
    ${event.details?.comments ? `<p>${escapeHtml(event.details.comments)}</p>` : ""}
  </div>`).join("");
}

async function loadEvidencePreview(jobId, pageNumber) {
  const image = $("#evidence-preview-image");
  const status = $("#evidence-preview-status");
  status.hidden = false;
  status.textContent = `Cargando página ${pageNumber}…`;
  image.hidden = true;
  $("#evidence-page-label").textContent = `Página ${pageNumber} de ${state.previewPageCount || "—"}`;
  $("#evidence-page-previous").disabled = true;
  $("#evidence-page-next").disabled = true;

  try {
    const previewResponse = await fetch(
      `${API_BASE}/api/v1/jobs/${encodeURIComponent(jobId)}/preview?page=${pageNumber}`,
      { credentials: "include" },
    );
    if (!previewResponse.ok) {
      let message = `No se pudo generar la vista previa (HTTP ${previewResponse.status}).`;
      try {
        const body = await previewResponse.json();
        message = body.detail || message;
      } catch {}
      throw new Error(message);
    }
    const previewBlob = await previewResponse.blob();
    if (previewBlob.type !== "image/png") {
      throw new Error("El servidor no devolvió una imagen de vista previa válida.");
    }
    state.previewPageCount = Number(previewResponse.headers.get("X-Page-Count")) || state.previewPageCount;
    if (state.previewObjectUrl) URL.revokeObjectURL(state.previewObjectUrl);
    state.previewObjectUrl = URL.createObjectURL(previewBlob);
    image.src = state.previewObjectUrl;
    image.alt = `Página ${pageNumber} de ${state.previewPageCount} del PDF`;
    image.hidden = false;
    status.hidden = true;
    $("#evidence-page-label").textContent = `Página ${pageNumber} de ${state.previewPageCount}`;
    $("#evidence-page-previous").disabled = pageNumber <= 1;
    $("#evidence-page-next").disabled = pageNumber >= state.previewPageCount;
  } catch (error) {
    status.textContent = error.message;
    $("#evidence-page-label").textContent = `Página ${pageNumber} de ${state.previewPageCount || "—"}`;
  }
}

async function openJob(jobId) {
  try {
    const [job, results, review, audit] = await Promise.all([
      api(`/api/v1/jobs/${encodeURIComponent(jobId)}`),
      api(`/api/v1/jobs/${encodeURIComponent(jobId)}/results`),
      api(`/api/v1/jobs/${encodeURIComponent(jobId)}/review`),
      api(`/api/v1/jobs/${encodeURIComponent(jobId)}/audit`),
    ]);
    state.selectedJob = job;
    $("#detail-title").textContent = displayName(job);
    $("#detail-subtitle").textContent = getCode(job);
    $("#detail-meta").innerHTML = [
      ["Estado del expediente", statusInfo[job.status]?.[0] || job.status],
      ["Páginas", job.metadata?.page_count ?? "Pendiente"],
      ["Hash SHA256", job.original_file_hash ? `${job.original_file_hash.slice(0, 16)}…` : "No disponible"],
      ["Fecha de ingreso", job.queued_at ? new Date(job.queued_at).toLocaleString("es-DO") : "—"],
      ["Lectura de texto", job.metadata?.text_extraction_source || "Pendiente"],
      ["Proveedor OCR", job.metadata?.ocr_provider || "No utilizado"],
      ["Cédulas candidatas (sin validar)", job.metadata?.cedula_candidate_count ?? "Pendiente"],
      ["Páginas con candidatos", job.metadata?.cedula_candidate_pages?.join(", ") || "Ninguna detectada"],
      ["Candidatas en lista", job.metadata?.roster_candidate_count ?? "Pendiente"],
      ["Candidatas en otras páginas", job.metadata?.evidence_candidate_count ?? "Pendiente"],
      ["Pasan control del dígito", job.metadata?.cedula_checksum_valid_count ?? "Pendiente"],
      ["No pasan control (posible error OCR)", job.metadata?.cedula_checksum_invalid_count ?? "Pendiente"],
      ["Pasan control en lista / documentos", `${job.metadata?.roster_checksum_valid_count ?? "—"} / ${job.metadata?.evidence_checksum_valid_count ?? "—"}`],
      ["No pasan en lista / documentos", `${job.metadata?.roster_checksum_invalid_count ?? "—"} / ${job.metadata?.evidence_checksum_invalid_count ?? "—"}`],
      ["Coincidencias exactas legibles", job.metadata?.candidate_matches ?? "Pendiente"],
      ["Candidatas de baja confianza", job.metadata?.low_confidence_evidence_candidates ?? "Pendiente"],
      ["Cotejos confirmados por revisor", job.metadata?.verified_identities ?? 0],
      ["Código de acción", job.metadata?.action_code || "No determinado"],
      ["Revisor", review?.reviewer || "Pendiente"],
      ["Estado final manual", review?.final_status ? finalStatusLabels[review.final_status] || review.final_status : "Sin decisión"],
    ].map(([label, value]) => `<div class="meta-card"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong></div>`).join("");

    renderResults(results);
    renderAudit(audit);
    $("#review-comments").value = review?.comments || "";
    $("#final-status").value = review?.final_status || "";
    $("#cedula-participant-reference").value = "";
    $("#cedula-roster-page").value = "";
    $("#cedula-roster-number").value = "";
    $("#cedula-document-page").value = "";
    $("#cedula-document-number").value = "";
    $("#cedula-visual-confirmed").checked = false;
    const evidenceUrl = `${API_BASE}/api/v1/jobs/${encodeURIComponent(job.id)}/evidence`;
    if (state.evidenceObjectUrl) URL.revokeObjectURL(state.evidenceObjectUrl);
    if (state.previewObjectUrl) URL.revokeObjectURL(state.previewObjectUrl);
    state.evidenceObjectUrl = null;
    state.previewObjectUrl = null;
    state.previewPage = 1;
    state.previewPageCount = Number(job.metadata?.page_count) || 0;
    $("#evidence-open").hidden = true;
    $("#evidence-preview-image").hidden = true;
    $("#evidence-preview-status").hidden = false;
    $("#evidence-preview-status").textContent = "Buscando el PDF original…";
    $("#evidence-page-label").textContent = `Página 1 de ${state.previewPageCount || "—"}`;
    try {
      const evidenceResponse = await fetch(evidenceUrl, { credentials: "include" });
      if (!evidenceResponse.ok) {
        throw new Error(evidenceResponse.status === 404 ? "El archivo original no está disponible en el almacenamiento local actual." : "No se pudo abrir la evidencia.");
      }
      const evidenceBlob = await evidenceResponse.blob();
      if (evidenceBlob.type !== "application/pdf") {
        throw new Error("La evidencia recibida no es un PDF válido.");
      }
      state.evidenceObjectUrl = URL.createObjectURL(evidenceBlob);
      $("#evidence-open").href = state.evidenceObjectUrl;
      $("#evidence-open").hidden = false;
      await loadEvidencePreview(job.id, state.previewPage);
    } catch (error) {
      $("#evidence-preview-status").textContent = error.message;
    }
    $("#process-button").hidden = !["QUEUED", "FAILED", "REQUIRES_REVIEW"].includes(job.status);
    $("#process-button").textContent = job.status === "REQUIRES_REVIEW"
      ? "Volver a procesar PDF"
      : "Procesar PDF";
    $("#detail-dialog").showModal();
  } catch (error) {
    toast(`No se pudo abrir el expediente: ${error.message}`);
  }
}

async function saveReview() {
  if (!state.selectedJob) return;
  const button = $("#save-review");
  button.disabled = true;
  button.textContent = "Guardando…";
  try {
    await api(`/api/v1/jobs/${encodeURIComponent(state.selectedJob.id)}/review`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        comments: $("#review-comments").value,
        final_status: $("#final-status").value || null,
      }),
    });
    toast("Revisión guardada en SIVAF y registrada en auditoría.");
    await loadJobs();
    await openJob(state.selectedJob.id);
  } catch (error) {
    toast(`No se pudo guardar la revisión: ${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = "Guardar revisión";
  }
}

async function saveCedulaVerification() {
  if (!state.selectedJob) return;
  const button = $("#save-cedula-verification");
  button.disabled = true;
  button.textContent = "Evaluando…";
  try {
    const result = await api(
      `/api/v1/jobs/${encodeURIComponent(state.selectedJob.id)}/cedula-verifications`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          participant_reference: $("#cedula-participant-reference").value,
          roster_page: Number($("#cedula-roster-page").value),
          document_page: Number($("#cedula-document-page").value),
          roster_cedula: $("#cedula-roster-number").value,
          document_cedula: $("#cedula-document-number").value,
          visual_identity_confirmed: $("#cedula-visual-confirmed").checked,
        }),
      },
    );
    toast(`${result.participant_reference}: ${result.message}`);
    await loadJobs();
    await openJob(state.selectedJob.id);
  } catch (error) {
    toast(`No se pudo evaluar el cotejo: ${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = "Evaluar y guardar cotejo";
  }
}

async function processSelected() {
  if (!state.selectedJob) return;
  const button = $("#process-button");
  button.disabled = true;
  button.textContent = "Procesando…";
  try {
    await api(`/api/v1/jobs/${encodeURIComponent(state.selectedJob.id)}/process`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force: false }),
    });
    toast("Procesamiento técnico finalizado. Revisa los resultados antes de decidir.");
    await loadJobs();
    await openJob(state.selectedJob.id);
  } catch (error) {
    toast(`No se pudo procesar el PDF: ${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = "Procesar PDF";
  }
}

async function signIn(event) {
  event.preventDefault();
  const button = $("#login-submit");
  const form = new FormData(event.currentTarget);
  button.disabled = true;
  button.textContent = "Validando…";
  $("#login-error").textContent = "";
  try {
    const user = await api("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: form.get("username"),
        password: form.get("password"),
      }),
    });
    showDashboard(user);
    $("#login-form").reset();
    await loadJobs();
  } catch (error) {
    $("#login-error").textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = "Iniciar sesión";
  }
}

async function signOut() {
  try {
    await api("/api/v1/auth/logout", { method: "POST" });
  } catch (error) {
    toast(`No se pudo cerrar la sesión correctamente: ${error.message}`);
  } finally {
    state.user = null;
    showLogin();
  }
}

$("#upload-trigger").addEventListener("click", () => $("#pdf-input").click());
$("#pdf-input").addEventListener("change", (event) => uploadPdf(event.target.files[0]));
$("#refresh-button").addEventListener("click", () => {
  void loadJobs();
  if (window.location.hash === "#actions") void loadActions();
  if (window.location.hash === "#access") void loadAccessControlData();
});
$("#search-input").addEventListener("input", () => { state.page = 0; renderJobs(); });
$("#status-filter").addEventListener("change", () => { state.pendingOnly = window.location.hash === "#reviews"; state.page = 0; renderJobs(); });
$("#page-previous").addEventListener("click", () => { state.page = Math.max(0, state.page - 1); renderJobs(); });
$("#page-next").addEventListener("click", () => { state.page += 1; renderJobs(); });
$("#action-search").addEventListener("input", () => { state.actionPage = 0; void loadActions(); });
$("#actions-previous").addEventListener("click", () => { state.actionPage = Math.max(0, state.actionPage - 1); void loadActions(); });
$("#actions-next").addEventListener("click", () => { state.actionPage += 1; void loadActions(); });
$("#action-file-input").addEventListener("change", (event) => importActions(event.target.files[0]));
$("#evidence-page-previous").addEventListener("click", () => {
  if (state.selectedJob && state.previewPage > 1) {
    state.previewPage -= 1;
    void loadEvidencePreview(state.selectedJob.id, state.previewPage);
  }
});
$("#evidence-page-next").addEventListener("click", () => {
  if (state.selectedJob && state.previewPage < state.previewPageCount) {
    state.previewPage += 1;
    void loadEvidencePreview(state.selectedJob.id, state.previewPage);
  }
});
$("#process-button").addEventListener("click", processSelected);
$("#save-review").addEventListener("click", saveReview);
$("#save-cedula-verification").addEventListener("click", saveCedulaVerification);
$("#use-page-as-roster").addEventListener("click", () => {
  if (state.previewPage > 0) $("#cedula-roster-page").value = state.previewPage;
});
$("#use-page-as-document").addEventListener("click", () => {
  if (state.previewPage > 0) $("#cedula-document-page").value = state.previewPage;
});
$("#close-detail").addEventListener("click", () => $("#detail-dialog").close());
$("#dismiss-notice").addEventListener("click", () => $(".notice-bar").remove());
$("#login-form").addEventListener("submit", signIn);
$("#logout-button").addEventListener("click", signOut);
window.addEventListener("hashchange", renderRoute);

async function initialize() {
  try {
    const user = await api("/api/v1/auth/me");
    showDashboard(user);
    await loadJobs();
  } catch {
    showLogin();
  }
}

initialize();
