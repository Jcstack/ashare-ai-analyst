/** Generic rich card — fallback renderer for unknown card types.
 *  Attempts to render common fields (title, summary, content) with
 *  markdown before falling back to raw JSON dump. */

import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

interface GenericCardProps {
  props: Record<string, unknown>
}

export function GenericCard({ props }: GenericCardProps) {
  const title = typeof props.title === "string" ? props.title : undefined
  const summary = typeof props.summary === "string" ? props.summary : undefined
  const content = typeof props.content === "string" ? props.content : undefined
  const text = summary || content

  // If we have recognizable text fields, render them nicely
  if (title || text) {
    return (
      <div className="rounded-md border bg-bg-surface p-4 space-y-2">
        {title && (
          <p className="font-semibold text-sm">{title}</p>
        )}
        {text && (
          <div className="prose prose-sm dark:prose-invert max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
          </div>
        )}
      </div>
    )
  }

  // Fallback: raw JSON
  return (
    <div className="rounded-md border bg-bg-surface p-3">
      <pre className="text-xs text-muted-foreground overflow-x-auto whitespace-pre-wrap break-words">
        {JSON.stringify(props, null, 2)}
      </pre>
    </div>
  )
}
