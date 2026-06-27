import { ChatWindow } from "@/components/chat/ChatWindow"

interface Props { params: Promise<{ session_id: string }> }

export default async function ChatSessionPage({ params }: Props) {
  const { session_id } = await params
  return <ChatWindow initialSessionId={session_id} />
}
