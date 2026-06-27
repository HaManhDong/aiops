export async function* readSSEStream(response: Response): AsyncGenerator<{ event: string; data: unknown }> {
  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ""

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const parts = buffer.split("\n\n")
    buffer = parts.pop() ?? ""

    for (const part of parts) {
      const lines = part.split("\n")
      let event = "message"
      let data = ""
      for (const line of lines) {
        if (line.startsWith("event: ")) event = line.slice(7).trim()
        if (line.startsWith("data: ")) data = line.slice(6)
      }
      if (data) {
        try {
          yield { event, data: JSON.parse(data) }
        } catch {
          // skip malformed
        }
      }
    }
  }
}
