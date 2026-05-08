const STORAGE_KEY = "mps-assistant-ui-v1"
const LEGACY_KNOWLEDGE_KEY = "mps-assistant-chat-v2"
const MAX_STORED_MESSAGES = 24
const KNOWLEDGE_WELCOME = "Ask about MPS South Africa. Answers come only from official MPS material."
const APPLICATION_INTRO =
  "I can guide the live MPS South Africa membership draft in this chat, using the same journey order as the portal."
const STARTER_QUESTIONS = [
  "What steps are in the membership application?",
  "What personal details does the application ask for?",
  "What file types can I upload in the application?",
  "What should I do if I receive a complaint?",
]
const APPLICATION_STEP_LABELS = [
  "Role",
  "Contact",
  "Quote",
  "Underwriting",
  "Quote",
  "Details",
  "Confirm",
  "Collections",
]
const EFT_BANK_DETAILS = [
  ["Bank", "First National Bank (FNB)"],
  ["Account name", "The Medical Protection Society"],
  ["Account number", "62 *** *** ***"],
  ["Branch code", "250 655"],
  ["Account type", "Business Cheque"],
]

const chatForm = document.getElementById("chat-form")
const askButton = document.getElementById("ask-button")
const questionInput = document.getElementById("question-input")
const toggleChatbox = document.getElementById("toggle-chatbox")
const newChatButton = document.getElementById("new-chat")
const chatboxShell = document.getElementById("chatbox-shell")
const chatLauncher = document.getElementById("chat-launcher")
const messagesStage = document.getElementById("messages-stage")
const messagesList = document.getElementById("chat-messages")
const typingIndicator = document.getElementById("typing-indicator")
const modeKnowledge = document.getElementById("mode-knowledge")
const modeApply = document.getElementById("mode-apply")
const modeCaption = document.getElementById("mode-caption")
const composerNote = document.getElementById("composer-note")
const typingText = typingIndicator.querySelector("p")

let knowledgePending = false
let applicationPending = false
let onboardingConfig = null
let onboardingConfigPromise = null

let uiState = loadUiState()

function defaultQualification() {
  return {
    country: "South Africa",
    institution: "",
    qualification: "",
    monthYear: "",
  }
}

function defaultApplicationState() {
  return {
    currentStep: 0,
    membershipCategory: "",
    verified: false,
    verificationMethod: "email",
    marketing: "no",
    otpSent: false,
    rateCardLoading: false,
    checkboxes: {
      ack: false,
      scd: false,
      acc: false,
    },
    fields: {
      firstName: "",
      lastName: "",
      email: "",
      confirmEmail: "",
      gpCategory: "",
      gpHoursBand: "",
      gpIntrapartumBasis: "",
      membershipStartDate: "",
      gender: "",
      middleNames: "",
      maidenName: "",
      initials: "",
      homePhone: "",
      workPhone: "",
      address1: "",
      address2: "",
      address3: "",
      city: "",
      region: "",
      country: "South Africa",
      postalCode: "",
      clientType: "",
      mpsSpeciality: "",
      collectionMethod: "debit",
      collectionFrequency: "monthly",
    },
    qualifications: [defaultQualification()],
    underwritingAnswers: {},
    underwritingDetails: {},
    uploadedFiles: [],
    selectedPrice: null,
    rateCard: null,
    errorMessage: "",
    noticeMessage: "",
    submitResult: null,
  }
}

function loadUiState() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      return normalizeUiState(parsed)
    }
  } catch (error) {
    // Ignore broken session data.
  }

  try {
    const legacy = sessionStorage.getItem(LEGACY_KNOWLEDGE_KEY)
    if (legacy) {
      const parsed = JSON.parse(legacy)
      return normalizeUiState({
        activeMode: "knowledge",
        knowledgeConversation: Array.isArray(parsed) ? parsed : [],
      })
    }
  } catch (error) {
    // Ignore broken legacy data.
  }

  return normalizeUiState({})
}

function normalizeUiState(value) {
  const defaultState = {
    activeMode: "knowledge",
    knowledgeConversation: [],
    applicationConversation: [],
    application: defaultApplicationState(),
  }

  const state = value && typeof value === "object" ? value : {}
  const activeMode = state.activeMode === "apply" ? "apply" : "knowledge"
  const knowledgeConversation = normalizeConversation(state.knowledgeConversation)
  const applicationConversation = normalizeConversation(state.applicationConversation)
  const application = normalizeApplicationState(state.application)

  return {
    ...defaultState,
    activeMode,
    knowledgeConversation,
    applicationConversation,
    application,
  }
}

function normalizeConversation(items) {
  if (!Array.isArray(items)) {
    return []
  }

  return items
    .filter((item) => item && (item.role === "user" || item.role === "assistant") && typeof item.content === "string")
    .slice(-MAX_STORED_MESSAGES)
}

function normalizeApplicationState(value) {
  const defaults = defaultApplicationState()
  const state = value && typeof value === "object" ? value : {}
  const fields = state.fields && typeof state.fields === "object" ? state.fields : {}

  return {
    ...defaults,
    ...state,
    checkboxes: {
      ...defaults.checkboxes,
      ...(state.checkboxes || {}),
    },
    fields: {
      ...defaults.fields,
      ...fields,
    },
    qualifications: Array.isArray(state.qualifications) && state.qualifications.length
      ? state.qualifications.map((item) => ({
          ...defaultQualification(),
          ...(item || {}),
        }))
      : defaults.qualifications,
    underwritingAnswers: state.underwritingAnswers && typeof state.underwritingAnswers === "object"
      ? state.underwritingAnswers
      : {},
    underwritingDetails: state.underwritingDetails && typeof state.underwritingDetails === "object"
      ? state.underwritingDetails
      : {},
    uploadedFiles: Array.isArray(state.uploadedFiles) ? state.uploadedFiles : [],
    selectedPrice: state.selectedPrice || null,
    rateCard: state.rateCard || null,
    submitResult: state.submitResult || null,
  }
}

function saveUiState() {
  uiState.knowledgeConversation = uiState.knowledgeConversation.slice(-MAX_STORED_MESSAGES)
  uiState.applicationConversation = uiState.applicationConversation.slice(-MAX_STORED_MESSAGES)
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(uiState))
}

function createElement(tag, className, text) {
  const element = document.createElement(tag)
  if (className) {
    element.className = className
  }
  if (text !== undefined) {
    element.textContent = text
  }
  return element
}

function setText(id, text) {
  const node = document.getElementById(id)
  if (node) {
    node.textContent = text || ""
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;")
}

function showTyping(text) {
  typingText.textContent = text
  typingIndicator.classList.remove("hidden")
  scrollMessagesToBottom()
}

function hideTyping() {
  typingIndicator.classList.add("hidden")
}

function setChatboxOpen(isOpen) {
  chatboxShell.classList.toggle("is-open", isOpen)
  chatboxShell.classList.toggle("is-collapsed", !isOpen)
  toggleChatbox.setAttribute("aria-expanded", String(isOpen))
  chatLauncher.classList.toggle("hidden", isOpen)
  if (isOpen && uiState.activeMode === "knowledge") {
    questionInput.focus()
  }
}

function scrollMessagesToBottom() {
  requestAnimationFrame(() => {
    messagesStage.scrollTop = messagesStage.scrollHeight
  })
}

function scrollLatestMessageIntoView() {
  requestAnimationFrame(() => {
    const rows = messagesList.querySelectorAll(".message-row")
    const lastRow = rows[rows.length - 1]
    if (lastRow) {
      lastRow.scrollIntoView({ block: "start", behavior: "smooth" })
      return
    }
    messagesStage.scrollTop = messagesStage.scrollHeight
  })
}

function autoResizeComposer() {
  questionInput.style.height = "auto"
  questionInput.style.height = `${Math.min(questionInput.scrollHeight, 180)}px`
}

function appendTextBlocks(container, text) {
  const normalized = String(text || "").trim()
  if (!normalized) {
    return
  }

  const blocks = normalized.split(/\n\s*\n/)
  for (const block of blocks) {
    const citationOnly = block.trim().match(/^(?:\[\d+\]\s*)+$/)
    if (citationOnly && container.lastElementChild) {
      container.lastElementChild.textContent = `${container.lastElementChild.textContent} ${block.trim()}`.trim()
      continue
    }

    const lines = block
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)

    if (!lines.length) {
      continue
    }

    const allBullets = lines.every((line) => line.startsWith("- "))
    if (allBullets) {
      const list = createElement("ul", "message-list")
      for (const line of lines) {
        list.appendChild(createElement("li", "", line.slice(2).trim()))
      }
      container.appendChild(list)
      continue
    }

    container.appendChild(createElement("p", "message-copy", lines.join("\n")))
  }
}

function renderSourceCards(sources) {
  const wrapper = createElement("div", "source-stack")
  for (const source of sources) {
    const card = createElement("div", "source-card")
    card.appendChild(
      createElement(
        "p",
        "source-title",
        `[${source.number}] ${source.document_title || source.page_title || source.file_name || "MPS source"}`
      )
    )

    const metaParts = [
      source.section_heading ? `Section: ${source.section_heading}` : "",
      source.page_number ? `Page: ${source.page_number}` : "",
      source.file_name ? `File: ${source.file_name}` : "",
    ].filter(Boolean)

    if (metaParts.length) {
      card.appendChild(createElement("p", "source-meta", metaParts.join(" | ")))
    }

    if (source.url) {
      const link = createElement("a", "source-link", source.url)
      link.href = source.url
      link.target = "_blank"
      link.rel = "noreferrer"
      card.appendChild(link)
    }

    wrapper.appendChild(card)
  }
  return wrapper
}

function renderAssistantResponse(response) {
  const bubble = createElement(
    "div",
    `message-bubble assistant-bubble ${response.refused ? "assistant-bubble-refused" : ""}`
  )

  const directBlock = createElement("div", "message-block message-block-primary")
  appendTextBlocks(directBlock, response.direct_answer)
  bubble.appendChild(directBlock)

  if (response.plain_english) {
    const section = createElement("section", "message-section")
    section.appendChild(createElement("p", "message-section-title", "What this means"))
    appendTextBlocks(section, response.plain_english)
    bubble.appendChild(section)
  }

  if (response.practical_next_steps) {
    const section = createElement("section", "message-section")
    section.appendChild(createElement("p", "message-section-title", "What you can do next"))
    appendTextBlocks(section, response.practical_next_steps)
    bubble.appendChild(section)
  }

  if (response.limitations) {
    const section = createElement("section", "message-section")
    section.appendChild(
      createElement(
        "p",
        "message-section-title",
        response.refused ? "Why I can't be sure" : "What to check with MPS"
      )
    )
    appendTextBlocks(section, response.limitations)
    bubble.appendChild(section)
  }

  if (response.sources && response.sources.length) {
    const details = createElement("details", "message-sources")
    details.appendChild(createElement("summary", "", `Sources (${response.sources.length})`))
    details.appendChild(renderSourceCards(response.sources))
    bubble.appendChild(details)
  }

  return bubble
}

function renderTextMessage(message, assistantLabel) {
  const article = createElement("article", `message-row message-row-${message.role}`)

  if (message.role === "assistant") {
    article.appendChild(createElement("div", "message-avatar", "MP"))
  }

  const content = createElement("div", `message-stack message-stack-${message.role}`)
  if (message.role === "assistant") {
    content.appendChild(createElement("p", "message-role", assistantLabel))
  }

  if (message.role === "assistant" && message.response) {
    content.appendChild(renderAssistantResponse(message.response))
  } else {
    const bubble = createElement("div", `message-bubble ${message.role === "user" ? "user-bubble" : "assistant-bubble"}`)
    if (message.role === "assistant") {
      const block = createElement("div", "message-block message-block-primary")
      appendTextBlocks(block, message.content)
      bubble.appendChild(block)
    } else {
      appendTextBlocks(bubble, message.content)
    }
    if (message.isWelcome) {
      const promptBlock = createElement("div", "welcome-prompt")
      promptBlock.appendChild(createElement("p", "starter-title", "Try a question"))
      promptBlock.appendChild(createStarterChips())
      bubble.appendChild(promptBlock)
    }
    content.appendChild(bubble)
  }

  article.appendChild(content)
  messagesList.appendChild(article)
}

function createStarterChips() {
  const wrapper = createElement("div", "starter-chips")

  for (const question of STARTER_QUESTIONS) {
    const button = createElement("button", "starter-chip", question)
    button.type = "button"
    button.dataset.question = question
    button.disabled = knowledgePending
    button.addEventListener("click", async () => {
      await sendQuestion(question)
    })
    wrapper.appendChild(button)
  }

  const applyButton = createElement("button", "starter-chip starter-chip-primary", "Start membership application")
  applyButton.type = "button"
  applyButton.disabled = knowledgePending
  applyButton.addEventListener("click", async () => {
    await switchMode("apply")
  })
  wrapper.appendChild(applyButton)

  return wrapper
}

function buildAssistantHistoryContent(response) {
  const parts = []
  if (response.direct_answer) {
    parts.push(`Direct answer: ${response.direct_answer}`)
  }
  if (response.plain_english) {
    parts.push(`Plain-English interpretation: ${response.plain_english}`)
  }
  if (response.practical_next_steps) {
    parts.push(`Practical next steps: ${response.practical_next_steps}`)
  }
  if (response.limitations) {
    parts.push(`What to confirm with MPS: ${response.limitations}`)
  }
  return parts.join("\n\n")
}

function setKnowledgePendingState(pending) {
  knowledgePending = pending
  askButton.disabled = pending
  askButton.textContent = pending ? "Processing..." : "Send"
  questionInput.disabled = pending
  newChatButton.disabled = pending || applicationPending
  modeKnowledge.disabled = pending || applicationPending
  modeApply.disabled = pending || applicationPending
  document.querySelectorAll(".starter-chip").forEach((button) => {
    button.disabled = pending
  })
}

function setApplicationPendingState(pending) {
  applicationPending = pending
  newChatButton.disabled = pending || knowledgePending
  modeKnowledge.disabled = pending
  modeApply.disabled = pending
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options)
  let data = {}
  try {
    data = await response.json()
  } catch (error) {
    data = {}
  }
  if (!response.ok) {
    throw new Error(data.detail || data.message || "Something went wrong. Please try again.")
  }
  return data
}

async function sendQuestion(prefilledQuestion) {
  const question = String(prefilledQuestion !== undefined ? prefilledQuestion : questionInput.value).trim()
  if (!question) {
    return
  }

  uiState.knowledgeConversation.push({ role: "user", content: question })
  saveUiState()
  renderApp("end")

  questionInput.value = ""
  autoResizeComposer()
  showTyping("processing ...")
  setKnowledgePendingState(true)

  try {
    const data = await fetchJson("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        messages: uiState.knowledgeConversation.map((message) => ({
          role: message.role,
          content: message.content,
        })),
      }),
    })

    uiState.knowledgeConversation.push({
      role: "assistant",
      content: buildAssistantHistoryContent(data),
      response: data,
    })
    saveUiState()
    renderApp("latest")
  } catch (error) {
    uiState.knowledgeConversation.push({
      role: "assistant",
      content: error.message || "Something went wrong. Please try again.",
    })
    saveUiState()
    renderApp("latest")
  } finally {
    hideTyping()
    setKnowledgePendingState(false)
    if (uiState.activeMode === "knowledge") {
      questionInput.focus()
    }
  }
}

function seedApplicationConversation() {
  if (uiState.applicationConversation.length) {
    return
  }
  uiState.applicationConversation.push({
    role: "assistant",
    content: `${APPLICATION_INTRO}\n\nStart with the role that best matches the application you want to complete.`,
  })
  saveUiState()
}

async function ensureOnboardingConfig() {
  if (onboardingConfig) {
    return onboardingConfig
  }
  if (onboardingConfigPromise) {
    return onboardingConfigPromise
  }

  onboardingConfigPromise = fetchJson("/api/onboarding/config")
    .then((data) => {
      onboardingConfig = data
      if (uiState.activeMode === "apply") {
        renderApp("end")
      }
      return data
    })
    .finally(() => {
      onboardingConfigPromise = null
    })

  return onboardingConfigPromise
}

function applicationState() {
  return uiState.application
}

function clearApplicationFeedback() {
  const app = applicationState()
  app.errorMessage = ""
  app.noticeMessage = ""
}

function setApplicationError(message) {
  const app = applicationState()
  app.errorMessage = message
  app.noticeMessage = ""
}

function setApplicationNotice(message) {
  const app = applicationState()
  app.noticeMessage = message
  app.errorMessage = ""
}

async function switchMode(mode) {
  if (mode === uiState.activeMode) {
    return
  }

  if (mode === "apply") {
    showTyping("processing ...")
    try {
      await ensureOnboardingConfig()
      seedApplicationConversation()
      uiState.activeMode = "apply"
      saveUiState()
      renderApp("top")
    } catch (error) {
      uiState.activeMode = "apply"
      seedApplicationConversation()
      setApplicationError(error.message || "The application journey could not be loaded right now.")
      saveUiState()
      renderApp("top")
    } finally {
      hideTyping()
    }
    return
  }

  uiState.activeMode = "knowledge"
  saveUiState()
  renderApp("top")
  questionInput.focus()
}

function updateModeUi() {
  const isKnowledge = uiState.activeMode === "knowledge"

  modeKnowledge.classList.toggle("is-active", isKnowledge)
  modeApply.classList.toggle("is-active", !isKnowledge)
  modeKnowledge.setAttribute("aria-selected", String(isKnowledge))
  modeApply.setAttribute("aria-selected", String(!isKnowledge))

  modeCaption.textContent = isKnowledge
    ? "Answers based only on official MPS South Africa sources."
    : "Complete the live membership draft in this chat."
  if (isKnowledge) {
    composerNote.textContent = ""
    composerNote.classList.add("hidden")
  } else {
    composerNote.textContent =
      "Use the step cards below to continue the application. Switch back to Ask MPS for sourced answers."
    composerNote.classList.remove("hidden")
  }
  chatForm.classList.toggle("composer-hidden", !isKnowledge)
  newChatButton.textContent = isKnowledge ? "New chat" : "Start again"
}

function renderKnowledgeConversation(scrollMode) {
  messagesList.innerHTML = ""

  renderTextMessage(
    {
      role: "assistant",
      content: KNOWLEDGE_WELCOME,
      isWelcome: true,
    },
    "MPS Assistant"
  )

  for (const message of uiState.knowledgeConversation) {
    renderTextMessage(message, "MPS Assistant")
  }

  messagesStage.classList.toggle("is-empty", uiState.knowledgeConversation.length === 0)
  if (scrollMode === "top") {
    requestAnimationFrame(() => {
      messagesStage.scrollTop = 0
    })
  } else if (scrollMode === "latest") {
    scrollLatestMessageIntoView()
  } else {
    scrollMessagesToBottom()
  }
}

function renderApplicationConversation(scrollMode) {
  seedApplicationConversation()
  messagesList.innerHTML = ""

  for (const message of uiState.applicationConversation) {
    renderTextMessage(message, "MPS Application")
  }

  renderApplicationCardMessage()
  messagesStage.classList.remove("is-empty")
  if (scrollMode === "top") {
    requestAnimationFrame(() => {
      messagesStage.scrollTop = 0
    })
  } else if (scrollMode === "latest") {
    scrollLatestMessageIntoView()
  } else {
    scrollMessagesToBottom()
  }
}

function renderApp(scrollMode = "end") {
  updateModeUi()
  if (uiState.activeMode === "knowledge") {
    renderKnowledgeConversation(scrollMode)
  } else {
    renderApplicationConversation(scrollMode)
  }
}

function pushApplicationMessages(userText, assistantText, nextStep) {
  const app = applicationState()
  clearApplicationFeedback()
  if (userText) {
    uiState.applicationConversation.push({ role: "user", content: userText })
  }
  if (assistantText) {
    uiState.applicationConversation.push({ role: "assistant", content: assistantText })
  }
  app.currentStep = nextStep
  saveUiState()
}

function currentRole() {
  return onboardingConfig?.roles?.find((role) => role.id === applicationState().membershipCategory) || null
}

function money(value) {
  const rounded = Math.round(Number(value) || 0)
  return `R ${rounded.toLocaleString("en-ZA")}`
}

function monthlyEquivalent(rate) {
  return money(Math.ceil((Number(rate) || 0) / 12))
}

function minMembershipDate() {
  const dateValue = new Date()
  dateValue.setDate(dateValue.getDate() + 56)
  return dateValue.toISOString().split("T")[0]
}

function saleDates(startDate) {
  if (!startDate) {
    return { sale_start: "", sale_end: "", renewal: "" }
  }
  const start = new Date(`${startDate}T00:00:00`)
  if (Number.isNaN(start.getTime())) {
    return { sale_start: "", sale_end: "", renewal: "" }
  }

  const saleEnd = new Date(start)
  saleEnd.setFullYear(saleEnd.getFullYear() + 1)
  saleEnd.setDate(saleEnd.getDate() - 1)

  const renewal = new Date(saleEnd)
  renewal.setDate(renewal.getDate() + 1)

  return {
    sale_start: formatDateInputValue(start),
    sale_end: formatDateInputValue(saleEnd),
    renewal: formatDateInputValue(renewal),
  }
}

function formatDateInputValue(dateValue) {
  const year = dateValue.getFullYear()
  const month = String(dateValue.getMonth() + 1).padStart(2, "0")
  const day = String(dateValue.getDate()).padStart(2, "0")
  return `${year}-${month}-${day}`
}

function currentSaleCategory() {
  return currentRole()?.sale_category || ""
}

function paymentReference() {
  const fields = applicationState().fields
  const first = (fields.firstName || "").toUpperCase().replaceAll(" ", "").slice(0, 3) || "APP"
  const last = (fields.lastName || "").toUpperCase().replaceAll(" ", "").slice(0, 3) || "MPS"
  return `MPS-${first}${last}-${new Date().getFullYear()}`
}

function disclosureHelper(question) {
  const labels = (question.columns || [])
    .map((column) => column.label)
    .filter(Boolean)
  if (!labels.length) {
    return ""
  }
  return `Include: ${labels.join(", ")}.`
}

function applicationHeader(title, subtitle) {
  const stepIndex = Math.min(applicationState().currentStep, APPLICATION_STEP_LABELS.length - 1)
  return `
    <div class="journey-shell">
      <div class="journey-topline">
        <span class="journey-kicker">Application journey</span>
        <span class="journey-step-count">Step ${Math.min(applicationState().currentStep + 1, 8)} of 8</span>
      </div>
      <h3 class="journey-title">${escapeHtml(title)}</h3>
      <p class="journey-copy">${escapeHtml(subtitle)}</p>
      <div class="journey-progress">
        ${APPLICATION_STEP_LABELS.map((label, index) => {
          const stateClass =
            applicationState().currentStep > index
              ? "is-complete"
              : applicationState().currentStep === index
                ? "is-current"
                : ""
          return `<span class="journey-progress-pill ${stateClass}">${escapeHtml(label)}</span>`
        }).join("")}
      </div>
      ${buildApplicationFeedback()}
    `
}

function buildApplicationFeedback() {
  const app = applicationState()
  if (app.errorMessage) {
    return `<div class="journey-alert journey-alert-error">${escapeHtml(app.errorMessage)}</div>`
  }
  if (app.noticeMessage) {
    return `<div class="journey-alert journey-alert-info">${escapeHtml(app.noticeMessage)}</div>`
  }
  return ""
}

function buildRoleStep() {
  return `
    ${applicationHeader("Choose your role", "These are the roles currently available in the live portal.")}
      <div class="journey-choice-grid">
        ${onboardingConfig.roles
          .map((role) => {
            if (role.available_in_chat) {
              return `
                <button class="journey-choice-card" type="button" data-role="${escapeHtml(role.id)}">
                  <span class="journey-choice-title">${escapeHtml(role.title)}</span>
                  <span class="journey-choice-subtitle">${escapeHtml(role.subtitle)}</span>
                  <span class="journey-choice-badge">${escapeHtml(role.badge)}</span>
                </button>
              `
            }
            return `
              <a class="journey-choice-card journey-choice-card-muted" href="${escapeHtml(role.redirect_url)}" target="_blank" rel="noreferrer">
                <span class="journey-choice-title">${escapeHtml(role.title)}</span>
                <span class="journey-choice-subtitle">${escapeHtml(role.subtitle)}</span>
                <span class="journey-choice-badge">${escapeHtml(role.badge)}</span>
              </a>
            `
          })
          .join("")}
      </div>
      <p class="journey-footnote">If your role is not available in chat yet, you can carry on through the official MPS join pages.</p>
    </div>
  `
}

function buildContactStep() {
  const app = applicationState()
  const fields = app.fields
  const portalMessage = onboardingConfig?.portal_auth?.enabled
    ? onboardingConfig.portal_auth.message
    : "The chat uses the live OTP and draft application endpoints directly."
  return `
    ${applicationHeader("Contact details and verification", "Add the details MPS uses to start your application draft.")}
      <div class="journey-meta-chip">${escapeHtml(portalMessage)}</div>
      <div class="journey-form-grid journey-form-grid-2">
        <label class="journey-field">
          <span>First name</span>
          <input id="apply-first-name" data-field="firstName" type="text" value="${escapeHtml(fields.firstName)}" placeholder="e.g. Thabo" />
        </label>
        <label class="journey-field">
          <span>Surname</span>
          <input id="apply-last-name" data-field="lastName" type="text" value="${escapeHtml(fields.lastName)}" placeholder="e.g. Nkosi" />
        </label>
        <label class="journey-field">
          <span>Email address</span>
          <input id="apply-email" data-field="email" type="email" value="${escapeHtml(fields.email)}" placeholder="name@example.com" />
        </label>
        <label class="journey-field">
          <span>Confirm email</span>
          <input id="apply-confirm-email" data-field="confirmEmail" type="email" value="${escapeHtml(fields.confirmEmail)}" placeholder="Repeat email address" />
        </label>
      </div>

      <div class="journey-block">
        <div class="journey-block-head">
          <strong>Email verification</strong>
          <span class="journey-state-pill ${app.verified ? "is-verified" : ""}">${app.verified ? "Verified" : "Not verified"}</span>
        </div>
        <p class="journey-copy-small">The live portal also offers captcha, but this chat flow uses the email OTP path.</p>
        <div class="journey-inline-actions">
          <button class="journey-button journey-button-secondary" id="application-send-otp" type="button">
            ${app.otpSent ? "Resend code" : "Send verification code"}
          </button>
          <input id="application-otp-code" class="journey-inline-input" type="text" inputmode="numeric" maxlength="6" placeholder="6-digit code" ${app.verified ? "disabled" : ""} />
          <button class="journey-button" id="application-verify-otp" type="button" ${app.verified ? "disabled" : ""}>Verify</button>
        </div>
      </div>

      <div class="journey-block">
        <div class="journey-block-head">
          <strong>Consents</strong>
        </div>
        <div class="journey-toggle-stack">
          <button class="journey-check ${app.checkboxes.ack ? "is-checked" : ""}" type="button" data-checkbox-toggle="ack">
            <span class="journey-check-box">${app.checkboxes.ack ? "x" : ""}</span>
            <span>I acknowledge the application and authorisation wording.</span>
          </button>
          <button class="journey-check ${app.checkboxes.scd ? "is-checked" : ""}" type="button" data-checkbox-toggle="scd">
            <span class="journey-check-box">${app.checkboxes.scd ? "x" : ""}</span>
            <span>I consent to the use of special category data for the application.</span>
          </button>
        </div>
      </div>

      <div class="journey-block">
        <div class="journey-block-head">
          <strong>Marketing preference</strong>
        </div>
        <div class="journey-pill-row">
          <button class="journey-pill-button ${app.marketing === "yes" ? "is-selected" : ""}" type="button" data-marketing="yes">Yes, keep me informed</button>
          <button class="journey-pill-button ${app.marketing === "no" ? "is-selected" : ""}" type="button" data-marketing="no">No, thanks</button>
        </div>
      </div>

      <div class="journey-actions">
        <button class="journey-button journey-button-secondary" id="application-back" type="button">Back</button>
        <button class="journey-button" id="application-continue" type="button">Continue</button>
      </div>
    </div>
  `
}

function buildQuoteStep() {
  const app = applicationState()
  const fields = app.fields
  const role = currentRole()
  const quotePreview = app.selectedPrice
    ? `<div class="journey-quote-mini">Live quote ready: <strong>${money(app.selectedPrice.rate)}</strong> per year</div>`
    : ""

  return `
    ${applicationHeader("Quote details", "Choose the pricing inputs MPS uses for the live GP quote.")}
      ${quotePreview}
      <div class="journey-form-grid journey-form-grid-2">
        <label class="journey-field journey-field-full">
          <span>Selected role</span>
          <input type="text" value="${escapeHtml(role ? role.title : "")}" disabled />
        </label>
        <label class="journey-field journey-field-full">
          <span>GP pricing category</span>
          <select id="apply-gp-category" data-field="gpCategory">
            <option value="">Please select</option>
            ${onboardingConfig.pricing.categories
              .map(
                (item) =>
                  `<option value="${escapeHtml(item.value)}" ${fields.gpCategory === item.value ? "selected" : ""}>${escapeHtml(item.label)}</option>`
              )
              .join("")}
          </select>
        </label>
        ${
          fields.gpCategory === "intrapartum"
            ? `
              <label class="journey-field journey-field-full">
                <span>Intrapartum protection basis</span>
                <select id="apply-intrapartum" data-field="gpIntrapartumBasis">
                  <option value="">Please select</option>
                  ${onboardingConfig.pricing.intrapartum_bases
                    .map(
                      (item) =>
                        `<option value="${escapeHtml(item.value)}" ${fields.gpIntrapartumBasis === item.value ? "selected" : ""}>${escapeHtml(item.label)}</option>`
                    )
                    .join("")}
                </select>
              </label>
            `
            : `
              <label class="journey-field">
                <span>Weekly hours band</span>
                <select id="apply-hours-band" data-field="gpHoursBand">
                  <option value="">Please select</option>
                  ${onboardingConfig.pricing.hours_bands
                    .map(
                      (item) =>
                        `<option value="${escapeHtml(item.value)}" ${fields.gpHoursBand === item.value ? "selected" : ""}>${escapeHtml(item.label)}</option>`
                    )
                    .join("")}
                </select>
              </label>
            `
        }
        <label class="journey-field">
          <span>Desired membership start date</span>
          <input id="apply-start-date" data-field="membershipStartDate" type="date" min="${minMembershipDate()}" value="${escapeHtml(fields.membershipStartDate)}" />
        </label>
      </div>
      <p class="journey-footnote">Earliest available date is 8 weeks from today.</p>
      <div class="journey-actions">
        <button class="journey-button journey-button-secondary" id="application-back" type="button">Back</button>
        <button class="journey-button" id="application-continue" type="button">Get live quote</button>
      </div>
    </div>
  `
}

function buildUnderwritingStep() {
  const app = applicationState()
  const allQuestions = onboardingConfig.underwriting.flatMap((group) => group.questions)
  const answeredCount = allQuestions.filter((question) => ["yes", "no"].includes(app.underwritingAnswers[question.key])).length

  return `
    ${applicationHeader("Underwriting questions", "Answer these carefully and do not include patient names or confidential patient information.")}
      <div class="journey-inline-bar">
        <span>${answeredCount} / ${allQuestions.length} answered</span>
        <button class="journey-button journey-button-ghost" id="application-all-no" type="button">All No</button>
      </div>
      <div class="journey-question-groups">
        ${onboardingConfig.underwriting
          .map(
            (group) => `
              <section class="journey-question-group">
                <header>
                  <h4>${escapeHtml(group.title)}</h4>
                  <p>${escapeHtml(group.description)}</p>
                </header>
                <div class="journey-question-list">
                  ${group.questions
                    .map((question) => {
                      const answer = app.underwritingAnswers[question.key] || ""
                      const details = app.underwritingDetails[question.key] || ""
                      return `
                        <article class="journey-question-card">
                          <div class="journey-question-head">
                            <div>
                              <strong>${escapeHtml(question.prompt)}</strong>
                              ${question.note ? `<p>${escapeHtml(question.note)}</p>` : ""}
                              <p class="journey-footnote">${escapeHtml(disclosureHelper(question))}</p>
                            </div>
                            <div class="journey-pill-row journey-pill-row-tight">
                              <button class="journey-pill-button ${answer === "yes" ? "is-selected" : ""}" type="button" data-uw-answer="${escapeHtml(question.key)}" data-uw-value="yes">Yes</button>
                              <button class="journey-pill-button ${answer === "no" ? "is-selected" : ""}" type="button" data-uw-answer="${escapeHtml(question.key)}" data-uw-value="no">No</button>
                            </div>
                          </div>
                          ${
                            answer === "yes"
                              ? `
                                <label class="journey-field">
                                  <span>Disclosure details</span>
                                  <textarea data-uw-detail="${escapeHtml(question.key)}" rows="4" placeholder="${escapeHtml(disclosureHelper(question))}">${escapeHtml(details)}</textarea>
                                </label>
                                ${
                                  question.requires_upload
                                    ? `<p class="journey-footnote">You can note document filenames in the supporting documents step. The live portal currently treats uploads as a follow-up item.</p>`
                                    : ""
                                }
                              `
                              : ""
                          }
                        </article>
                      `
                    })
                    .join("")}
                </div>
              </section>
            `
          )
          .join("")}
      </div>
      <div class="journey-actions">
        <button class="journey-button journey-button-secondary" id="application-back" type="button">Back</button>
        <button class="journey-button" id="application-continue" type="button">Continue</button>
      </div>
    </div>
  `
}

function buildQuoteReviewStep() {
  const app = applicationState()
  const fields = app.fields
  const role = currentRole()
  const quote = app.selectedPrice
  const breakdown = quote
    ? `
      <div class="journey-price-hero">
        <div>
          <span class="journey-kicker">Indicative annual total</span>
          <strong>${money(quote.rate)}</strong>
        </div>
        <div class="journey-price-side">
          <span>Monthly equivalent</span>
          <strong>${monthlyEquivalent(quote.rate)}</strong>
        </div>
      </div>
      <dl class="journey-summary-grid">
        <div><dt>Role</dt><dd>${escapeHtml(role?.title || "-")}</dd></div>
        <div><dt>Pricing category</dt><dd>${escapeHtml(quote.category)}</dd></div>
        <div><dt>Hours or basis</dt><dd>${escapeHtml(quote.band)}</dd></div>
        <div><dt>Grade</dt><dd>${escapeHtml(quote.grade)}</dd></div>
        <div><dt>Membership start</dt><dd>${escapeHtml(fields.membershipStartDate || "-")}</dd></div>
        <div><dt>Status</dt><dd>Indicative only</dd></div>
      </dl>
    `
    : `<p class="journey-copy-small">The live quote has not loaded yet.</p>`

  const rateCardMarkup = buildRateCardMarkup()

  return `
    ${applicationHeader("Quote presented", "This is the current indicative price returned by the live MPS pricing API.")}
      ${breakdown}
      <div class="journey-alert journey-alert-warm">
        Final subscription is still subject to MPS underwriting review and approval.
      </div>
      ${rateCardMarkup}
      <div class="journey-actions">
        <button class="journey-button journey-button-secondary" id="application-back" type="button">Back</button>
        <button class="journey-button" id="application-continue" type="button">Continue</button>
      </div>
    </div>
  `
}

function buildRateCardMarkup() {
  const app = applicationState()
  const quote = app.selectedPrice
  if (!quote) {
    return ""
  }
  if (app.rateCardLoading) {
    return `<div class="journey-footnote">Loading the live rate card...</div>`
  }
  if (!app.rateCard) {
    return ""
  }

  if (quote.category === "GP INCLUDING INTRAPARTUM OBSTETRICS") {
    const rows = Object.entries(app.rateCard.intrapartum || {})
      .map(
        ([grade, item]) => `
          <tr class="${quote.grade === grade ? "is-highlighted" : ""}">
            <td>${escapeHtml(item.label)}</td>
            <td>${escapeHtml(grade)}</td>
            <td>${money(item.rate)}</td>
          </tr>
        `
      )
      .join("")
    return `
      <details class="journey-details">
        <summary>View the live intrapartum rate card</summary>
        <table class="journey-table">
          <thead><tr><th>Protection basis</th><th>Grade</th><th>Rate</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </details>
    `
  }

  const selectedMatrixEntry = Object.values(app.rateCard.matrix || {}).find((entry) => entry.label === quote.category)
  if (!selectedMatrixEntry) {
    return ""
  }

  const rows = Object.entries(app.rateCard.bands || {})
    .map(([key, label]) => {
      const band = selectedMatrixEntry.bands?.[key]
      if (!band) {
        return ""
      }
      const isHighlighted = quote.grade === band.grade
      return `
        <tr class="${isHighlighted ? "is-highlighted" : ""}">
          <td>${escapeHtml(label)}</td>
          <td>${escapeHtml(band.grade)}</td>
          <td>${money(band.rate)}</td>
        </tr>
      `
    })
    .join("")

  return `
    <details class="journey-details">
      <summary>View the live rate card for this category</summary>
      <table class="journey-table">
        <thead><tr><th>Band</th><th>Grade</th><th>Rate</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </details>
  `
}

function buildDetailsStep() {
  const app = applicationState()
  const fields = app.fields
  const sales = saleDates(fields.membershipStartDate)

  return `
    ${applicationHeader("Full details", "Complete the wider record used for MAPS and SAMA.")}
      <section class="journey-section-card">
        <h4>Personal</h4>
        <div class="journey-form-grid journey-form-grid-2">
          <label class="journey-field">
            <span>Gender</span>
            <select data-field="gender">
              <option value="">Please select</option>
              <option value="Male" ${fields.gender === "Male" ? "selected" : ""}>Male</option>
              <option value="Female" ${fields.gender === "Female" ? "selected" : ""}>Female</option>
              <option value="Other" ${fields.gender === "Other" ? "selected" : ""}>Other</option>
            </select>
          </label>
          <label class="journey-field">
            <span>Middle name(s)</span>
            <input data-field="middleNames" type="text" value="${escapeHtml(fields.middleNames)}" placeholder="Optional" />
          </label>
          <label class="journey-field">
            <span>Maiden or previous name</span>
            <input data-field="maidenName" type="text" value="${escapeHtml(fields.maidenName)}" placeholder="Optional" />
          </label>
          <label class="journey-field">
            <span>Initials</span>
            <input data-field="initials" type="text" value="${escapeHtml(fields.initials)}" placeholder="e.g. T.S." maxlength="10" />
          </label>
          <label class="journey-field">
            <span>Home phone</span>
            <input data-field="homePhone" type="tel" value="${escapeHtml(fields.homePhone)}" placeholder="Optional" />
          </label>
          <label class="journey-field">
            <span>Work phone</span>
            <input data-field="workPhone" type="tel" value="${escapeHtml(fields.workPhone)}" placeholder="Optional" />
          </label>
        </div>
      </section>

      <section class="journey-section-card">
        <h4>Address</h4>
        <div class="journey-form-grid">
          <label class="journey-field">
            <span>Address line 1</span>
            <input data-field="address1" type="text" value="${escapeHtml(fields.address1)}" placeholder="Street address or PO Box" />
          </label>
          <label class="journey-field">
            <span>Address line 2</span>
            <input data-field="address2" type="text" value="${escapeHtml(fields.address2)}" placeholder="Suburb or complex" />
          </label>
          <label class="journey-field">
            <span>Address line 3</span>
            <input data-field="address3" type="text" value="${escapeHtml(fields.address3)}" />
          </label>
        </div>
        <div class="journey-form-grid journey-form-grid-2">
          <label class="journey-field">
            <span>City</span>
            <input data-field="city" type="text" value="${escapeHtml(fields.city)}" placeholder="e.g. Johannesburg" />
          </label>
          <label class="journey-field">
            <span>Province or region</span>
            <select data-field="region">
              <option value="">Select province</option>
              ${onboardingConfig.provinces
                .map(
                  (item) =>
                    `<option value="${escapeHtml(item)}" ${fields.region === item ? "selected" : ""}>${escapeHtml(item)}</option>`
                )
                .join("")}
            </select>
          </label>
          <label class="journey-field">
            <span>Country</span>
            <input type="text" value="South Africa" disabled />
          </label>
          <label class="journey-field">
            <span>Postal code</span>
            <input data-field="postalCode" type="text" maxlength="4" value="${escapeHtml(fields.postalCode)}" placeholder="e.g. 2196" />
          </label>
        </div>
      </section>

      <section class="journey-section-card">
        <div class="journey-section-head">
          <h4>Qualifications</h4>
          <button class="journey-button journey-button-ghost" id="application-add-qualification" type="button">Add qualification</button>
        </div>
        <div class="journey-qualification-list">
          ${app.qualifications
            .map(
              (entry, index) => `
                <div class="journey-qualification-card">
                  <div class="journey-form-grid journey-form-grid-2">
                    <label class="journey-field">
                      <span>Country</span>
                      <input data-qualification-index="${index}" data-qualification-field="country" type="text" value="${escapeHtml(entry.country)}" />
                    </label>
                    <label class="journey-field">
                      <span>Institution</span>
                      <input data-qualification-index="${index}" data-qualification-field="institution" type="text" value="${escapeHtml(entry.institution)}" placeholder="e.g. University of Cape Town" />
                    </label>
                    <label class="journey-field">
                      <span>Qualification</span>
                      <input data-qualification-index="${index}" data-qualification-field="qualification" type="text" value="${escapeHtml(entry.qualification)}" placeholder="e.g. MBChB" />
                    </label>
                    <label class="journey-field">
                      <span>Month and year</span>
                      <input data-qualification-index="${index}" data-qualification-field="monthYear" type="month" value="${escapeHtml(entry.monthYear)}" />
                    </label>
                  </div>
                  ${
                    app.qualifications.length > 1
                      ? `<button class="journey-inline-remove" type="button" data-remove-qualification="${index}">Remove qualification</button>`
                      : ""
                  }
                </div>
              `
            )
            .join("")}
        </div>
      </section>

      <section class="journey-section-card">
        <h4>System fields</h4>
        <div class="journey-form-grid journey-form-grid-2">
          <label class="journey-field">
            <span>Client type</span>
            <select data-field="clientType">
              <option value="">Please select</option>
              ${onboardingConfig.client_types
                .map(
                  (item) =>
                    `<option value="${escapeHtml(item)}" ${fields.clientType === item ? "selected" : ""}>${escapeHtml(item)}</option>`
                )
                .join("")}
            </select>
          </label>
          <label class="journey-field">
            <span>MPS speciality</span>
            <input data-field="mpsSpeciality" type="text" value="${escapeHtml(fields.mpsSpeciality)}" placeholder="Optional classification" />
          </label>
          <label class="journey-field">
            <span>Sale start date</span>
            <input type="date" value="${escapeHtml(sales.sale_start)}" disabled />
          </label>
          <label class="journey-field">
            <span>Sale end date</span>
            <input type="date" value="${escapeHtml(sales.sale_end)}" disabled />
          </label>
          <label class="journey-field">
            <span>Renewal date</span>
            <input type="date" value="${escapeHtml(sales.renewal)}" disabled />
          </label>
          <label class="journey-field">
            <span>Sale category</span>
            <input type="text" value="${escapeHtml(currentSaleCategory())}" disabled />
          </label>
        </div>
      </section>

      <div class="journey-actions">
        <button class="journey-button journey-button-secondary" id="application-back" type="button">Back</button>
        <button class="journey-button" id="application-continue" type="button">Continue</button>
      </div>
    </div>
  `
}

function buildConfirmStep() {
  const app = applicationState()
  const quote = app.selectedPrice
  const fileList = app.uploadedFiles.length
    ? `
      <div class="journey-file-list">
        ${app.uploadedFiles
          .map((file) => `<div class="journey-file-chip">${escapeHtml(file.name)}</div>`)
          .join("")}
      </div>
    `
    : `<p class="journey-copy-small">No filenames added yet.</p>`

  return `
    ${applicationHeader("Documents and confirmation", "Add any filenames you want noted and confirm the application details.")}
      <section class="journey-section-card">
        <h4>Supporting documents</h4>
        <p class="journey-copy-small">The live portal currently treats document upload as a follow-up item. You can still note the filenames here for your own handover.</p>
        <label class="journey-file-picker">
          <span>Select local files</span>
          <input id="application-supporting-files" type="file" multiple />
        </label>
        ${fileList}
      </section>

      <section class="journey-section-card">
        <h4>Final confirmation</h4>
        ${
          quote
            ? `
              <dl class="journey-summary-grid">
                <div><dt>Indicative annual total</dt><dd>${money(quote.rate)}</dd></div>
                <div><dt>Indicative monthly equivalent</dt><dd>${monthlyEquivalent(quote.rate)}</dd></div>
              </dl>
            `
            : ""
        }
        <button class="journey-check ${app.checkboxes.acc ? "is-checked" : ""}" type="button" data-checkbox-toggle="acc">
          <span class="journey-check-box">${app.checkboxes.acc ? "x" : ""}</span>
          <span>I confirm the application details are accurate and complete.</span>
        </button>
      </section>

      <div class="journey-actions">
        <button class="journey-button journey-button-secondary" id="application-back" type="button">Back</button>
        <button class="journey-button" id="application-continue" type="button">Continue to collections</button>
      </div>
    </div>
  `
}

function buildCollectionsStep() {
  const app = applicationState()
  const quote = app.selectedPrice
  const method = app.fields.collectionMethod || "debit"
  const frequency = app.fields.collectionFrequency || "monthly"
  const annual = quote ? money(quote.rate) : "TBC"
  const monthly = quote ? monthlyEquivalent(quote.rate) : "TBC"

  let methodMarkup = ""
  if (method === "eft") {
    methodMarkup = `
      <div class="journey-section-card">
        <h4>EFT details</h4>
        <table class="journey-table">
          <tbody>
            ${EFT_BANK_DETAILS.map(([label, value]) => `<tr><td>${escapeHtml(label)}</td><td>${escapeHtml(value)}</td></tr>`).join("")}
            <tr><td>Reference</td><td><strong>${escapeHtml(paymentReference())}</strong></td></tr>
            <tr><td>Amount</td><td><strong>${frequency === "annual" ? annual : monthly}</strong></td></tr>
          </tbody>
        </table>
      </div>
    `
  } else if (method === "card") {
    methodMarkup = `
      <div class="journey-alert journey-alert-info">
        This chat does not collect card numbers or CVVs. After the draft reaches MPS, secure card setup should continue directly with the MPS team.
      </div>
    `
  } else {
    methodMarkup = `
      <div class="journey-alert journey-alert-info">
        This chat records your debit order preference, but it does not capture or store full bank credentials. MPS should complete the secure DebiCheck setup with you directly.
      </div>
    `
  }

  return `
    ${applicationHeader("Collections", "Choose your payment preference and submit the live draft.")}
      <div class="journey-price-hero">
        <div>
          <span class="journey-kicker">Monthly view</span>
          <strong>${monthly}</strong>
        </div>
        <div class="journey-price-side">
          <span>Annual view</span>
          <strong>${annual}</strong>
        </div>
      </div>

      <section class="journey-section-card">
        <h4>Billing frequency</h4>
        <div class="journey-pill-row">
          ${onboardingConfig.payment_frequencies
            .map(
              (item) =>
                `<button class="journey-pill-button ${frequency === item.id ? "is-selected" : ""}" type="button" data-frequency="${escapeHtml(item.id)}">${escapeHtml(item.label)}</button>`
            )
            .join("")}
        </div>
      </section>

      <section class="journey-section-card">
        <h4>Payment method</h4>
        <div class="journey-choice-grid journey-choice-grid-tight">
          ${onboardingConfig.payment_methods
            .map(
              (item) => `
                <button class="journey-choice-card ${method === item.id ? "journey-choice-card-selected" : ""}" type="button" data-payment-method="${escapeHtml(item.id)}">
                  <span class="journey-choice-title">${escapeHtml(item.label)}</span>
                  <span class="journey-choice-subtitle">${escapeHtml(item.subtitle)}</span>
                </button>
              `
            )
            .join("")}
        </div>
      </section>

      ${methodMarkup}
      <div class="journey-actions">
        <button class="journey-button journey-button-secondary" id="application-back" type="button">Back</button>
        <button class="journey-button" id="application-submit" type="button">${applicationPending ? "Submitting..." : "Submit application"}</button>
      </div>
    </div>
  `
}

function buildSuccessStep() {
  const app = applicationState()
  const result = app.submitResult || {}
  return `
    ${applicationHeader("Application submitted", "The live MPS draft lead has been saved.")}
      <div class="journey-success">
        <div class="journey-success-mark">OK</div>
        <h4>Your application draft is in.</h4>
        <p>${escapeHtml(result.message || "Draft lead saved.")}</p>
      </div>
      <dl class="journey-summary-grid">
        <div><dt>Lead ID</dt><dd>${escapeHtml(result.lead_id || "-")}</dd></div>
        <div><dt>Reference</dt><dd>${escapeHtml(result.reference || paymentReference())}</dd></div>
        <div><dt>Payment preference</dt><dd>${escapeHtml((result.payment_method || applicationState().fields.collectionMethod || "").toUpperCase())}</dd></div>
        <div><dt>Billing frequency</dt><dd>${escapeHtml((result.payment_frequency || applicationState().fields.collectionFrequency || "").toUpperCase())}</dd></div>
      </dl>
      <div class="journey-next-steps">
        <strong>What happens next</strong>
        <p>1. MPS reviews your application and disclosures.</p>
        <p>2. Underwriting confirms the final subscription.</p>
        <p>3. Your MPS membership number is issued via MAPS.</p>
        <p>4. The membership number is written back to the SAMA system.</p>
      </div>
      <div class="journey-actions">
        <button class="journey-button journey-button-secondary" id="application-restart" type="button">Start new application</button>
        <a class="journey-button" href="${escapeHtml(onboardingConfig.portal_url)}" target="_blank" rel="noreferrer">Open official portal</a>
      </div>
    </div>
  `
}

function buildApplicationCardHtml() {
  if (!onboardingConfig) {
    const errorMarkup = applicationState().errorMessage
      ? `<div class="journey-alert journey-alert-error">${escapeHtml(applicationState().errorMessage)}</div>`
      : ""
    return `
      <div class="journey-shell">
        <div class="journey-topline">
          <span class="journey-kicker">Application journey</span>
        </div>
        <h3 class="journey-title">Loading the live journey</h3>
        <p class="journey-copy">The chat is pulling the latest onboarding structure.</p>
        ${errorMarkup}
      </div>
    `
  }

  const step = applicationState().currentStep
  switch (step) {
    case 0:
      return buildRoleStep()
    case 1:
      return buildContactStep()
    case 2:
      return buildQuoteStep()
    case 3:
      return buildUnderwritingStep()
    case 4:
      return buildQuoteReviewStep()
    case 5:
      return buildDetailsStep()
    case 6:
      return buildConfirmStep()
    case 7:
      return buildCollectionsStep()
    default:
      return buildSuccessStep()
  }
}

function renderApplicationCardMessage() {
  const article = createElement("article", "message-row message-row-assistant")
  article.appendChild(createElement("div", "message-avatar", "MP"))

  const content = createElement("div", "message-stack message-stack-assistant")
  content.appendChild(createElement("p", "message-role", "MPS Application"))

  const bubble = createElement("div", "message-bubble assistant-bubble journey-bubble")
  bubble.innerHTML = buildApplicationCardHtml()
  content.appendChild(bubble)
  article.appendChild(content)
  messagesList.appendChild(article)
  bindApplicationCardEvents(bubble)
}

function bindApplicationCardEvents(container) {
  const app = applicationState()

  container.querySelectorAll("[data-role]").forEach((button) => {
    button.addEventListener("click", async () => {
      const roleId = button.getAttribute("data-role")
      const role = onboardingConfig.roles.find((item) => item.id === roleId)
      if (!role) {
        return
      }
      app.membershipCategory = roleId
      clearApplicationFeedback()
      pushApplicationMessages(role.title, "Next I need your contact details and email verification.", 1)
      renderApp("latest")
    })
  })

  container.querySelectorAll("[data-field]").forEach((input) => {
    const fieldName = input.getAttribute("data-field")
    const update = () => {
      app.fields[fieldName] = input.value
      if (fieldName === "email" || fieldName === "confirmEmail") {
        app.verified = false
        app.otpSent = false
      }
      saveUiState()
    }
    input.addEventListener("input", update)
    input.addEventListener("change", update)
  })

  container.querySelectorAll("[data-checkbox-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.getAttribute("data-checkbox-toggle")
      app.checkboxes[key] = !app.checkboxes[key]
      clearApplicationFeedback()
      saveUiState()
      renderApp("end")
    })
  })

  container.querySelectorAll("[data-marketing]").forEach((button) => {
    button.addEventListener("click", () => {
      app.marketing = button.getAttribute("data-marketing")
      clearApplicationFeedback()
      saveUiState()
      renderApp("end")
    })
  })

  container.querySelectorAll("[data-uw-answer]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.getAttribute("data-uw-answer")
      const value = button.getAttribute("data-uw-value")
      app.underwritingAnswers[key] = value
      if (value === "no") {
        app.underwritingDetails[key] = ""
      }
      clearApplicationFeedback()
      saveUiState()
      renderApp("end")
    })
  })

  container.querySelectorAll("[data-uw-detail]").forEach((textarea) => {
    const key = textarea.getAttribute("data-uw-detail")
    const update = () => {
      app.underwritingDetails[key] = textarea.value
      saveUiState()
    }
    textarea.addEventListener("input", update)
    textarea.addEventListener("change", update)
  })

  container.querySelectorAll("[data-qualification-index]").forEach((input) => {
    const index = Number(input.getAttribute("data-qualification-index"))
    const field = input.getAttribute("data-qualification-field")
    const update = () => {
      app.qualifications[index][field] = input.value
      saveUiState()
    }
    input.addEventListener("input", update)
    input.addEventListener("change", update)
  })

  container.querySelectorAll("[data-remove-qualification]").forEach((button) => {
    button.addEventListener("click", () => {
      const index = Number(button.getAttribute("data-remove-qualification"))
      app.qualifications.splice(index, 1)
      clearApplicationFeedback()
      saveUiState()
      renderApp("end")
    })
  })

  container.querySelectorAll("[data-frequency]").forEach((button) => {
    button.addEventListener("click", () => {
      app.fields.collectionFrequency = button.getAttribute("data-frequency")
      clearApplicationFeedback()
      saveUiState()
      renderApp("end")
    })
  })

  container.querySelectorAll("[data-payment-method]").forEach((button) => {
    button.addEventListener("click", () => {
      app.fields.collectionMethod = button.getAttribute("data-payment-method")
      clearApplicationFeedback()
      saveUiState()
      renderApp("end")
    })
  })

  const addQualification = container.querySelector("#application-add-qualification")
  if (addQualification) {
    addQualification.addEventListener("click", () => {
      app.qualifications.push(defaultQualification())
      clearApplicationFeedback()
      saveUiState()
      renderApp("end")
    })
  }

  const sendOtpButton = container.querySelector("#application-send-otp")
  if (sendOtpButton) {
    sendOtpButton.addEventListener("click", async () => {
      clearApplicationFeedback()
      if (!isValidEmail(app.fields.email || "")) {
        setApplicationError("Enter a valid email address first.")
        saveUiState()
        renderApp("end")
        return
      }
      showTyping("Sending the live verification code.")
      setApplicationPendingState(true)
      try {
        const data = await fetchJson("/api/onboarding/send-otp", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: app.fields.email }),
        })
        app.otpSent = true
        setApplicationNotice(data.message || "Verification code sent.")
        saveUiState()
        renderApp("end")
      } catch (error) {
        setApplicationError(error.message || "Unable to send the verification code.")
        saveUiState()
        renderApp("end")
      } finally {
        hideTyping()
        setApplicationPendingState(false)
      }
    })
  }

  const verifyOtpButton = container.querySelector("#application-verify-otp")
  const otpCodeInput = container.querySelector("#application-otp-code")
  if (verifyOtpButton && otpCodeInput) {
    verifyOtpButton.addEventListener("click", async () => {
      clearApplicationFeedback()
      showTyping("Checking the live verification code.")
      setApplicationPendingState(true)
      try {
        const data = await fetchJson("/api/onboarding/verify-otp", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: app.fields.email, code: otpCodeInput.value }),
        })
        app.verified = true
        app.otpSent = true
        setApplicationNotice(data.message || "Email verified.")
        saveUiState()
        renderApp("end")
      } catch (error) {
        setApplicationError(error.message || "Verification failed.")
        saveUiState()
        renderApp("end")
      } finally {
        hideTyping()
        setApplicationPendingState(false)
      }
    })
  }

  const supportingFiles = container.querySelector("#application-supporting-files")
  if (supportingFiles) {
    supportingFiles.addEventListener("change", () => {
      app.uploadedFiles = Array.from(supportingFiles.files || []).map((file) => ({
        name: file.name,
        size: file.size,
      }))
      setApplicationNotice(app.uploadedFiles.length ? `${app.uploadedFiles.length} filename(s) added to your local application summary.` : "")
      saveUiState()
      renderApp("end")
    })
  }

  const backButton = container.querySelector("#application-back")
  if (backButton) {
    backButton.addEventListener("click", () => {
      clearApplicationFeedback()
      app.currentStep = Math.max(0, app.currentStep - 1)
      saveUiState()
      renderApp("top")
    })
  }

  const allNoButton = container.querySelector("#application-all-no")
  if (allNoButton) {
    allNoButton.addEventListener("click", () => {
      for (const group of onboardingConfig.underwriting) {
        for (const question of group.questions) {
          app.underwritingAnswers[question.key] = "no"
          app.underwritingDetails[question.key] = ""
        }
      }
      clearApplicationFeedback()
      saveUiState()
      renderApp("end")
    })
  }

  const continueButton = container.querySelector("#application-continue")
  if (continueButton) {
    continueButton.addEventListener("click", async () => {
      await handleApplicationContinue()
    })
  }

  const submitButton = container.querySelector("#application-submit")
  if (submitButton) {
    submitButton.addEventListener("click", async () => {
      await handleApplicationSubmit()
    })
  }

  const restartButton = container.querySelector("#application-restart")
  if (restartButton) {
    restartButton.addEventListener("click", () => {
      resetApplicationJourney()
    })
  }
}

function isValidEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(String(value || "").trim())
}

function validateContactStep() {
  const fields = applicationState().fields
  const app = applicationState()
  if ((fields.firstName || "").trim().length < 2) {
    return "First name must be at least 2 characters."
  }
  if ((fields.lastName || "").trim().length < 2) {
    return "Surname must be at least 2 characters."
  }
  if (!isValidEmail(fields.email)) {
    return "Enter a valid email address."
  }
  if (fields.email !== fields.confirmEmail) {
    return "Email confirmation does not match."
  }
  if (!app.checkboxes.ack) {
    return "Accept the acknowledgement wording before continuing."
  }
  if (!app.checkboxes.scd) {
    return "Confirm the special category data consent before continuing."
  }
  if (!app.verified) {
    return "Verify your email address before continuing."
  }
  return ""
}

function validateQuoteStep() {
  const fields = applicationState().fields
  if (!fields.gpCategory) {
    return "Choose the GP pricing category."
  }
  if (fields.gpCategory === "intrapartum") {
    if (!fields.gpIntrapartumBasis) {
      return "Choose the intrapartum protection basis."
    }
  } else if (!fields.gpHoursBand) {
    return "Choose the weekly hours band."
  }
  if (!fields.membershipStartDate) {
    return "Choose the desired membership start date."
  }
  if (fields.membershipStartDate < minMembershipDate()) {
    return "Membership start date must be at least 8 weeks from today."
  }
  return ""
}

function validateUnderwritingStep() {
  const app = applicationState()
  const questions = onboardingConfig.underwriting.flatMap((group) => group.questions)
  for (const question of questions) {
    const answer = app.underwritingAnswers[question.key]
    if (answer !== "yes" && answer !== "no") {
      return "Answer every underwriting question before continuing."
    }
    if (answer === "yes" && !(app.underwritingDetails[question.key] || "").trim()) {
      return "Add disclosure details for every question answered yes."
    }
  }
  return ""
}

function qualificationIsComplete(entry) {
  return ["country", "institution", "qualification", "monthYear"].every((key) => String(entry?.[key] || "").trim())
}

function validateDetailsStep() {
  const fields = applicationState().fields
  const app = applicationState()
  if (!fields.gender) {
    return "Select the gender in full details."
  }
  if ((fields.address1 || "").trim().length < 3) {
    return "Address Line 1 is required."
  }
  if ((fields.city || "").trim().length < 2) {
    return "City is required."
  }
  if (!fields.region) {
    return "Choose the province or region."
  }
  if (!/^\d{4}$/.test(String(fields.postalCode || "").trim())) {
    return "Postal code must be 4 digits."
  }
  if (!fields.clientType) {
    return "Choose the client type."
  }
  if (!app.qualifications.some((entry) => qualificationIsComplete(entry))) {
    return "Add at least one complete qualification."
  }
  return ""
}

function validateConfirmStep() {
  if (!applicationState().checkboxes.acc) {
    return "Confirm the information accuracy statement before continuing."
  }
  return ""
}

async function loadRateCardIfNeeded() {
  const app = applicationState()
  if (app.rateCard || app.rateCardLoading) {
    return
  }
  app.rateCardLoading = true
  saveUiState()
  renderApp("end")
  try {
    app.rateCard = await fetchJson("/api/onboarding/rate-card")
  } catch (error) {
    setApplicationNotice(error.message || "The live rate card could not be loaded.")
  } finally {
    app.rateCardLoading = false
    saveUiState()
    renderApp("end")
  }
}

async function handleApplicationContinue() {
  const app = applicationState()
  clearApplicationFeedback()

  if (app.currentStep === 1) {
    const error = validateContactStep()
    if (error) {
      setApplicationError(error)
      saveUiState()
      renderApp("end")
      return
    }
    pushApplicationMessages(
      "Contact details added and email verified.",
      "Now choose the live pricing inputs so I can pull the current quote.",
      2
    )
    renderApp("latest")
    return
  }

  if (app.currentStep === 2) {
    const error = validateQuoteStep()
    if (error) {
      setApplicationError(error)
      saveUiState()
      renderApp("end")
      return
    }

    showTyping("Pulling the live quote from MPS.")
    setApplicationPendingState(true)
    try {
      const data = await fetchJson("/api/onboarding/quote", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          gp_category: app.fields.gpCategory,
          gp_hours_band: app.fields.gpHoursBand || null,
          gp_intrapartum_basis: app.fields.gpIntrapartumBasis || null,
        }),
      })
      app.selectedPrice = data.payload?.price || data.price || null
      pushApplicationMessages(
        "Quote details captured.",
        "Answer the underwriting questions as fully as you can.",
        3
      )
      renderApp("latest")
    } catch (error) {
      setApplicationError(error.message || "The live quote could not be loaded.")
      saveUiState()
      renderApp("end")
    } finally {
      hideTyping()
      setApplicationPendingState(false)
    }
    return
  }

  if (app.currentStep === 3) {
    const error = validateUnderwritingStep()
    if (error) {
      setApplicationError(error)
      saveUiState()
      renderApp("end")
      return
    }
    pushApplicationMessages(
      "Underwriting answers completed.",
      "Here is the indicative quote summary from the live pricing API.",
      4
    )
    renderApp("latest")
    void loadRateCardIfNeeded()
    return
  }

  if (app.currentStep === 4) {
    pushApplicationMessages(
      "Quote reviewed.",
      "Now complete the wider record used for MAPS and SAMA.",
      5
    )
    renderApp("latest")
    return
  }

  if (app.currentStep === 5) {
    const error = validateDetailsStep()
    if (error) {
      setApplicationError(error)
      saveUiState()
      renderApp("end")
      return
    }
    pushApplicationMessages(
      "Full details completed.",
      "Add any supporting document filenames you want noted, then confirm the application details.",
      6
    )
    renderApp("latest")
    return
  }

  if (app.currentStep === 6) {
    const error = validateConfirmStep()
    if (error) {
      setApplicationError(error)
      saveUiState()
      renderApp("end")
      return
    }
    pushApplicationMessages(
      "Documents reviewed and application confirmed.",
      "Choose your payment preference and submit the live draft.",
      7
    )
    renderApp("latest")
  }
}

async function handleApplicationSubmit() {
  const app = applicationState()
  clearApplicationFeedback()
  if (!app.selectedPrice) {
    setApplicationError("Load the live quote before submitting the application.")
    saveUiState()
    renderApp("end")
    return
  }

  showTyping("Submitting the live MPS draft application.")
  setApplicationPendingState(true)
  try {
    const underwritingRows = {}
    for (const [key, answer] of Object.entries(app.underwritingAnswers)) {
      if (answer === "yes") {
        underwritingRows[key] = [{ details: app.underwritingDetails[key] || "" }]
      } else {
        underwritingRows[key] = []
      }
    }

    const payload = {
      current_step: 7,
      membership_category: app.membershipCategory,
      verified: app.verified,
      marketing: app.marketing,
      checkboxes: app.checkboxes,
      fields: app.fields,
      qualifications: app.qualifications,
      underwriting_answers: app.underwritingAnswers,
      underwriting_rows: underwritingRows,
    }

    const data = await fetchJson("/api/onboarding/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })

    app.submitResult = data.payload || {}
    clearApplicationFeedback()
    uiState.applicationConversation.push({ role: "user", content: "Submit application." })
    app.currentStep = 8
    saveUiState()
    renderApp("latest")
  } catch (error) {
    setApplicationError(error.message || "The live application draft could not be saved.")
    saveUiState()
    renderApp("end")
  } finally {
    hideTyping()
    setApplicationPendingState(false)
  }
}

function resetApplicationJourney() {
  uiState.application = defaultApplicationState()
  uiState.applicationConversation = []
  seedApplicationConversation()
  saveUiState()
  renderApp("top")
}

toggleChatbox.addEventListener("click", () => {
  setChatboxOpen(false)
})

chatLauncher.addEventListener("click", () => {
  setChatboxOpen(true)
})

newChatButton.addEventListener("click", () => {
  if (uiState.activeMode === "knowledge") {
    uiState.knowledgeConversation = []
    saveUiState()
    renderApp("top")
    questionInput.value = ""
    autoResizeComposer()
    questionInput.focus()
    return
  }

  resetApplicationJourney()
})

modeKnowledge.addEventListener("click", async () => {
  await switchMode("knowledge")
})

modeApply.addEventListener("click", async () => {
  await switchMode("apply")
})

questionInput.addEventListener("input", autoResizeComposer)
questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault()
    chatForm.requestSubmit()
  }
})

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault()
  await sendQuestion()
})

renderApp(uiState.activeMode === "knowledge" && uiState.knowledgeConversation.length ? "end" : "top")
autoResizeComposer()
