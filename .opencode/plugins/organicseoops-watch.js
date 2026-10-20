import { mkdirSync, readFileSync, renameSync, unlinkSync, writeFileSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"
import { OpencodeClient } from "@opencode-ai/sdk/v2"

export default async ({ client, directory }) => {
  const root = join(process.env.XDG_STATE_HOME || join(homedir(), ".local/state"), "organicseoops-opencode")
  mkdirSync(root, { recursive: true, mode: 0o700 })
  const file = join(root, `${process.pid}.json`)
  const start = readFileSync(`/proc/${process.pid}/stat`, "utf8").split(") ").pop().split(" ")[19]
  const unattended = process.env.ORGANICSEOOPS_UNATTENDED === "1"
  // Reuse OpenCode's in-process transport: a TUI worker need not expose a TCP port.
  const api = new OpencodeClient({ client: client._client })
  const sessions = {}
  let healthy = false
  let polling = false
  let disposed = false
  let revision = 0
  const answering = new Set()

  function save() {
    if (disposed) return
    writeFileSync(`${file}.tmp`, JSON.stringify({ pid: process.pid, start, directory, updated: Date.now(), healthy, sessions }), { mode: 0o600 })
    renameSync(`${file}.tmp`, file)
  }

  async function answer(request) {
    if (answering.has(request.id)) return
    answering.add(request.id)
    try {
      const answers = request.questions.map(({ options }) => {
        // ponytail: infer tags from text; use explicit option metadata if OpenCode adds it.
        const matches = (text, word) => new RegExp(`\\b${word}\\b`, "i").test(text)
          && !new RegExp(`\\b(?:not|non)[ -]+${word}\\b`, "i").test(text)
        const tagged = (word) => options.find((option) => matches(option.label, word))
          || options.find((option) => matches(option.description, word))
        const choice = tagged("recommended") || tagged("default") || options[0]
        return [choice?.label || "Use your best judgment within CONTINUE.md and the existing authorized scope; continue without waiting for me."]
      })
      await api.question.reply({ directory, requestID: request.id, answers }, { throwOnError: true, signal: AbortSignal.timeout(5000) })
    } finally {
      answering.delete(request.id)
    }
  }

  async function approve(request) {
    await api.permission.reply({ directory, requestID: request.id, reply: "once" }, { throwOnError: true, signal: AbortSignal.timeout(5000) })
  }

  async function refresh() {
    if (polling || disposed) return
    polling = true
    try {
      const version = revision
      const { data } = await api.session.status({ directory }, { throwOnError: true, signal: AbortSignal.timeout(5000) })
      if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("Invalid session status")
      if (version === revision) {
        for (const id of Object.keys(sessions)) delete sessions[id]
        for (const [id, status] of Object.entries(data)) sessions[id] = status?.type || "unknown"
      }
      if (unattended) {
        const questions = await api.question.list({ directory }, { throwOnError: true, signal: AbortSignal.timeout(5000) })
        for (const request of questions.data) await answer(request)
        const permissions = await api.permission.list({ directory }, { throwOnError: true, signal: AbortSignal.timeout(5000) })
        for (const request of permissions.data) await approve(request)
      }
      healthy = true
    } catch (error) {
      healthy = false
      if (process.env.ORGANICSEOOPS_WATCH_DEBUG === "1") console.error("OrganicSEOOps tracking refresh:", error)
    } finally {
      polling = false
      save()
    }
  }

  save()
  // Do not await requests during plugin initialization: that can re-enter instance setup.
  const initial = setTimeout(refresh, 1000)
  const timer = setInterval(refresh, 15000)
  initial.unref()
  timer.unref()
  return {
    event: async ({ event }) => {
      const input = event.properties
      if (event.type === "session.status") sessions[input.sessionID] = input.status.type
      if (event.type === "session.idle") delete sessions[input.sessionID]
      if (event.type === "session.deleted") delete sessions[input.info.id]
      if (["session.status", "session.idle", "session.deleted"].includes(event.type)) {
        revision++
        save()
      }
      if (!unattended) return
      try {
        if (event.type === "question.asked") await answer(input)
        if (event.type === "permission.asked") await approve(input)
      } catch {
        healthy = false
        save()
      }
    },
    dispose: async () => {
      disposed = true
      clearTimeout(initial)
      clearInterval(timer)
      try { unlinkSync(file) } catch (error) { if (error.code !== "ENOENT") throw error }
    },
  }
}
